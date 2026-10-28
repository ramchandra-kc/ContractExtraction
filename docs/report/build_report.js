// Builds the research report (Word). Figures come from make_figures.py.
//   uv run --no-project --with matplotlib python docs/report/make_figures.py
//   NODE_PATH=<dir with node_modules/docx> node docs/report/build_report.js
// Text supports **bold** and *italic*. Each new experiment adds a results subsection and its table rows here.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Footer, Header,
  AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType, LevelFormat, PageNumber,
} = require("docx");

const HERE = __dirname;
const OUT = path.join(HERE, "ContractExtraction-Research-Report.docx");
const FONT = "Times New Roman";
const CONTENT_WIDTH = 9638; // A4 with 2 cm margins, in DXA

// ---------- helpers ----------

function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const p = (text, opts = {}) =>
  new Paragraph({ children: runs(text), alignment: AlignmentType.JUSTIFIED, spacing: { after: 140, line: 276 }, ...opts });
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
const bullet = (text) =>
  new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(text), spacing: { after: 80, line: 276 } });
const numbered = (text, ref = "rq") =>
  new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(text), spacing: { after: 80, line: 276 } });
const caption = (text) =>
  new Paragraph({ children: runs(text, { size: 19 }), alignment: AlignmentType.LEFT, spacing: { before: 60, after: 220 } });
const tableTitle = (text) =>
  new Paragraph({ children: runs(text, { size: 19 }), keepNext: true, spacing: { before: 200, after: 80 } });
const pending = (text) =>
  new Paragraph({
    children: [new TextRun({ text: "[Pending] ", bold: true, color: "B45309" }), ...runs(text, { color: "6B6B6B" })],
    shading: { type: ShadingType.CLEAR, fill: "FFF7E6", color: "auto" },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: "F59E0B", space: 6 } },
    spacing: { before: 80, after: 160 },
  });

const thin = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

// Booktabs-style table: rules above and below the header and at the bottom only.
function table(header, body, widths, { firstColLeft = true, left = false } = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scale = CONTENT_WIDTH / total;
  const w = widths.map((x) => Math.round(x * scale));
  w[w.length - 1] += CONTENT_WIDTH - w.reduce((a, b) => a + b, 0);
  const cell = (text, i, { bold = false, top = none, bottom = none, keep = true } = {}) =>
    new TableCell({
      width: { size: w[i], type: WidthType.DXA },
      borders: { top, bottom, left: none, right: none },
      margins: { top: 50, bottom: 50, left: 80, right: 80 },
      children: [
        new Paragraph({
          alignment: left || (i === 0 && firstColLeft) ? AlignmentType.LEFT : AlignmentType.CENTER,
          keepNext: keep, // keeps the table on one page
          children: runs(String(text), { size: 18, bold }),
        }),
      ],
    });
  const rows = [
    new TableRow({ tableHeader: true, children: header.map((t, i) => cell(t, i, { bold: true, top: thin, bottom: thin })) }),
    ...body.map(
      (r, ri) => new TableRow({ children: r.map((t, i) => cell(t, i, { bottom: ri === body.length - 1 ? thin : none, keep: ri < body.length - 1 })) }),
    ),
  ];
  return new Table({ width: { size: CONTENT_WIDTH, type: WidthType.DXA }, columnWidths: w, rows });
}

function figure(file, widthPx, heightPx) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    keepNext: true,
    spacing: { before: 160 },
    children: [
      new ImageRun({
        type: "png",
        data: fs.readFileSync(path.join(HERE, "figures", file)),
        transformation: { width: widthPx, height: heightPx },
        altText: { title: file, description: file, name: file },
      }),
    ],
  });
}

// ---------- numbers (computed by make_figures.py from the experiment exports) ----------

const N = JSON.parse(fs.readFileSync(path.join(HERE, "figures", "numbers.json"), "utf8"));
const A = N.arms, R = N.retrieval, D6 = N.e6_diff, D8 = N.e8_diff, AT = N.attribution, INV = N.invented_by_field, G = N.grader;
const CUR = "or-llama31-8b", RB = "e1-qwen3-rbase", K5 = "e6-qwen3-k5", K10 = "e6-qwen3-k10", K20 = "e6-qwen3-k20";
const RR = "e6-qwen3-k5-rr", NULLP = "e8-qwen3-k5-nullpolicy", RRM = "bge-reranker-v2-m3-int8";
const E6ARMS = [K5, K10, K20, RR];
const LBL = Object.fromEntries(Object.entries(A).map(([k, v]) => [k, v.label]));

const MINUS = "−";
const num = (x, d) => (x < 0 ? MINUS : "") + Math.abs(x).toFixed(d);
const sgn = (x, d = 3) => (x < 0 ? MINUS : "+") + Math.abs(x).toFixed(d);
const f2 = (x) => x.toFixed(2);
const f3 = (x) => x.toFixed(3);
const pc = (x, d = 1) => `${(100 * x).toFixed(d)}%`;
const usd = (x) => x.toFixed(4);
const int = (x) => Math.round(x).toLocaleString("en-US");
const pv = (p) => (p < 0.001 ? "< 0.001" : p.toFixed(3));
const ptsOf = (x) => num(100 * x, 1);
// A paired difference with its 95% CI; scale -1 reports the reverse comparison, scale 100 percentage points.
function ci(d, scale = 1, dec = scale === 100 ? 1 : 3) {
  const [lo, hi] = scale < 0 ? [d.hi * scale, d.lo * scale] : [d.lo * scale, d.hi * scale];
  return `${sgn(d.diff * scale, dec)} [${sgn(lo, dec)}, ${sgn(hi, dec)}]`;
}
const pts = (d) => ci(d, 100);
const star = (d, points = false) => (points ? pts(d) : ci(d)) + (d.p_holm !== null && d.p_holm < 0.05 ? "*" : "");
const retr = (r, hitDec = 1) => [pc(r.recall), pc(r.recall_at_1), f3(r.mrr), r.mean_hits.toFixed(hitDec)];
const sw = (name, k) => R.sweep[`${name} k=${k} t=0 q=20`];
const rk = (base, reranker, c) => R.rerank[`${base} k=5 q=20 r=${reranker} c=${c}`];
const gain = (base, c) => R.rerank_gain[`${base} k=5 q=20 r=${RRM} c=${c}`];
const rgain = (base, c) => {
  const g = gain(base, c);
  return `${sgn(100 * g.diff, 1)} [${sgn(100 * g.lo, 1)}, ${sgn(100 * g.hi, 1)}]${g.p_holm < 0.05 ? "*" : " (n.s.)"}`;
};
// One Table 8 row over the E6 arms, the best value in bold.
function row6(label, key, fmt, higherIsBetter) {
  const vals = E6ARMS.map((a) => A[a][key]);
  const best = higherIsBetter ? Math.max(...vals) : Math.min(...vals);
  return [label, ...vals.map((v) => (v === best ? `**${fmt(v)}**` : fmt(v)))];
}
const copied = (arm, label) => N.copied_example[`${arm}|${label}`] || 0;
const CP = (arm) => copied(arm, "absent");
const COPIED_ABSENT = [K5, K10, K20, RR, NULLP].reduce((s, a) => s + copied(a, "absent"), 0);
const COPIED_VALUE = [K5, K10, K20, RR, NULLP].reduce((s, a) => s + copied(a, "value"), 0);
const CAUSE = {
  expiration_date: "an expiry relative to an event (e.g. 90 days after termination) where the label is empty",
  uncapped_liabilities: "the definition's example list (fraud, IP, data breach), copied verbatim",
  initial_term: "a duration derived from dates the contract gives",
  document_status: "\"executed\"; every such label has low or medium confidence",
  execution_date: "dates from elsewhere in the text, some placeholders (2026-01-01)",
};
const GRADING_COST = 0.12 + 0.10 + 0.02 + 0.02 + 0.27; // printed by `experiment semantic` and the cross-check
const SPENT = N.cost_log.reduce((s, e) => s + e.cost, 0) + GRADING_COST;
const C = N.code.components;
const TESTS = { backend: 397, live: 5, gateway: 18, frontend: 53 }; // pytest / vitest on 28 October 2026
const SRC = ["backend", "gateway", "frontend", "sql", "scripts"], TST = ["backend_tests", "gateway_tests", "frontend_tests"];
const SRC_FILES = SRC.reduce((s, k) => s + C[k].files, 0), SRC_LINES = SRC.reduce((s, k) => s + C[k].lines, 0);
const TEST_FILES = TST.reduce((s, k) => s + C[k].files, 0), TEST_LINES = TST.reduce((s, k) => s + C[k].lines, 0);

