"""Config edits reach the next run and never change a past one.

Runs are executed by the real executor with scripted models, so this test commits (like
test_executor). It works on its own uniquely named rows and restores the seeded rows it touches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import delete, select, update

from contract_extraction.domain.enums import RunKind, RunState
from contract_extraction.ingestion import register_file
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import ConfigRepo, RunRepo
from contract_extraction.persistence.repositories.config_writes import ConfigWriter
from contract_extraction.persistence.repositories.results import ResultRepo
from contract_extraction.pipeline.options import RunOptions, narrow
from test_executor import FIELDS, Harness


def _enqueue(h: Harness, pipeline: str):
    doc_id, _, _ = register_file(h.db, h.storage, h.settings, h.pdf)
    options = RunOptions(fields=FIELDS)
    with h.db.session() as s:
        return RunRepo(s).enqueue(doc_id, narrow(ConfigRepo(s).resolve_pipeline(pipeline), options), RunKind.FULL,
                                  options.model_dump(exclude_defaults=True)).id


def _snapshot(db, run_id) -> dict:
    with db.session() as s:
        return RunRepo(s).get(run_id).config_snapshot


def _best(db, run_id) -> list:
    with db.session() as s:
        return [(b["field_key"], b["retrieval_config"], b["value"], b["verdict"]) for b in ResultRepo(s).best_values(run_id)]


def test_edits_reach_the_next_run_and_never_change_a_past_one(db, storage, tmp_path):
    tag = uuid.uuid4().hex[:6]
    rag_a, rag_b, name = f"inv-a-{tag}", f"inv-b-{tag}", f"inv-{tag}"
    with db.session() as s:
        title = s.scalars(select(m.Field).where(m.Field.key == "title")).one()
        original = (title.id, title.user_prompt, [q.query for q in title.queries])

    try:
        with db.session() as s:
            w = ConfigWriter(s)
            loose = {"score_threshold": Decimal("0"), "min_score": Decimal("0")}
            w.create_retrieval({"name": rag_a, "top_k": 10, **loose})
            w.create_retrieval({"name": rag_b, "top_k": 5, **loose})
            default = ConfigRepo(s).resolve_pipeline()
            w.create_pipeline({
                "name": name, "description": None, "decomposition": default.decomposition.name, "index": default.index.name,
                "field_set": {"name": default.field_set.name, "version": default.field_set.version},
                "extraction_profile": default.extraction_profile.name,
                "extraction_prompt": {"name": default.extraction_prompt.name, "version": default.extraction_prompt.version},
                "judge_enabled": True, "judge_profile": default.judge_profile.name,
                "judge_prompt": {"name": default.judge_prompt.name, "version": default.judge_prompt.version},
                "judge_parallel": False, "retrievals": [rag_a, rag_b],
            })

        h = Harness(db, storage, tmp_path, "invariant")
        run_a = _enqueue(h, name)
        assert h.execute(run_a) == RunState.SUCCEEDED
        snap_a, best_a = _snapshot(db, run_a), _best(db, run_a)
        assert [r["name"] for r in snap_a["retrievals"]] == [rag_a, rag_b]

        with db.session() as s:
            w = ConfigWriter(s)
            w.update_retrieval(rag_a, {"top_k": 3})
            version = w.create_prompt_version("extraction_system", "Edited system prompt.", None).version
            w.update_pipeline(name, {"retrievals": [rag_b, rag_a],
                                     "extraction_prompt": {"name": "extraction_system", "version": version}})
            # A hand-written prompt replaces the generic one; the scripted model reads the field key from it.
            w.update_field(original[0], {"user_prompt": "Task: extract the following field:\ntitle\nEDITED-7C\n",
                                         "queries": ["the heading"]})

        run_b = _enqueue(h, name)
        snap_b = _snapshot(db, run_b)
        assert [(r["name"], r["top_k"]) for r in snap_b["retrievals"]] == [(rag_b, 5), (rag_a, 3)]
        assert (snap_b["extraction_prompt"]["version"], snap_b["extraction_prompt"]["body"]) == (version, "Edited system prompt.")
        title_a = next(f for f in snap_a["field_set"]["fields"] if f["key"] == "title")
        title_b = next(f for f in snap_b["field_set"]["fields"] if f["key"] == "title")
        assert title_a["user_prompt"] is None
        assert title_b["user_prompt"].endswith("EDITED-7C\n") and title_b["queries"] == ["the heading"]

        assert _snapshot(db, run_a) == snap_a, "a past run's snapshot never changes"
        assert _best(db, run_a) == best_a, "nor do its best values"
        assert h.execute(run_b) == RunState.SUCCEEDED
        assert any("EDITED-7C" in c for c in h.extractor.calls)
    finally:
        # Put the shared test database back as the seed left it (other tests count its rows).
        with db.session() as s:
            ConfigWriter(s).update_field(original[0], {"user_prompt": original[1], "queries": original[2]})
            pipeline_id = select(m.PipelineConfig.id).where(m.PipelineConfig.name == name).scalar_subquery()
            s.execute(delete(m.Run).where(m.Run.pipeline_config_id == pipeline_id))
            s.execute(delete(m.PipelineConfig).where(m.PipelineConfig.name == name))
            s.execute(delete(m.RetrievalConfig).where(m.RetrievalConfig.name.in_([rag_a, rag_b])))
            # Prompts are never deleted through the API; remove this test's version and reactivate v1.
            s.execute(delete(m.PromptTemplate).where(m.PromptTemplate.name == "extraction_system", m.PromptTemplate.version > 1))
            s.execute(update(m.PromptTemplate).where(m.PromptTemplate.name == "extraction_system",
                                                     m.PromptTemplate.version == 1).values(is_active=True))
