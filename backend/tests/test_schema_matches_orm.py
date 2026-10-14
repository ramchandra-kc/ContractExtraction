"""docker/schema.sql is the source of truth; persistence/models.py must mirror it exactly."""

from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.engine import Engine

from contract_extraction.persistence.models import Base, views


@pytest.fixture(scope="module")
def insp(engine: Engine):
    return inspect(engine)


def test_same_tables(insp):
    assert set(insp.get_table_names()) == set(Base.metadata.tables)


def test_same_views(insp):
    assert set(insp.get_view_names()) == set(views.tables)
    for name, table in views.tables.items():
        assert [c["name"] for c in insp.get_columns(name)] == [c.name for c in table.columns], name


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_same_columns(insp, engine: Engine, table: str):
    orm = Base.metadata.tables[table]
    db_cols = {c["name"]: c for c in insp.get_columns(table)}
    assert set(db_cols) == {c.name for c in orm.columns}, "column names differ"
    for col in orm.columns:
        db_col = db_cols[col.name]
        assert db_col["nullable"] == col.nullable, f"{table}.{col.name} nullability"
        orm_type = col.type.compile(dialect=engine.dialect)
        db_type = db_col["type"].compile(dialect=engine.dialect)
        assert orm_type == db_type, f"{table}.{col.name} type: ORM {orm_type} vs DB {db_type}"


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_same_keys(insp, table: str):
    orm = Base.metadata.tables[table]

    assert set(insp.get_pk_constraint(table)["constrained_columns"]) == {c.name for c in orm.primary_key}

    db_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]),
         (fk["options"].get("ondelete") or "NO ACTION").upper())
        for fk in insp.get_foreign_keys(table)
    }
    orm_fks = {
        (tuple(e.parent.name for e in fk.elements), fk.referred_table.name, tuple(e.column.name for e in fk.elements),
         (fk.ondelete or "NO ACTION").upper())
        for fk in orm.foreign_key_constraints
    }
    assert orm_fks == db_fks, "foreign keys differ"

    db_uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints(table)}
    orm_uniques = {tuple(c.name for c in u.columns) for u in orm.constraints if isinstance(u, UniqueConstraint)}
    orm_uniques |= {(c.name,) for c in orm.columns if c.unique}
    assert orm_uniques == db_uniques, "unique constraints differ"