const progress = [
  h1("Progress at a Glance"),
  p(
    "This progress report covers the first phase of a research programme on what improves LLM-based contract extraction. The platform, the " +
    "evaluation tooling and four of the thirteen planned experiments are complete and a fifth has started; all results are on the development split (36 contracts), and the " +
    `held-out test split (108 contracts) has not been touched. LLM spending so far is about USD ${SPENT.toFixed(2)}.`,
  ),
  p("**Built.**"),
  bullet(`a reproducible extraction platform (web interface, gateway, API, workers; about ${Math.round(SRC_LINES / 1000)},000 lines of code and ${TESTS.backend + TESTS.gateway + TESTS.frontend} automated tests, Section 3) that snapshots every run's configuration and code version and stores the outcome of every retrieval configuration and field;`),
  bullet("stage-wise evaluation: evidence recall without LLM calls, four extraction scores including an LLM-graded semantic score, and paired statistics clustered by document;"),
  bullet("new pipeline components behind configuration flags: a local cross-encoder reranker with a shared score cache, and versioned system prompts per pipeline."),
  p("**Key findings so far.**"),
  bullet(
    `**The current system can be beaten cheaply.** A single dense configuration on Qwen3 30B raises the score from ${f3(A[CUR].score)} to ` +
    `${f3(A[RB].score)} and halves invented values (${pc(A[CUR].invented, 0)} to ${pc(A[RB].invented, 0)}) at ${Math.round((100 * A[RB].cost) / A[CUR].cost)}% ` +
    "of the cost; the seven-configuration ensemble with an LLM judge is no better than its best member.",
  ),
  bullet(
    "**Retrieval settings were the first bottleneck.** Similarity thresholds of 0.7 retrieve almost nothing; hybrid search with anchor chunks adds " +
    `${ptsOf(sw("RAG07", 5).recall - sw("RAG02", 5).recall)} points of evidence recall at k = 5.`,
  ),
  bullet(
    `**More context beats better ranking.** Passing 10 or 20 chunks instead of 5 raises the semantic score by ${sgn(D6.semantic[K10].diff)} and ` +
    `${sgn(D6.semantic[K20].diff)} (both significant); a cross-encoder reranker adds ${sgn(D6.semantic[RR].diff)} (not significant). k = 10 gives ` +
    `${Math.round((100 * D6.semantic[K10].diff) / D6.semantic[K20].diff)}% of k = 20's gain for ` +
    `${Math.round((100 * (A[K10].cost - A[K5].cost)) / (A[K20].cost - A[K5].cost))}% of its extra cost.`,
  ),
  bullet(
    `**Invented values rise with context and resist prompting.** They grow from ${pc(A[K5].invented, 0)} to ${pc(A[K20].invented, 0)} of absent ` +
    "fields; an explicit null-policy prompt changed nothing, and most cases trace to field definitions and labelling policy.",
  ),
  bullet(
    `**The semantic score is consistent across graders** (Cohen's kappa ${G.kappa.toFixed(2)} against a second, independent model).`,
  ),
  p(
    "**Next.** Retrieval experiments that need no LLM calls (query expansion × hybrid search, embedding models), then chunking, reader variants, " +
    "verification and decomposition, the long-context comparison, and finally a single run on the test split (Section 10.1, Table 14).",
  ),
];

// ---------- content ----------

const title = [
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 600, after: 200 },
    children: [
      new TextRun({
        text: "What Improves LLM Contract Extraction? A Stage-wise Evaluation of Retrieval and Reading in a RAG Pipeline",
        bold: true, size: 34,
      }),
    ],
  }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: "Ram", size: 24 })] }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 60 },
    children: [new TextRun({ text: "ContractExtraction project", italics: true, size: 22 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 360 },
    children: [new TextRun({ text: "Code fair submission and progress report, 28 October 2026. Development-split results; test-split results pending.", size: 20, color: "6B6B6B" })],
  }),
];

const abstract = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: "Abstract", bold: true, size: 24 })] }),
  p(
    "Large language models (LLMs) combined with retrieval-augmented generation (RAG) are a common way to turn contracts into structured data, " +
    "yet the many design choices in such pipelines are usually tuned by intuition. We study which components actually improve field-level " +
    "extraction quality, using a reproducible extraction platform that records every intermediate outcome and a corpus of 144 public contracts " +
    "across 18 contract types with 2,928 field labels. We evaluate the pipeline stage by stage, separating whether the evidence reaches the model " +
    "(evidence recall) from whether the model reads it correctly, and we report every comparison as a paired difference with a 95% confidence " +
    "interval from a bootstrap over documents. On the development split (36 contracts), replacing the current seven-configuration ensemble with " +
    `an LLM judge on Llama 3.1 8B by a single dense retrieval configuration on Qwen3 30B raises the partial-credit score from ${f3(A[CUR].score)} to ` +
    `${f3(A[RB].score)} and halves the rate of invented values on fields the contract does not contain (${pc(A[CUR].invented, 0)} to ` +
    `${pc(A[RB].invented, 0)}), at ${Math.round((100 * A[RB].cost) / A[CUR].cost)}% of the cost. Retrieval was the first bottleneck: absolute ` +
    "similarity thresholds starve the model of context, hybrid lexical-dense search with anchor chunks adds about 15 points of evidence recall, " +
    "and a cross-encoder reranker helps dense retrieval but adds little to hybrid retrieval and nothing measurable end to end. Passing more chunks " +
    `works better: 10 and 20 chunks instead of 5 raise the semantic score from ${f2(A[K5].semantic)} to ${f2(A[K10].semantic)} and ` +
    `${f2(A[K20].semantic)}, with k = 10 giving most of the gain at well under half the extra cost, at the price of more invented values on absent ` +
    "fields. An explicit null-policy prompt does not reduce them; most trace to field definitions and labelling policy. Because labels paraphrase " +
    `what models quote, we introduce an LLM-graded semantic score and check it against a second grader (Cohen's kappa ${G.kappa.toFixed(2)}).`,
  ),
  p("**Keywords:** contract analysis, information extraction, retrieval-augmented generation, hybrid retrieval, reranking, LLM evaluation"),
];

const introduction = [
  h1("1  Introduction"),
  p(
    "Commercial contracts carry the facts an organisation must act on: who the parties are, when the agreement starts and ends, how it renews, " +
    "what it costs, and how either side can leave it. Reading these facts out of hundreds of agreements by hand is slow and error-prone, so " +
    "automatic extraction into a fixed schema of fields is an attractive target for LLMs. Contracts are long (median 16 pages in our corpus, up to " +
    "428), so the usual architecture splits each document into chunks, retrieves the chunks most relevant to each field, and asks the model to " +
    "extract the value from them (retrieval-augmented generation, RAG).",
  ),
  p(
    "Every stage of such a pipeline has free parameters: how text is chunked, which embedding model and similarity threshold select chunks, " +
    "whether lexical search is fused with dense search, how many chunks reach the model, whether a reranker reorders them, which model reads " +
    "them, and whether a second model judges the answer. Practitioner systems, including the one studied here, often combine several retrieval " +
    "configurations and an LLM judge in the hope that the ensemble is more robust than any single setting. Whether these choices help is rarely " +
    "measured, and when it is, retrieval and reading errors are usually mixed in a single end-to-end accuracy figure.",
  ),
  p(
    "This report asks a practical question: **which components of a contract-extraction pipeline improve extraction quality, and by how much?** " +
    "We answer it with controlled experiments that change one component at a time, evaluate retrieval and extraction separately, and report " +
    "paired differences with uncertainty. The work is ongoing; this progress report covers the baseline, retrieval, reranking, context-size and first " +
    "prompt experiments on the development split, and the remaining experiments are planned in Section 10.1.",
  ),
  p("The research questions addressed so far are:"),
  numbered("**RQ1 (baseline).** How well does the current system perform, how does a single-configuration research baseline compare, and what is the smallest effect the data can resolve?"),
  numbered("**RQ2 (retrieval settings).** Which retrieval settings decide whether the evidence for a field reaches the model?"),
  numbered("**RQ3 (reranking).** Does a cross-encoder reranker improve evidence recall and, through it, the extracted values?"),
  numbered("**RQ4 (context size).** How many retrieved chunks should the reader receive?"),
  numbered("**RQ5 (ensembling and judging).** Does a multi-configuration ensemble with LLM-judge selection beat the best single configuration?"),
  numbered("**RQ6 (measurement).** How should extracted values be scored when reference labels paraphrase the contract while models quote it?"),
  numbered("**RQ7 (invented values).** Where do values for absent fields come from, and does an explicit instruction prevent them?"),
  p("The contributions of this work are:"),
  bullet("an open, reproducible extraction platform in which every run stores the fully resolved configuration, the code version, and the outcome of every retrieval configuration and field, not only the final answer;"),
  bullet("a stage-wise evaluation protocol for contract extraction: evidence recall computed from labelled evidence quotes with no LLM calls, extraction metrics at several levels of strictness, and paired statistics clustered by document;"),
  bullet("empirical findings on the development split showing that retrieval, not reading, is the main bottleneck, that absolute similarity thresholds and judge-selected ensembles are harmful or useless, and that more context helps the reader more than better ranking does;"),
  bullet("an LLM-graded semantic score for structured and free-text fields, with an agreement analysis against a second, independent grader."),
];

const related = [
  h1("2  Related Work"),
  h2("2.1  Contract understanding"),
  p(
    "Legal NLP has produced several contract benchmarks. CUAD [6] annotates 41 clause categories in 510 commercial contracts as an extractive " +
    "question-answering task, ContractNLI [8] frames contract review as document-level natural language inference over non-disclosure agreements, " +
    "and LEDGAR [14] classifies provisions from SEC filings. These datasets label clause spans; our task differs in asking for normalised, typed " +
    "values (ISO dates and durations, money with currency, party references, structured objects), which makes scoring harder and is one reason we " +
    "introduce a semantic score.",
  ),
  h2("2.2  Retrieval-augmented generation"),
  p(
    "RAG [9] conditions a generator on passages retrieved from an external corpus. Dense retrievers embed queries and passages in one vector space; " +
    "lexical retrievers such as BM25 [12] match exact terms, which matters for legal text full of defined terms and numbers. Hybrid retrieval fuses " +
    "both rankings, often with reciprocal rank fusion (RRF) [3]. Two-stage pipelines then reorder a larger candidate set with a cross-encoder " +
    "reranker [11]; the BGE family [2] provides multilingual embedding and reranking models that run locally. Models do not use long contexts " +
    "uniformly: information in the middle of a long prompt is used less reliably than information at its ends [10], which motivates the question of " +
    "how many chunks to pass to the reader.",
  ),
  h2("2.3  Evaluating RAG systems and LLM judges"),
  p(
    "RAGAS [4] and ARES [13] argue for evaluating retrieval and generation separately, using context relevance, faithfulness and answer quality. " +
    "LLM-as-a-judge [16] uses a strong model to grade outputs and reports high agreement with humans on open-ended answers, but also position, " +
    "verbosity and self-preference biases. We use an LLM grader only to score semantic equivalence against a reference label, and we measure its " +
    "agreement with a second grader. For statistics we follow common NLP practice [5]: paired tests on the same items, bootstrap confidence " +
    "intervals [1], McNemar's test [15] for paired binary outcomes, and Holm's correction [7] for multiple comparisons.",
  ),
];

