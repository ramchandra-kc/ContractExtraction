# Future plan: research write-up

The system is built; the findings are not. This plan turns the platform into a research write-up: experiments first,
writing last.

## 1. Research questions

1. **Retrieval:** does hybrid search (BM25 + dense + field anchors, RAG07) beat dense-only on accuracy and evidence recall?
2. **Models:** local `llama3.1:8b` vs low-cost OpenRouter models: accuracy, cost and latency per contract.
3. **LLM judge:** how often do its verdicts agree with ground truth?
4. **Contract types:** does classifying first and extracting only that type's fields improve accuracy or cost?
5. *(Optional)* **Formats:** accuracy lost on OCR'd scans vs native PDF / DOCX / HTML of the same contract.
6. **Fine-tuning:** can a fine-tuned small local model match larger hosted models at a fraction of the cost?
   What to tune is decided by the error analysis (R5):
   - retrieval misses dominate → fine-tune the embedding model or add a reranker, trained on (field query, CUAD
     excerpt) pairs;
   - model / normalisation errors dominate → LoRA-tune the extraction model on (retrieved chunks + field → JSON value).
   - The judge is tuned only if its agreement with ground truth is poor.

## 2. Dataset

- **CUAD v1** (510 EDGAR contracts, 41 clause categories, CC BY 4.0) as the public benchmark.
  - `master_clauses.csv` "Answer" column → ground truth for dates, terms, notice periods, governing law, parties.
  - Yes/No answers → `exists` keys and boolean fields.
  - `CUAD_v1.json` excerpt offsets → retrieval recall (did a retrieved chunk overlap the labelled excerpt?).
- **Hand labels** on a 30–50 contract subset for structured keys CUAD lacks (scope, territory, duration) and fields
  it doesn't cover (force majeure, payment terms).
- Own contracts in `test_data/` only as extra results; never quote names or details from them.
- Verify CUAD column names before writing the importer.

## 3. Work items

| # | Item | Done when |
|---|---|---|
| R1 | CUAD importer: CSV answers → ground truth, normalised to catalogue types | ~500 contracts labelled for mapped fields |
| R2 | Results export: per run / field / document → CSV | All tables and charts come from the export |
| R3 | Baseline run: one frozen pipeline | Baseline numbers recorded with run ids |
| R4 | Experiments: change one thing at a time; ≥3 seeds where temperature > 0 | One results table per research question |
| R5 | Error analysis: 30–50 failures by cause (decomposition/OCR, chunking, retrieval, model, normalisation, label wrong) | Category counts and examples |
| R6 | Write-up | Draft complete |

### Fine-tuning (after R5)

| # | Item | Done when |
|---|---|---|
| F1 | CUAD split by contract (~400 train / ~110 test); the test set is shared by every experiment, prompting included | Split file committed; no contract in both sets |
| F2 | Training-set builder: extraction examples and/or retrieval pairs from the train split | JSONL sets generated from the database and CUAD |
| F3 | Strong baselines on the test split: few-shot prompting, larger OpenRouter models | Numbers to beat recorded |
| F4 | Training: MLX-LM LoRA on 4-bit `llama3.1:8b` (or embedding / reranker tuning) | Adapter or model trained, training config recorded |
| F5 | Serving: convert to GGUF, Ollama Modelfile, new model profile | Fine-tuned model runs through the normal pipeline |
| F6 | Comparison: test split plus own contracts (generalisation beyond EDGAR) | Accuracy, cost and latency vs F3 |

Fine-tuning won't fix decomposition / OCR errors, chunk boundaries, label gaps, or fields CUAD doesn't cover
(force majeure, payment terms).

## 4. Metrics

- Exact match and partial-credit score (`evaluation.py`), per field and overall
- "Not present" detection (invented values on empty labels)
- Retrieval recall against CUAD excerpts
- Judge agreement with ground truth (precision / recall of verdicts)
- Tokens, cost and seconds per contract

## 5. Write-up outline

1. Abstract
2. Introduction and contributions
3. Related work: CUAD, LegalBench, RAG for long documents, LLM-as-judge
4. System design (condensed from `architecture.md` and the ADRs)
5. Dataset and labelling rules
6. Experimental setup
7. Results, one subsection per research question
8. Error analysis
9. Limitations: dataset size, US-only contracts, small models, CUAD label gaps
10. Conclusion; appendix with prompts and field catalogue

## Open questions

- Target format: technical report, paper, or thesis chapter (decides rigour and related-work depth).
- Which OpenRouter models to compare, and the cost budget for full CUAD runs.
- Fine-tuning target (extraction model, retriever, or both): decided by R5.