const system = [
  h1("3  System"),
  p(
    "ContractExtraction is a research platform that takes a contract and returns a fixed set of fields, each with its value, the evidence chunks it " +
    "was based on, and optionally a verdict from an LLM judge. A browser front end and a REST API sit in front of background workers; the workers " +
    "claim queued runs from PostgreSQL, store vectors in Qdrant, and call either a local Ollama server or a hosted provider (OpenRouter). Every " +
    "setting that shapes a run (models, prompts, chunking, retrieval configurations and fields) is configuration stored in the database, and each " +
    "run stores the fully resolved configuration as a snapshot together with the git commit of the code that ran it. Table 1 summarises the stages.",
  ),
  tableTitle("**Table 1.** Pipeline stages."),
  table(
    ["Stage", "Input → output", "Main settings"],
    [
      ["Decompose", "source file → page Markdown", "converter per format (HTML, PDF via pymupdf / OCR / hybrid, DOCX, text); repeated header and footer removal"],
      ["Index", "pages → chunks → vectors", "2,000-character chunks with 300 overlap, within a page; section heading prepended; nomic-embed-text embeddings and a BM25 keyword vector per chunk"],
      ["Retrieve", "field → ranked chunks", "expansion queries per field, hits per query, top-k, score threshold, optional BM25 fused by RRF, optional anchor chunks, optional cross-encoder reranker"],
      ["Extract", "field prompt + chunks → value", "one call per field (or per field group), JSON output in the field's typed format"],
      ["Judge", "value + evidence → verdict", "separate LLM, PASS / FAIL; selects the best value across retrieval configurations"],
    ],
    [14, 22, 64],
  ),
  p(""),
  p(
    "**Retrieval.** For each field the retriever issues the field label and its expansion queries, keeps a fixed number of hits per query, merges and " +
    "deduplicates them, and passes the top *k* to the reader. A score threshold optionally drops low-similarity chunks. With keyword search on, the " +
    "dense and BM25 rankings are fused by RRF. *Anchor chunks* add the first or last two chunks of the document for fields that are almost always on " +
    "the cover page or in the preamble (title, parties, effective date) or on the signature page (signatories, execution date). The optional " +
    "reranker scores a larger candidate pool (20 or 40 fused hits) with a cross-encoder, BAAI bge-reranker-v2-m3 quantised to int8 and run on CPU, and keeps the top *k*.",
  ),
  p(
    "**The current system.** The default pipeline runs seven retrieval configurations, RAG01–RAG07 (Appendix A), for every field, extracts a value " +
    "under each with Llama 3.1 8B, and lets an LLM judge choose the best value. Its configurations were designed by hand and differ in several " +
    "settings at once, so they serve here only as the baseline \"current system\". For the research grid we defined a clean baseline, **R-base** " +
    "(dense retrieval, top 5, no threshold, query expansion, 5 hits per query), from which each arm changes a single setting.",
  ),
  h2("3.1  Architecture and deployment"),
  p(
    "Figure 1 shows how the parts run. The browser talks only to the frontend, which reaches the backend through a gateway that adds request " +
    "identifiers, timeouts, an upload size limit and an aggregated health check. The backend API never does pipeline work inside a request: it " +
    "writes a queued run to PostgreSQL and returns. Workers claim queued runs with SELECT … FOR UPDATE SKIP LOCKED, send a heartbeat every 15 " +
    "seconds, and write results back, so the API and the workers never call each other and any number of workers can run in parallel. Only the " +
    "workers talk to Qdrant, the LLM providers and the reranker, which keeps the API fast. All pipeline configuration lives in the database, " +
    "and each run executes from a frozen snapshot of it, so editing a configuration never changes a queued or finished run.",
  ),
  figure("fig_architecture.png", 620, 422),
  caption(
    "**Figure 1.** Deployment architecture. Blue: application processes; orange: data stores; green: model services. The API and the workers " +
    "communicate only through the run queue in PostgreSQL.",
  ),
  h2("3.2  Technology stack"),
  tableTitle("**Table 2.** Technology stack."),
  table(
    ["Layer", "Technologies"],
    [
      ["Frontend", "React 19, TypeScript 5.9, Vite 8, Tailwind CSS 4, Radix UI, TanStack Query, React Router, openapi-fetch with types generated from the API's OpenAPI schema"],
      ["Gateway", "Python 3.13, Starlette, httpx (streaming reverse proxy), Uvicorn"],
      ["Backend API and workers", "Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2 with psycopg 3, Uvicorn; one package with API, worker and CLI entry points"],
      ["Document processing", "PyMuPDF and pymupdf4llm (PDF to Markdown, OCR and hybrid modes), BeautifulSoup and markdownify (HTML), mammoth (DOCX), Pillow (images)"],
      ["Retrieval", "Qdrant 1.12 (dense and BM25 sparse vectors per chunk, reciprocal rank fusion), Snowball stemmer, fastembed (ONNX cross-encoder reranker on CPU, SQLite score cache)"],
      ["Models", "Ollama (local Llama 3.1 8B, nomic-embed-text), OpenRouter (hosted Qwen3 30B, Llama 3.1 8B, Gemini, GPT-6 Luna and others) behind one OpenAI-compatible adapter"],
      ["Data", "PostgreSQL 16 (31 tables and 2 views: configuration, documents, runs and queue, results, ground truth), local file storage"],
      ["Tooling", "uv, npm, Docker Compose, pytest, Vitest with Testing Library and MSW, ESLint, TypeScript checks, one dev script (scripts/dev.sh) for start, status, smoke and test"],
      ["Analysis and report", "experiment CLI (create, run, export, compare, semantic), matplotlib, docx"],
    ],
    [22, 78], { left: true },
  ),
  p(""),
  h2("3.3  Code base and tests"),
  p(
    `The code base was built over ${N.code.commits} commits between ${N.code.first_commit} and ${N.code.last_commit}. Table 3 gives its size in ` +
    "non-blank lines, without generated files. Every test suite runs offline: providers sit behind interfaces, so the pipeline is tested with " +
    "fake LLMs, embedders and vector stores and needs no Docker or network. A separate smoke suite (scripts/dev.sh smoke) exercises the running stack end to end.",
  ),
  tableTitle("**Table 3.** Size of the code base and its tests (non-blank lines; test counts as of 28 October 2026)."),
  table(
    ["Component", "Source files", "Source lines", "Test files", "Test lines", "Tests"],
    [
      ["Backend (Python)", String(C.backend.files), int(C.backend.lines), String(C.backend_tests.files), int(C.backend_tests.lines), `${TESTS.backend} (+ ${TESTS.live} live and smoke)`],
      ["Gateway (Python)", String(C.gateway.files), int(C.gateway.lines), String(C.gateway_tests.files), int(C.gateway_tests.lines), String(TESTS.gateway)],
      ["Frontend (TypeScript, React)", String(C.frontend.files), int(C.frontend.lines), String(C.frontend_tests.files), int(C.frontend_tests.lines), String(TESTS.frontend)],
      ["Schema and seed data (SQL)", String(C.sql.files), int(C.sql.lines), "—", "—", "—"],
      ["Scripts (shell, Python)", String(C.scripts.files), int(C.scripts.lines), "—", "—", "—"],
      ["**Total**", `**${SRC_FILES}**`, `**${int(SRC_LINES)}**`, `**${TEST_FILES}**`, `**${int(TEST_LINES)}**`, `**${TESTS.backend + TESTS.gateway + TESTS.frontend}**`],
    ],
    [28, 13, 14, 12, 13, 20],
  ),
  p(""),
  p(
    `Test code is ${Math.round((100 * TEST_LINES) / SRC_LINES)}% of the source by lines. The backend tests cover configuration resolution and ` +
    "snapshots, the run queue and worker recovery, every document converter, chunking offsets, retrieval (fusion, anchors, reranking), answer " +
    "parsing, evaluation and evidence matching, the experiment exports and the statistics; the frontend tests render the pages against a mocked API.",
  ),
  h2("3.4  User interface"),
  p(
    "The web interface covers the whole workflow: upload a contract in any supported format, follow a run's progress, inspect each extracted " +
    "value next to its label and the retrieval configuration that produced it, read the extracted pages, and edit every configuration that " +
    "shapes a run (Figures 2–4).",
  ),
  figure("ui_documents.png", 600, 375),
  caption("**Figure 2.** Document list with upload. Each document shows its format, page count and latest run."),
  figure("ui_run_results.png", 600, 375),
  caption(
    "**Figure 3.** Results of a run (k = 20 arm): the extracted value, the judge's verdict, the expected label, whether they match and which " +
    "retrieval configuration produced the value. The contract is a public SEC filing.",
  ),
  figure("ui_configuration.png", 600, 375),
  caption("**Figure 4.** Configuration: pipelines, retrieval configurations, contract types, fields, models, prompts and indexing are all editable data."),
];

const data = [
  h1("4  Data"),
  h2("4.1  Corpus"),
  p(
    "The corpus contains 144 publicly available contracts, most of them exhibits filed with the US SEC (EDGAR), covering 18 contract types " +
    "(for example non-disclosure agreements, master services agreements, SaaS agreements, leases, loans, employment, licensing and share or asset " +
    "purchase agreements) plus a fallback type. Documents come in several source formats, including HTML, text-layer PDF, scanned PDF, plain text and " +
    "Word (42 of the 144 are PDFs). The corpus totals about 5,220 pages, with a median of 16 pages per contract and a maximum of 428.",
  ),
  h2("4.2  Field catalogue"),
  p(
    "Each contract type has its own field list drawn from a shared catalogue in which a field key means the same thing in every type. Fields are " +
    "typed (string, free text, list, boolean, number, date, ISO 8601 duration, money, relative date, jurisdiction, party references, structured " +
    "objects and lists of objects) and prioritised: P1 for direct financial, time or exit exposure, P2 for material risk and P3 for informational " +
    "fields. Roughly two thirds of the labelled values are structured (objects or lists), which matters for scoring (Section 5.2).",
  ),
  h2("4.3  Labels"),
  p(
    "The 2,928 field labels were drafted by an LLM (Claude) from the full contract text and are used as they are; there is no hand-verified gold " +
    "set. 1,225 labels are empty, meaning the field is not present in the contract, and 1,705 carry a verbatim evidence quote. Each label has a " +
    "confidence: 2,068 high, 786 medium and 74 low. Because the labels are drafts, we report headline results on all labels and check that each " +
    "claimed effect also holds on high-confidence labels (Section 8 discusses the remaining risk).",
  ),
  h2("4.4  Development and test split"),
  p(
    "Contracts were split once, stratified by contract type and source format (seed 2026, development share 0.28), into a **development set of 36 " +
    "contracts** and a **test set of 108 contracts**. All tuning and every result in this draft use the development set only; the test set will be " +
    "run once, at the end, with the final configurations. On the development set each run evaluates 452 labelled value cells and 280 absent-field " +
    "cells per repeat.",
  ),
];

const method = [
  h1("5  Methodology"),
  h2("5.1  Experimental design"),
  p(
    "Each experiment compares *arms*, pipelines that differ from a reference in one setting. All arms of an experiment run on the same documents and " +
    "fields, so every comparison is paired at the level of a (document, field) cell. Each arm is repeated three times at a low non-zero temperature, " +
    "which lets us separate run-to-run noise from document-to-document variation. Retrieval-only experiments run the retriever for every labelled " +
    "field and score the retrieved chunks without calling an LLM, which makes retrieval sweeps nearly free.",
  ),
  h2("5.2  Metrics"),
  p("**Retrieval.** For labels with an evidence quote we compute:"),
  bullet("**Evidence recall:** the share of labelled fields for which at least one fragment of the quote is found in a retrieved chunk. Text is normalised to word tokens, and a fragment counts as found when at least 80% of its tokens appear in order in the chunk (fragments under three tokens are ignored)."),
  bullet("**Recall@k** and **mean reciprocal rank (MRR)** of the first chunk holding the evidence."),
  bullet("**Not indexed:** the share of quotes found in no chunk of the document at all, which isolates losses in decomposition and chunking from losses in retrieval."),
  p("**Extraction.** For labelled values we report four scores of increasing leniency, and two rates on absent fields:"),
  bullet("**Exact:** the value equals the label after type normalisation."),
  bullet("**Score (partial credit):** structure-aware; object keys are averaged and list items greedily matched, with exact comparison at the leaves."),
  bullet("**Lenient:** the same structure with lenient leaves (numbers by value, text by token F1)."),
  bullet("**Semantic:** leaves settled deterministically where possible (empty answers wrong, booleans and numbers compared, lenient matches of 1 correct); the rest graded *correct* (1), *partial* (0.5) or *wrong* (0) by an LLM grader (GPT-6 Luna) given the field definition, the label and the answer."),
  bullet("**Missed:** an empty answer for a field that has a value; **absent correct** and **invented:** on fields the contract does not contain, the share answered empty versus with an invented value."),
  p("We also record LLM calls, tokens, cost (OpenRouter list prices) and wall-clock seconds per run, where one run processes one contract."),
  h2("5.3  Statistical analysis"),
  p(
    "Cells from one contract are correlated, so the unit of resampling is the document. For each paired comparison we report the mean difference " +
    "with a 95% confidence interval from a cluster bootstrap over documents, a permutation p-value, and McNemar's exact test for exact match, with " +
    "Holm's correction within each research question. We claim an effect only when (i) its confidence interval excludes zero, (ii) it exceeds the " +
    "run-to-run noise floor measured in E1, and (iii) it holds on high-confidence labels.",
  ),
  h2("5.4  Models"),
  tableTitle("**Table 4.** Models used so far."),
  table(
    ["Role", "Model", "Access", "Price (USD per M tokens, in / out)"],
    [
      ["Reader, current system", "Llama 3.1 8B Instruct", "OpenRouter", "0.05 / 0.08"],
      ["Reader, research workhorse", "Qwen3 30B-A3B Instruct 2507", "OpenRouter", "0.09 / 0.30"],
      ["Judge, current system", "Llama 3.1 8B Instruct", "OpenRouter", "0.05 / 0.08"],
      ["Semantic grader", "GPT-6 Luna (low reasoning effort)", "OpenRouter", "0.10 / 0.50"],
      ["Grader cross-check", "Gemini 4 Argon", "OpenRouter", "2.00 / 10.00"],
      ["Embeddings", "nomic-embed-text", "Ollama (local)", "free"],
      ["Reranker", "bge-reranker-v2-m3 (int8)", "fastembed (local CPU)", "free"],
    ],
    [26, 32, 18, 24],
  ),
  p(""),
];

const results = [
  h1("6  Results"),
  p(
    "All results in this section are on the development split (36 contracts, three repeats per arm). Every number in the tables and figures is " +
    "computed from the experiment exports by make_figures.py; intervals are 95% cluster bootstrap intervals over documents, and an asterisk marks " +
    "a difference whose Holm-adjusted permutation p-value is below 0.05.",
  ),

  h2("6.1  E1: Baseline and noise floor (RQ1)"),
  p(
    "E1 compares the current system (seven retrieval configurations, Llama 3.1 8B reader and judge) with the research baseline (R-base, Qwen3 30B, " +
    "no judge). Table 5 and Figure 5 give the results."
  ),
  tableTitle("**Table 5.** E1 on the development split (452 value cells and 280 absent cells per repeat, 3 repeats)."),
  table(
    ["Metric", "Current system (Llama 3.1 8B, RAG01–07 + judge)", "R-base (Qwen3 30B)"],
    [
      ["Exact", f3(A[CUR].exact), f3(A[RB].exact)],
      ["Score (partial credit)", f3(A[CUR].score), `**${f3(A[RB].score)}**`],
      ["Lenient", f3(A[CUR].lenient), f3(A[RB].lenient)],
      ["Semantic", f3(A[CUR].semantic), `**${f3(A[RB].semantic)}**`],
      ["Missed", pc(A[CUR].missed), pc(A[RB].missed)],
      ["Absent correct", pc(A[CUR].absent_correct), `**${pc(A[RB].absent_correct)}**`],
      ["Invented on absent", pc(A[CUR].invented), `**${pc(A[RB].invented)}**`],
      ["Evidence recall", pc(A[CUR].recall), pc(A[RB].recall)],
      ["Score with evidence retrieved / without", `${f3(A[CUR].score_with_evidence)} / ${f3(A[CUR].score_without_evidence)}`,
        `${f3(A[RB].score_with_evidence)} / ${f3(A[RB].score_without_evidence)}`],
      ["LLM calls per contract", int(A[CUR].llm_calls), int(A[RB].llm_calls)],
      ["Tokens per contract", int(A[CUR].tokens), int(A[RB].tokens)],
      ["Cost per contract (USD)", usd(A[CUR].cost), usd(A[RB].cost)],
      ["Seconds per contract", int(A[CUR].seconds), int(A[RB].seconds)],
    ],
    [40, 34, 26],
  ),
  p(""),
  figure("fig_e1_baseline.png", 540, 300),
  caption(
    "**Figure 5.** E1: current system against the research baseline, with 95% cluster bootstrap intervals. The baseline is better on both " +
    "quality scores and invents values on absent fields half as often.",
  ),
  p(
    `The research baseline is better on every quality metric: the score rises by ${ci(N.e1_diff.score)} and the semantic score by ` +
    `${ci(N.e1_diff.semantic)}, and both differences hold on high-confidence labels (score ${ci(N.e1_diff.score_high)}). The largest change is on ` +
    `absent fields, where invented values fall from ${pc(A[CUR].invented, 0)} to ${pc(A[RB].invented, 0)} (${pts(N.e1_diff.invented)} points). The ` +
    "smaller model also copies prompt placeholders into its answers (\"John Doe\", \"ABC Corp\") in 1.8% of values, against none for Qwen3. The " +
    "baseline is also cheaper and faster, because the current system makes seven extraction calls and a judge call per field.",
  ),
  p(
    "**Retrieval gates reading.** Within each arm, a value whose evidence was retrieved scores about four times higher than one whose evidence was " +
    `not (${f3(A[RB].score_with_evidence)} vs ${f3(A[RB].score_without_evidence)} for Qwen3). Since only ${pc(A[RB].recall, 0)} of fields receive ` +
    "their evidence, improving retrieval is the first lever.",
  ),
  p(
    "**Noise floor.** The standard deviation of the set mean across the three repeats is about 0.004 (0.005 for Llama, 0.003 for Qwen3), an order " +
    "of magnitude below the document-level confidence interval of about ±0.035. With 36 development contracts, the number of documents, not " +
    "sampling noise, limits the effects we can claim; differences smaller than roughly 0.03 in score are not resolvable on this split.",
  ),
  p(
    "**Reading given evidence.** Restricting to cells whose evidence was retrieved, Qwen3 scores 0.79 on text, 0.83 on dates and 1.0 on booleans, " +
    "but only 0.24 on structured (JSON) values, which make up two thirds of the labels. Inspection showed that this is mostly a scoring artefact: " +
    "labels paraphrase (for example, a list of termination triggers) while the model quotes the contract. This motivated the semantic score (Section 6.9).",
  ),

  h2("6.2  E11: Ensemble with judge selection (RQ5)"),
  p(
    "Because the current system stores the outcome of every retrieval configuration, the E1 runs also answer whether the ensemble helps. Selecting " +
    "the judge's preferred value across seven configurations gives a score of 0.165, while RAG07 alone scores 0.175 (difference not significant, " +
    "p = 0.28). The ensemble is therefore no better than its best member at seven times the extraction cost. The judge is the reason: of the values " +
    "it passed, only 16% were correct, and it passed only 34% of the values that were correct. RAG04–RAG06 contribute almost nothing, for the " +
    "reason shown in E2.",
  ),

  h2("6.3  E2: Retrieval settings (RQ2)"),
  p(
    "E2 runs the retriever alone for every labelled field with an evidence quote (452 fields, no LLM calls). Table 6 shows the seeded configurations."
  ),
  tableTitle("**Table 6.** Evidence recall of the seeded retrieval configurations (development split, 452 fields)."),
  table(
    ["Config", "Settings", "Recall", "Recall@1", "MRR", "Mean chunks"],
    [
      ["RAG01", "dense, top 10, threshold 0.5, expansion", ...retr(R.seeded.RAG01)],
      ["RAG02", "dense, top 5, threshold 0.5, expansion", ...retr(R.seeded.RAG02)],
      ["RAG03", "dense, top 3, threshold 0.5, expansion", ...retr(R.seeded.RAG03)],
      ["RAG04–06", "dense, top 10 / 5 / 3, threshold 0.7, no expansion", ...retr(R.seeded.RAG04, 2)],
      ["RAG07", "RAG02 + BM25 (RRF) + 2 anchor chunks", ...retr(R.seeded.RAG07).map((x) => `**${x}**`)],
    ],
    [11, 43, 11, 11, 10, 14],
  ),
  p(""),
  p("Three findings shape the rest of the programme:"),
  bullet(
    "**Absolute thresholds starve the reader.** nomic-embed-text cosine similarities for relevant chunks mostly lie between 0.4 and 0.7, so a 0.7 " +
    `threshold returns on average ${R.seeded.RAG04.mean_hits.toFixed(2)} chunks per field and recall collapses to ${pc(R.seeded.RAG04.recall)}. ` +
    "The extraction model then answers from no evidence at all. The research baseline R-base therefore uses a fixed *k* with no threshold.",
  ),
  bullet(
    "**top-k is capped by hits per query.** With three hits per query, raising top-k from 5 to 20 changes nothing, because the merged pool never " +
    "holds more than about five unique chunks. Recall only grows with *k* when the per-query pool is raised as well (20 hits per query).",
  ),
  bullet(
    `**Hybrid search with anchors beats dense search at every k,** by ${ptsOf(sw("RAG07", 5).recall - sw("RAG02", 5).recall)} points at k = 5 ` +
    `(${pc(sw("RAG07", 5).recall)} vs ${pc(sw("RAG02", 5).recall)}) and ${ptsOf(sw("RAG07", 20).recall - sw("RAG02", 20).recall)} points at k = 20 ` +
    `(${pc(sw("RAG07", 20).recall)} vs ${pc(sw("RAG02", 20).recall)}), with a much better first hit (recall@1 ${pc(sw("RAG07", 5).recall_at_1, 0)} ` +
    `vs ${pc(sw("RAG02", 5).recall_at_1, 0)}). Exact terms, defined names and dates favour lexical matching, and cover- and signature-page fields favour anchors.`,
  ),
  figure("fig_recall_vs_k.png", 520, 300),
  caption(
    "**Figure 6.** Evidence recall against the number of chunks passed to the reader, for dense and hybrid retrieval (20 hits per query, no " +
    "threshold, development split). Recall keeps rising to k = 20, so ranking, not the candidate pool, limits recall at k = 5.",
  ),
  p(
    `Only ${pc(R.seeded.RAG07.not_indexed)} of evidence quotes are missing from every chunk of their document, so decomposition and chunking lose little; ` +
    `the evidence is indexed but ranked too low. With RAG07, recall at k = 5 plateaus at about 70% while k = 20 reaches ${pc(sw("RAG07", 20).recall, 0)}. ` +
    "This pointed to two remedies, tested in E6: rank better (a reranker) or pass more chunks (larger k). Note that k = 20 (about 9,000 prompt " +
    "tokens) exceeds the 8,192-token context window configured for local Llama 3.1 8B, so the second remedy is open only to readers with longer contexts.",
  ),

  h2("6.4  E6: Cross-encoder reranking, retrieval only (RQ3)"),
  tableTitle("**Table 7.** Evidence recall at k = 5 with and without the reranker (20 hits per query, development split, 452 fields)."),
  table(
    ["Retrieval", "Candidates", "Recall", "Recall@1", "MRR", "Δ recall vs no reranker (points, 95% CI)"],
    [
      ["R-base (dense)", "—", ...retr(rk("R-base", "none", 40)).slice(0, 3), ""],
      ["R-base + reranker", "20", ...retr(rk("R-base", RRM, 20)).slice(0, 3), rgain("R-base", 20)],
      ["R-base + reranker", "40", ...retr(rk("R-base", RRM, 40)).slice(0, 3), `**${rgain("R-base", 40)}**`],
      ["RAG07 (hybrid + anchors)", "—", ...retr(rk("RAG07", "none", 40)).slice(0, 3), ""],
      ["RAG07 + reranker", "20", ...retr(rk("RAG07", RRM, 20)).slice(0, 3), rgain("RAG07", 20)],
      ["RAG07 + reranker", "40", ...retr(rk("RAG07", RRM, 40)).slice(0, 3), rgain("RAG07", 40)],
    ],
    [26, 12, 11, 11, 10, 30],
  ),
  p(""),
  p(
    `The reranker lifts dense retrieval by ${ptsOf(gain("R-base", 40).diff)} points, a significant gain that brings it to the level of hybrid retrieval ` +
    `without a reranker. On hybrid retrieval the gain is ${ptsOf(gain("RAG07", 40).diff)} points and not significant (95% CI ` +
    `${ptsOf(gain("RAG07", 40).lo)} to +${ptsOf(gain("RAG07", 40).hi)} points). The reranker therefore *substitutes* for BM25 and anchors rather ` +
    "than adding to them, and at k = 5 it still falls far short of the recall that k = 20 reaches without any reranking. On CPU the int8 model costs " +
    "about 0.1 s per candidate; running it in eight parallel workers exhausted the memory of a 16 GB laptop, which we fixed with an on-disk score " +
    "cache, lazy model loading and a thread cap.",
  ),

  h2("6.5  E6: Context size versus reranking, end to end (RQ3, RQ4)"),
  p(
    "E6 then measures whether the recall gains reach the extracted values. All four arms use hybrid retrieval with anchors and 20 hits per query " +
    "(R07) and the Qwen3 30B reader; they differ only in how many chunks reach the reader (5, 10 or 20) and whether the reranker selects the five " +
    "(Table 8, Figure 7). Table 9 and Figure 8 give the paired differences against k = 5."
  ),
  tableTitle("**Table 8.** End-to-end results by context size and reranking (Qwen3 30B, development split, 3 repeats). Best value per row in bold."),
  table(
    ["Metric", "R07, k = 5", "R07, k = 10", "R07, k = 20", "R07, k = 5 + reranker"],
    [
      row6("Evidence recall", "recall", pc, true),
      row6("Exact", "exact", f3, true),
      row6("Score (partial credit)", "score", f3, true),
      row6("Lenient", "lenient", f3, true),
      row6("Semantic", "semantic", f3, true),
      row6("Missed", "missed", pc, false),
      row6("Absent correct", "absent_correct", pc, true),
      row6("Invented on absent", "invented", pc, false),
      row6("Tokens per contract", "tokens", int, false),
      row6("Cost per contract (USD)", "cost", usd, false),
      ["Failed runs (of 108 + retries)", ...E6ARMS.map((a) => String(A[a].runs_failed))],
    ],
    [30, 17, 17, 17, 19],
  ),
  p(""),
  figure("fig_context_size.png", 620, 266),
  caption(
    "**Figure 7.** Quality, evidence recall and invented values against the number of chunks passed to the reader (Qwen3 30B, development split, " +
    "95% cluster bootstrap intervals). Open diamonds: five chunks chosen by the reranker.",
  ),
  tableTitle("**Table 9.** Paired differences against R07, k = 5, in points on a 0–100 scale (95% cluster bootstrap CI; * Holm-adjusted p < 0.05)."),
  table(
    ["Arm", "Labels", "Semantic", "Score", "Exact", "Invented on absent"],
    [K10, K20, RR].flatMap((a) => [
      [LBL[a], "all", star(D6.semantic[a], true), star(D6.score[a], true), star(D6.exact[a], true), star(D6.invented[a], true)],
      ["", "high conf.", star(D6.semantic_high[a], true), star(D6.score_high[a], true), star(D6.exact_high[a], true), star(D6.invented_high[a], true)],
    ]),
    [18, 12, 17, 17, 17, 19],
  ),
  p(""),
  figure("fig_forest.png", 620, 250),
  caption(
    "**Figure 8.** Paired differences against k = 5 for every arm tested on the same cells, including the null-policy prompt of E8a (Section 6.8). " +
    "Filled markers: all labels; open markers: high-confidence labels only.",
  ),
  p(
    `**More context wins, with diminishing returns.** Against k = 5, passing 10 chunks raises the semantic score by ${ci(D6.semantic[K10])} and ` +
    `passing 20 by ${ci(D6.semantic[K20])}; k = 20 is still better than k = 10 (${ci(N.e6_diff.k10_vs_k20_semantic, -1)}). Missed values fall ` +
    `from ${pc(A[K5].missed)} to ${pc(A[K20].missed)}. All of these differences are significant and hold on high-confidence labels. The reader is ` +
    "not overwhelmed by four times as many chunks; the recall gain carries through to the answers.",
  ),
  p(
    `**At a price in hallucination.** With more context the model also fills more fields that the contract does not contain: invented values on ` +
    `absent fields rise from ${pc(A[K5].invented)} to ${pc(A[K10].invented)} at k = 10 (${pts(D6.invented[K10])} points, not significant after ` +
    `Holm) and ${pc(A[K20].invented)} at k = 20 (${pts(D6.invented[K20])} points, significant).`,
  ),
  p(
    `**Cost-effectiveness.** Tokens and cost rise with k, to ${usd(A[K10].cost)} and ${usd(A[K20].cost)} USD per contract. k = 10 obtains ` +
    `${Math.round((100 * D6.semantic[K10].diff) / D6.semantic[K20].diff)}% of k = 20's semantic gain for ` +
    `${Math.round((100 * (A[K10].cost - A[K5].cost)) / (A[K20].cost - A[K5].cost))}% of its extra cost, so it is the better default when cost ` +
    "matters and k = 20 when accuracy does (Figure 9). Both lie on the cost-quality Pareto front, together with the cheaper R-base and k = 5 arms.",
  ),
  figure("fig_cost_quality.png", 540, 320),
  caption(
    "**Figure 9.** Cost per contract against semantic score for every arm run so far (95% intervals). Arms from different experiments ran on " +
    "different code versions, so the comparison across experiments is indicative; the dashed line joins the arms no cheaper arm beats.",
  ),
  p(
    `**Reranking does not reach the answers.** The reranker arm moves every metric in the right direction (semantic ${sgn(D6.semantic[RR].diff)}, ` +
    `score ${sgn(D6.score[RR].diff)}, invented ${pts(D6.invented[RR])} points), but none of these differences is significant. For this reader, ` +
    "recall gained by passing more chunks is worth far more than recall gained by ranking them better.",
  ),
  p(
    `As an indication only, the k = 5 hybrid arm (score ${f3(A[K5].score)}) is well above the dense R-base arm of E1 (${f3(A[RB].score)}) with the ` +
    "same reader; the two runs come from different code versions and are not yet compared formally. The clean dense-versus-hybrid comparison belongs to E5.",
  ),

  h2("6.6  Retrieval failures versus reading failures"),
  p(
    "Figure 10 splits every labelled value into four outcomes by its semantic grade: correct, partially correct, wrong although the evidence was " +
    "retrieved (a reading failure), and wrong because the evidence was not retrieved (a retrieval failure). This attributes the remaining error to a " +
    "stage of the pipeline."
  ),
  figure("fig_error_attribution.png", 600, 300),
  caption(
    "**Figure 10.** Outcome of every labelled value (all repeats) by arm. Grey: wrong and evidence not retrieved; orange: wrong although the " +
    "evidence was retrieved.",
  ),
  p(
    `Retrieval failures fall from ${pc(AT[CUR].wrong_not_retrieved, 0)} of values in the current system and ${pc(AT[RB].wrong_not_retrieved, 0)} ` +
    `under R-base to ${pc(AT[K5].wrong_not_retrieved, 0)} at k = 5, ${pc(AT[K10].wrong_not_retrieved, 0)} at k = 10 and ` +
    `${pc(AT[K20].wrong_not_retrieved, 0)} at k = 20. Reading failures stay between ${pc(Math.min(...[RB, K5, K10, K20].map((a) => AT[a].wrong_retrieved)), 0)} ` +
    `and ${pc(Math.max(...[RB, K5, K10, K20].map((a) => AT[a].wrong_retrieved)), 0)} for Qwen3 (${pc(AT[CUR].wrong_retrieved, 0)} for Llama) and ` +
    `grow slightly with k. At k = 20 the reader, not the retriever, accounts for most wrong values, and the largest block is now partially ` +
    `correct values (${pc(AT[K20].partial, 0)}), mostly structured fields with some sub-fields missing. Further gains must therefore come from the ` +
    "reader (E8) and from the scoring of structured values, not from more retrieval.",
  ),

  h2("6.7  Where invented values come from"),
  p(
    `Invented values on absent fields are concentrated in a few fields: the eight fields in Table 10 account for ` +
    `${pc(INV.fields.reduce((s, f) => s + f.share_of_invented[K5], 0), 0)} of all invented values at k = 5, and the first four for ` +
    `${pc(INV.fields.slice(0, 4).reduce((s, f) => s + f.share_of_invented[K5], 0), 0)}. Inspecting the answers shows that most are not ` +
    "hallucinations in the usual sense (Table 10, Figure 11):",
  ),
  tableTitle("**Table 10.** Invented-value rate on absent labels for the fields with the most invented values (development split, all repeats)."),
  table(
    ["Field", "Absent cells per repeat", "k = 5", "k = 20", "k = 5 + null policy", "What the model returns"],
    INV.fields.map((f) => [f.field, String(f.cells), pc(f.rate[K5], 0), pc(f.rate[K20], 0), pc(f.rate[NULLP], 0), CAUSE[f.field] || "not yet inspected"]),
    [20, 11, 8, 8, 11, 42], { left: true },
  ),
  p(""),
  figure("fig_invented_by_field.png", 600, 320),
  caption("**Figure 11.** Invented-value rate on absent labels by field, for k = 5, k = 20 and the null-policy prompt (absent cells per repeat in brackets)."),
  bullet(
    "**Label policy, not invention.** For expiration_date the model returns an expiry relative to an event (for example 90 days after termination) " +
    "where the label is empty; the field's own format help asks for exactly this. For document_status it answers \"executed\", and every one of " +
    "those labels has low or medium confidence. These cells measure a disagreement about what the field should hold.",
  ),
  bullet(
    `**Copying the field definition.** uncapped_liabilities is defined as \"Liabilities carved out of the cap (fraud, IP, data breach)\", and the ` +
    `model returns exactly [\"fraud\", \"IP\", \"data breach\"] in ${COPIED_ABSENT} absent cells and ${COPIED_VALUE} value cells across the ` +
    "E6 and E8a arms. In 8 of the 10 contracts where this happens, the retrieved chunks mention neither fraud nor a data breach.",
  ),
  bullet(
    "**Derived and placeholder values.** initial_term is computed from dates the contract gives, and a few execution dates are placeholders such " +
    "as 2026-01-01.",
  ),

  h2("6.8  E8a: An explicit null policy in the system prompt"),
  p(
    "E8a tests the obvious fix: a system prompt that adds three rules to the original (return null unless the text explicitly states the value; " +
    "examples in a field definition and the JSON template are never values to copy; blanks, template wording and sample data are not values). " +
    "Everything else equals the k = 5 arm, so the comparison is paired on the same cells (Table 11).",
  ),
  tableTitle("**Table 11.** E8a: null-policy prompt against the original prompt (R07, k = 5, Qwen3 30B, development split, 3 repeats)."),
  table(
    ["Metric", "Original prompt", "Null policy", "Difference (95% CI)", "p"],
    [
      ["Semantic", f3(D8.semantic[NULLP].base), f3(D8.semantic[NULLP].arm), ci(D8.semantic[NULLP]), pv(D8.semantic[NULLP].p)],
      ["Score (partial credit)", f3(D8.score[NULLP].base), f3(D8.score[NULLP].arm), ci(D8.score[NULLP]), pv(D8.score[NULLP].p)],
      ["Exact", pc(D8.exact[NULLP].base), pc(D8.exact[NULLP].arm), pts(D8.exact[NULLP]) + " points", pv(D8.exact[NULLP].p)],
      ["Invented on absent", pc(D8.invented[NULLP].base), pc(D8.invented[NULLP].arm), pts(D8.invented[NULLP]) + " points", pv(D8.invented[NULLP].p)],
      ["Invented on absent, high confidence", pc(D8.invented_high[NULLP].base), pc(D8.invented_high[NULLP].arm), pts(D8.invented_high[NULLP]) + " points", pv(D8.invented_high[NULLP].p)],
      ["Cost per contract (USD)", usd(A[K5].cost), usd(A[NULLP].cost), "", ""],
    ],
    [30, 15, 15, 26, 14],
  ),
  p(""),
  p(
    "The prompt had no measurable effect on any metric, and the copied definition example became, if anything, more frequent " +
    `(${CP(K5)} to ${CP(NULLP)} absent cells). The logged LLM calls confirm that every E8a call carried the new rules. The generic field prompt ` +
    "already told the model not to infer, guess or invent values, so the model had been ignoring that instruction too. The lesson for practice is " +
    "to remove errors at their source, in the field definitions and the labelling policy, rather than adding instructions the reader does not follow.",
  ),

  h2("6.9  Validating the semantic score (RQ6)"),
  p(
    "Exact and partial-credit scores count paraphrased but correct answers as wrong, which is most visible on structured fields. Under the semantic " +
    "score, Qwen3's score on structured values whose evidence was retrieved rises from 0.24 to 0.47, and on lists from 0.10 to 0.60, while the " +
    "ranking of systems is unchanged (Tables 5 and 8). Grading all E1 runs cost USD 0.12.",
  ),
  p(
    `The grader was not validated against human grades. Instead, ${G.n} randomly sampled cells from E1 and E6 were re-graded by a second, ` +
    `independent model from another provider (Gemini 4 Argon; Table 12). The two graders agree on ${pc(G.agreement, 0)} of cells (Cohen's kappa ` +
    `${G.kappa.toFixed(2)}, substantial agreement) and on ${pc(G.correct_agreement, 0)} for the binary decision correct versus not correct. The main ` +
    `disagreement is partial versus correct (${G.confusion["partial->correct"]} of ${G.n} cells), with GPT-6 Luna slightly stricter; only ` +
    `${G.confusion["correct->wrong"] + G.confusion["wrong->correct"]} cells were graded correct by one model and wrong by the other. We therefore ` +
    "treat semantic scores as reliable for comparing arms, which share the grader, but not as calibrated absolute accuracies.",
  ),
  tableTitle(`**Table 12.** Grades of the two graders on ${G.n} sampled cells (rows: GPT-6 Luna, columns: Gemini 4 Argon).`),
  table(
    ["GPT-6 Luna \\ Gemini 4 Argon", "correct", "partial", "wrong", "Total"],
    ["correct", "partial", "wrong"].map((a) => [a, ...["correct", "partial", "wrong"].map((b) => String(G.confusion[`${a}->${b}`] || 0)),
      String(["correct", "partial", "wrong"].reduce((s, b) => s + (G.confusion[`${a}->${b}`] || 0), 0))]),
    [34, 16, 16, 16, 18],
  ),
  p(""),
];

const discussion = [
  h1("7  Discussion"),
  p(
    "**Retrieval was the first bottleneck, and its failures were ranking failures.** Almost all evidence is indexed (98%), but at k = 5 only " +
    "57–71% of it reaches the reader, and values scored without their evidence are close to zero. Every intervention that raised recall without " +
    "changing the reader also raised extraction quality. Chunking, which the original plan treated as a likely culprit, loses only 2% of evidence.",
  ),
  p(
    "**Simple configuration errors dominate hand-designed pipelines.** Half of the current system's retrieval configurations used a similarity " +
    "threshold that removes nearly all context, and a top-k setting that the per-query pool silently capped. Neither problem is visible in an " +
    "end-to-end accuracy figure; both are obvious in a retrieval-only evaluation that costs nothing to run. We recommend fixed-k retrieval with no " +
    "absolute threshold, and an evidence-recall check whenever retrieval settings change.",
  ),
  p(
    "**Ensembles with a weak judge waste computation.** Running seven configurations and letting a small model choose among them was no better than " +
    "the best single configuration, because the judge cannot tell correct values from incorrect ones. A judge is only useful if it is " +
    "substantially better at verification than the reader is at extraction; whether a deterministic check (is the quoted evidence actually in the " +
    "document?) does better is the subject of E9.",
  ),
  p(
    "**Long-context readers change the trade-off.** With a 262k-token context window, Qwen3 30B benefits from up to four times as many chunks, and " +
    "the \"lost in the middle\" degradation [10] does not outweigh the recall gain at this scale (about 9,000 tokens per call). Returns diminish: " +
    "k = 10 captures most of the gain at well under the cost of k = 20. A reranker, the standard remedy for poor ranking, mainly helps when the " +
    "reader can take only a few chunks, as with an 8k-context local model. Whether the trend continues to the whole contract is the question of E10.",
  ),
  p(
    "**After retrieval, the reader and the labels are the limit.** At k = 20, retrieval failures are down to 6% of values; wrong and partially " +
    "correct readings dominate. The invented values that rise with context are mostly not free hallucinations but disagreements about what a " +
    "field should hold (relative dates, document status) and copies of the field definition. A prompt rule did not change them; clearer field " +
    "definitions and an explicit labelling policy for derived values are the more promising fix.",
  ),
  p(
    "**Scoring choices change conclusions about readers.** Under exact scoring, structured fields appeared to be read badly even with the right " +
    "evidence; under semantic scoring, much of that gap was paraphrase. Reports on contract extraction should state which notion of correctness " +
    "they use, and should not compare strict and lenient numbers across studies.",
  ),
];

const threats = [
  h1("8  Threats to Validity"),
  bullet(
    "**Draft labels.** Labels were written by an LLM and not verified by hand. Errors in labels lower all arms alike and so affect absolute numbers " +
    "more than paired differences, but a systematic labelling style can favour models that write like the labeller; a Claude-family model would " +
    "likely be favoured, which is why the ceiling model in E13 is planned to come from another family. Every claimed effect is checked on " +
    "high-confidence labels.",
  ),
  bullet(
    "**Label policy for derived values.** Several absent labels (relative expiry dates, document status) record a policy choice rather than a fact, " +
    "so the invented-value rate overstates hallucination on those fields (Section 6.7).",
  ),
  bullet(
    "**LLM-graded semantic score.** The semantic score is graded by an LLM and is not human-validated. Agreement with a second grader is " +
    "substantial (kappa 0.68) but not perfect, and both graders may share biases. We report exact, partial-credit and lenient scores alongside it.",
  ),
  bullet(
    "**Sample size.** The development split has 36 contracts, so effects smaller than about 0.03 in score cannot be resolved, and per-type " +
    "breakdowns are descriptive only. The test split (108 contracts) will give tighter intervals.",
  ),
  bullet(
    "**Tuning on the development split.** Configurations are selected on the same 36 contracts on which they are reported, so the reported gains " +
    "are optimistic. Final claims will rest on the held-out test split.",
  ),
  bullet(
    "**Code versions.** The experiments ran on several commits (the reranker and its cache were added between E1 and E6). Arms are compared only " +
    "within an experiment or between experiments whose extraction code is identical (E6, E6b and E8a); other cross-experiment numbers are marked " +
    "as indicative. The plan re-runs the baseline on the frozen final code.",
  ),
  bullet(
    "**Failed runs.** Up to 6 of 108 runs per arm failed (provider errors and timeouts, most during a memory overload) and were retried; paired " +
    "comparisons use cells present in both arms.",
  ),
  bullet(
    "**Public documents.** The contracts are public SEC filings that may appear in the models' pre-training data, which could inflate absolute " +
    "accuracy, mostly for well-known parties and dates.",
  ),
  bullet(
    "**Evidence matching.** Evidence recall relies on fuzzy matching of quotes (80% token coverage) and covers only labels that have a quote; " +
    "evidence for absent fields and for values inferred from several passages is not measured.",
  ),
];

const critique = [
  h1("9  Critique and Improvements"),
  p(
    "Building the platform and running the first experiments exposed weaknesses in both the software and the research design. This section " +
    "lists them honestly, with the improvement each suggests; Table 13 gathers them by priority.",
  ),
  h2("9.1  Engineering"),
  bullet(
    "**The default pipeline is the weakest configuration.** New runs still default to the seven-configuration ensemble with a judge, which E1 " +
    "and E11 show is slower, costlier and less accurate than a single hybrid configuration. The default should follow the evidence: hybrid " +
    "retrieval with anchors, k = 10, no judge.",
  ),
  bullet(
    "**No schema migrations.** schema.sql is the single source of truth and the documented way to change it is to recreate the database. The " +
    "reranker columns were therefore added to the live database by hand, because recreating it would have deleted the experiment data. " +
    "Versioned migrations (for example Alembic) would make such changes safe and repeatable.",
  ),
  bullet(
    "**New pipeline settings are not yet in the API or the interface.** The reranker's model and candidate count exist in the schema and the " +
    "pipeline but can be set only through SQL presets. Every configuration flag should be editable where the others are.",
  ),
  bullet(
    "**Resource limits are implicit.** Eight workers each loading a 2–3.5 GB reranker exhausted a 16 GB laptop and failed runs through timeouts. " +
    "The fix (a shared on-disk score cache, lazy loading, a thread cap) works, but a worker should declare the resources a run needs, or the " +
    "model should run in one shared service, so that adding workers cannot overload the machine.",
  ),
  bullet(
    "**Failure handling is minimal.** A run is attempted once; provider timeouts and disconnects fail the whole run, and the experiment runner " +
    "re-queues it. Retrying a single failed field with back-off would lose less work.",
  ),
  bullet(
    "**No authentication and no continuous integration.** The gateway is designed to hold authentication but does not yet, so the system must " +
    "not be exposed beyond one machine. The tests run only when a developer runs them; a CI pipeline running the three offline suites, the type " +
    "checks and the linter on every push would catch regressions earlier.",
  ),
  bullet(
    "**Structured results are hard to read.** The results page shows structured values as raw JSON side by side (Figure 3). A field-by-field " +
    "comparison that highlights the differing sub-fields would make reviewing extractions much faster. Run progress is polled every two " +
    "seconds; server-sent events would be lighter.",
  ),
  h2("9.2  Research"),
  bullet(
    "**Labels are drafts.** Every label was written by an LLM, and some encode a policy choice (Section 6.7). A hand-verified subset of 30–50 " +
    "contracts, and an explicit labelling policy for derived and relative values, would turn the invented-value rate into a trustworthy measure.",
  ),
  bullet(
    "**The development split is small.** With 36 contracts, effects below about 0.03 cannot be resolved, and per-type results are anecdotal. " +
    "Only the final test run (108 contracts) can confirm the findings.",
  ),
  bullet(
    "**One reader model.** All grids use Qwen3 30B. The context-size result may not transfer to a reader with a short context window or a " +
    "different family; E12 tests a local model, and a second hosted reader would strengthen the claim.",
  ),
  bullet(
    "**Prompt instructions are a weak control.** E8a showed that the reader ignores system-prompt rules. Structural controls, such as JSON " +
    "Schema-constrained output and a required verbatim evidence span that is checked against the document, are the better next steps.",
  ),
  bullet(
    "**Partial credit dominates the remaining error.** About 44% of values are partially correct at k = 20, mostly structured fields with some " +
    "sub-fields missing. Reporting sub-field recall and precision separately would show which sub-fields the reader misses.",
  ),
  bullet(
    "**Code changed between experiments.** Only experiments on identical extraction code are compared directly. Freezing the code, tagging the " +
    "commit and re-running the baseline before the final experiments, as planned, removes this caveat.",
  ),
  tableTitle("**Table 13.** Improvements by priority."),
  table(
    ["Priority", "Improvement", "Why"],
    [
      ["High", "Make hybrid retrieval, k = 10, no judge the default pipeline", "better, cheaper and faster on every measure so far"],
      ["High", "Hand-verify a label subset; write a labelling policy for derived values", "makes accuracy and invented-value rates trustworthy"],
      ["High", "Schema-constrained output and evidence-span checks (E8, E9)", "prompt rules alone do not change the reader's behaviour"],
      ["Medium", "Versioned schema migrations", "safe changes to a database that holds experiment data"],
      ["Medium", "CI for the offline test suites, type checks and linter", "regressions caught on every push"],
      ["Medium", "Expose every pipeline flag in the API and UI; per-field retries", "no SQL needed to configure; fewer lost runs"],
      ["Medium", "Field-by-field diff view for structured results", "faster review of extractions"],
      ["Low", "Shared model service or declared worker resources", "adding workers cannot overload the machine"],
      ["Low", "Authentication in the gateway; server-sent events for progress", "needed before any multi-user deployment"],
    ],
    [11, 49, 40], { left: true },
  ),
  p(""),
];

const conclusion = [
  h1("10  Conclusion and Future Work"),
  p(
    "On the development split, the largest gains in contract extraction came not from a bigger ensemble or a judge but from getting the right text " +
    "to the reader: removing a context-starving threshold, adding lexical search and anchor chunks, and passing more chunks to a reader that can " +
    `use them. A single hybrid configuration with 20 chunks and Qwen3 30B reaches a semantic score of ${f2(A[K20].semantic)} at about one US cent ` +
    `per contract, against ${f2(A[CUR].semantic)} for the current seven-configuration system with Llama 3.1 8B at almost a cent per contract; ` +
    `10 chunks reach ${f2(A[K10].semantic)} for ${usd(A[K10].cost)} USD. A cross-encoder reranker substitutes for hybrid retrieval rather than ` +
    "adding to it, and its retrieval gain does not reach the answers. More context also brings more invented values on absent fields, which a " +
    "prompt rule does not remove; they trace back to field definitions and labelling policy.",
  ),
  tableTitle("**Table 13.** Experiment programme and status."),
  table(
    ["#", "Question", "Status"],
    [
      ["E1", "Baseline and noise floor", "Done (Section 6.1)"],
      ["E2", "Retrieval sweep: top-k, threshold, hits per query", "Done (Section 6.3)"],
      ["E3", "Embedding models: nomic with and without task prefixes, Qwen3-Embedding, bge-m3", "Planned"],
      ["E4", "Chunking: per page vs structure-aware, chunk size, contextual chunk text", "Planned"],
      ["E5", "Query expansion × hybrid search (2×2), HyDE and description-as-query", "Planned"],
      ["E6", "Reranking and context size (k = 5, 10, 20)", "Done (Sections 6.4–6.6)"],
      ["E7", "Decomposition method for PDFs", "Planned"],
      ["E8", "Reader: null-policy prompt; field vs group calls, schema-constrained output, quote-then-answer, oracle evidence", "Null-policy arm done (6.8); rest planned"],
      ["E9", "Verification: LLM judge vs evidence-span check", "Planned"],
      ["E10", "RAG vs whole contract in a long context", "Planned (last before the test run)"],
      ["E11", "Ensemble with judge selection", "Done (Section 6.2)"],
      ["E12", "Leave-one-out ablation and transfer to a local model", "Planned"],
      ["E13", "Test split, once: baseline, full stack, long context, frontier ceiling", "Planned"],
    ],
    [8, 62, 30], { left: true },
  ),
  p(""),
  h2("10.1  Plan for the remaining work"),
  p(
    "The remaining experiments run in the order below, all on the development split until the final test run. Retrieval experiments are scored " +
    "with the free retrieval-only evaluation first, and only their best arms are run end to end. Costs are estimates at the measured cost per arm " +
    `(about USD ${(A[K10].cost * 108).toFixed(2)} for one k = 10 arm over 36 contracts and three repeats).`,
  ),
  tableTitle("**Table 14.** Order and estimated LLM cost of the remaining experiments."),
  table(
    ["Step", "Experiment", "What it decides", "Estimated cost (USD)"],
    [
      ["1", "E5 query expansion × hybrid", "whether expansion and BM25 each help, and HyDE or description queries", "0 retrieval + ≈ 1.5 end to end"],
      ["2", "E3 embeddings", "whether a stronger embedding model or nomic task prefixes raise recall", "0 retrieval + ≈ 1.5"],
      ["3", "E4 chunking", "structure-aware and contextual chunks", "≈ 1.5 (+ 4–6 for contextual chunk text)"],
      ["4", "E8 reader (rest)", "group calls, constrained output, quote-then-answer, clearer field definitions, oracle evidence", "≈ 3"],
      ["5", "E9 verification", "LLM judge vs evidence-span check", "≈ 2"],
      ["6", "E7 decomposition", "PDF converters on the 42 PDFs", "≈ 1.5"],
      ["7", "E12 ablation and transfer", "what each component is worth in the full stack; local model", "≈ 3"],
      ["8", "E10 long context", "RAG vs the whole contract in context", "≈ 1–6"],
      ["9", "E13 test split", "final, once: baseline, full stack, long context, frontier ceiling", "≈ 30"],
    ],
    [7, 24, 47, 22], { left: true },
  ),
  p(""),
  p(
    "An error analysis of 50 test-set failures, classified as not indexed, not retrieved, retrieved but misread, normalisation, or label error " +
    "using the evidence-recall data, will decide whether further effort should go to the retriever or the reader.",
  ),
];

const references = [
  h1("References"),
  ...[
    "[1] B. Efron and R. J. Tibshirani. *An Introduction to the Bootstrap.* Chapman & Hall, 1993.",
    "[2] J. Chen, S. Xiao, P. Zhang, K. Luo, D. Lian and Z. Liu. BGE M3-Embedding: Multi-lingual, multi-functionality, multi-granularity text embeddings through self-knowledge distillation. *Findings of ACL*, 2024.",
    "[3] G. V. Cormack, C. L. A. Clarke and S. Büttcher. Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. *SIGIR*, 2009.",
    "[4] S. Es, J. James, L. Espinosa-Anke and S. Schockaert. RAGAS: Automated evaluation of retrieval augmented generation. *EACL System Demonstrations*, 2024.",
    "[5] R. Dror, G. Baumer, S. Shlomov and R. Reichart. The hitchhiker's guide to testing statistical significance in natural language processing. *ACL*, 2018.",
    "[6] D. Hendrycks, C. Burns, A. Chen and S. Ball. CUAD: An expert-annotated NLP dataset for legal contract review. *NeurIPS Datasets and Benchmarks*, 2021.",
    "[7] S. Holm. A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics*, 6(2):65–70, 1979.",
    "[8] Y. Koreeda and C. D. Manning. ContractNLI: A dataset for document-level natural language inference for contracts. *Findings of EMNLP*, 2021.",
    "[9] P. Lewis, E. Perez, A. Piktus et al. Retrieval-augmented generation for knowledge-intensive NLP tasks. *NeurIPS*, 2020.",
    "[10] N. F. Liu, K. Lin, J. Hewitt, A. Paranjape, M. Bevilacqua, F. Petroni and P. Liang. Lost in the middle: How language models use long contexts. *TACL*, 12, 2024.",
    "[11] R. Nogueira and K. Cho. Passage re-ranking with BERT. arXiv:1901.04085, 2019.",
    "[12] S. Robertson and H. Zaragoza. The probabilistic relevance framework: BM25 and beyond. *Foundations and Trends in Information Retrieval*, 3(4), 2009.",
    "[13] J. Saad-Falcon, O. Khattab, C. Potts and M. Zaharia. ARES: An automated evaluation framework for retrieval-augmented generation systems. *NAACL*, 2024.",
    "[14] D. Tuggener, P. von Däniken, T. Peetz and M. Cieliebak. LEDGAR: A large-scale multi-label corpus for text classification of legal provisions in contracts. *LREC*, 2020.",
    "[15] Q. McNemar. Note on the sampling error of the difference between correlated proportions or percentages. *Psychometrika*, 12(2):153–157, 1947.",
    "[16] L. Zheng, W.-L. Chiang, Y. Sheng et al. Judging LLM-as-a-judge with MT-Bench and Chatbot Arena. *NeurIPS Datasets and Benchmarks*, 2023.",
  ].map((t) => new Paragraph({ children: runs(t, { size: 20 }), indent: { left: 440, hanging: 440 }, spacing: { after: 80 } })),
];

const appendix = [
  h1("Appendix A  Retrieval configurations"),
  tableTitle("**Table A1.** Retrieval configurations used in this report. Expansion = field label plus expansion queries."),
  table(
    ["Name", "Top-k", "Threshold", "Expansion", "Hits / query", "BM25", "Anchors", "Reranker"],
    [
      ["RAG01", "10", "0.5", "yes", "3", "no", "0", "—"],
      ["RAG02", "5", "0.5", "yes", "3", "no", "0", "—"],
      ["RAG03", "3", "0.5", "yes", "3", "no", "0", "—"],
      ["RAG04", "10", "0.7", "no", "3", "no", "0", "—"],
      ["RAG05", "5", "0.7", "no", "3", "no", "0", "—"],
      ["RAG06", "3", "0.7", "no", "3", "no", "0", "—"],
      ["RAG07", "5", "0.5", "yes", "3", "yes", "2", "—"],
      ["R-base", "5", "none", "yes", "5", "no", "0", "—"],
      ["R07-k5", "5", "0.5", "yes", "20", "yes", "2", "—"],
      ["R07-k10", "10", "0.5", "yes", "20", "yes", "2", "—"],
      ["R07-k20", "20", "0.5", "yes", "20", "yes", "2", "—"],
      ["R07-k5-rr", "5", "0.5", "yes", "20", "yes", "2", "bge-reranker-v2-m3 (int8), 40 candidates"],
    ],
    [12, 8, 10, 11, 11, 8, 9, 31],
  ),
  p(""),
  h1("Appendix B  Experiment log and cost"),
  tableTitle("**Table B1.** Experiments run so far (development split). LLM cost from the runs' logged calls at OpenRouter list prices."),
  table(
    ["Experiment", "Arms × repeats", "Runs (incl. retries)", "LLM cost (USD)", "Notes"],
    [
      ["E1 baseline", "2 × 3", String(N.cost_log[0].runs), N.cost_log[0].cost.toFixed(2), "current system and R-base; also yields E11"],
      ["E2 retrieval sweeps", "37 configs", "—", "0", "retrieval only, no LLM calls"],
      ["E6 reranker retrieval", "8 configs", "—", "0", "local CPU, about 78 minutes"],
      ["E6 end to end", "3 × 3", String(N.cost_log[1].runs), N.cost_log[1].cost.toFixed(2), "R07-k5, R07-k20, R07-k5-rr"],
      ["E6b k = 10", "1 × 3", String(N.cost_log[2].runs), N.cost_log[2].cost.toFixed(2), "R07-k10"],
      ["E8a null policy", "1 × 3", String(N.cost_log[3].runs), N.cost_log[3].cost.toFixed(2), "R07-k5 with the null-policy prompt"],
      ["Semantic grading", "—", "—", (0.12 + 0.10 + 0.02 + 0.02).toFixed(2), "GPT-6 Luna, E1, E6, E6b, E8a"],
      ["Grader cross-check", "150 cells", "—", "0.27", "Gemini 4 Argon"],
      ["**Total**", "", "", `**${SPENT.toFixed(2)}**`, ""],
    ],
    [22, 14, 14, 14, 36],
  ),
];

// ---------- document ----------

const doc = new Document({
  creator: "Ram",
  title: "What Improves LLM Contract Extraction?",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: FONT }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: FONT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, italics: true, font: FONT }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
      { reference: "rq", levels: [{ level: 0, format: LevelFormat.NONE, text: "", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 360 } } } }] },
    ],
  },
  sections: [
    {
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
      headers: {
        default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: "What Improves LLM Contract Extraction? Progress report", size: 16, color: "8A8A8A" })] })] }),
      },
      footers: {
        default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ children: [PageNumber.CURRENT], size: 18 })] })] }),
      },
      children: [
        ...title, ...abstract, ...progress, ...introduction, ...related, ...system, ...data, ...method, ...results,
        ...discussion, ...threats, ...critique, ...conclusion, ...references, ...appendix,
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`wrote ${OUT}`);
});
