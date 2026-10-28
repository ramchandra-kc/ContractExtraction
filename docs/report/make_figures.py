"""Figures and numbers for the research report, computed from the experiment exports in experiments/.

Run from backend/ (it uses the project's statistics):
    uv run --with matplotlib python ../docs/report/make_figures.py

Writes figures/*.png and figures/numbers.json; build_report.js reads the JSON, so no result is typed by hand.
Every interval is a 95% cluster bootstrap over documents (contract_extraction.compare).
"""
import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from contract_extraction.compare import cells, compare_arms, read_rows
from contract_extraction.semantic import agreement

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments"
OUT = Path(__file__).parent / "figures"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, VIOLET, GREY, RED = "#2a78d6", "#eb6834", "#1baf7a", "#8a5cd6", "#9a9893", "#c8423b"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.axisbelow": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
    "legend.frameon": False,
})

# Arms: pipeline name → label used in the report.
CURRENT, RBASE = "or-llama31-8b", "e1-qwen3-rbase"
K5, K10, K20, RR, NULLP = "e6-qwen3-k5", "e6-qwen3-k10", "e6-qwen3-k20", "e6-qwen3-k5-rr", "e8-qwen3-k5-nullpolicy"
LABEL = {CURRENT: "Current system", RBASE: "R-base", K5: "k = 5", K10: "k = 10", K20: "k = 20",
         RR: "k = 5 + reranker", NULLP: "k = 5 + null policy"}
HIGH = {"label_confidence": "high"}


def csv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def by_key(path, key):
    return {r[key]: r for r in csv_rows(path)}


E1 = read_rows(EXP / "e1-baseline" / "results.csv")
E6 = read_rows(EXP / "e6-combined" / "results.csv")  # e6-reader (k5, k20, rr) + e6b-k10, same code and cells
E8 = read_rows(EXP / "e8a-combined" / "results.csv")  # e6-reader's k5 + e8a-nullpolicy
ALL = E1 + E6 + [r for r in E8 if r["pipeline"] == NULLP]
SUMMARY = {**by_key(EXP / "e1-baseline" / "summary.csv", "pipeline"), **by_key(EXP / "e6-reader" / "summary.csv", "pipeline"),
           **by_key(EXP / "e6b-k10" / "summary.csv", "pipeline"), **by_key(EXP / "e8a-nullpolicy" / "summary.csv", "pipeline")}


def mean_ci(rows, arm, metric, labels="value", where=None, resamples=10_000, seed=0):
    """An arm's mean over cells with a 95% cluster bootstrap interval (documents resampled)."""
    cs = cells([r for r in rows if r["pipeline"] == arm], ["pipeline"], metric, labels, where)[arm]
    per_doc = defaultdict(list)
    for (doc, _), v in cs.items():
        per_doc[doc].append(v)
    docs = sorted(per_doc)
    sums, counts = [sum(per_doc[d]) for d in docs], [len(per_doc[d]) for d in docs]
    rng = random.Random(seed)
    boot = sorted(sum(sums[i] for i in idx) / sum(counts[i] for i in idx)
                  for idx in ([rng.randrange(len(docs)) for _ in docs] for _ in range(resamples)))
    return {"mean": sum(sums) / sum(counts), "lo": boot[int(0.025 * resamples)], "hi": boot[int(0.975 * resamples)],
            "cells": len(cs), "documents": len(docs)}


def diffs(rows, baseline, metric, labels="value", where=None):
    return {c.arm: {"base": c.baseline_mean, "arm": c.arm_mean, "diff": c.diff, "lo": c.ci_low, "hi": c.ci_high,
                    "p": c.p, "p_holm": c.p_holm, "cells": c.cells, "documents": c.documents,
                    "b": c.b, "c": c.c, "mcnemar_p": c.mcnemar_p}
            for c in compare_arms(rows, ["pipeline"], baseline, metric, labels, where)}


def summary_row(arm):
    s = SUMMARY[arm]
    f = lambda k: float(s[k]) if s.get(k) not in ("", None) else None  # noqa: E731
    return {"runs_succeeded": int(s["runs_succeeded"]), "runs_failed": int(s["runs_failed"]),
            "exact": f("value_exact"), "score": f("value_score"), "lenient": f("value_lenient"),
            "missed": f("value_missed"), "absent_correct": f("absent_correct"), "invented": f("invented"),
            "recall": f("evidence_recall"), "score_with_evidence": f("score_with_evidence"),
            "score_without_evidence": f("score_without_evidence"), "llm_calls": f("llm_calls_per_run"),
            "tokens": f("tokens_per_run"), "cost": f("cost_usd_per_run"), "seconds": f("seconds_per_run")}


def arm_numbers(rows, arm):
    out = summary_row(arm)
    for m in ("semantic", "score", "exact"):
        out[f"{m}_ci"] = mean_ci(rows, arm, m)
        out[f"{m}_high_ci"] = mean_ci(rows, arm, m, where=HIGH)
    out["invented_ci"] = mean_ci(rows, arm, "invented", labels="absent")
    out["recall_ci"] = mean_ci(rows, arm, "evidence")
    out["semantic"] = out["semantic_ci"]["mean"]
    return out


def errorbar_args(cis):
    return [[c["mean"] - c["lo"] for c in cis], [c["hi"] - c["mean"] for c in cis]]


# ---------- numbers ----------

def retrieval_numbers():
    seeded = by_key(EXP / "e2-seeded" / "retrieval_summary.csv", "retrieval_config")
    sweep = by_key(EXP / "e2-q-sweep" / "retrieval_summary.csv", "retrieval_config")
    rerank = by_key(EXP / "e6-rerank" / "retrieval_summary.csv", "retrieval_config")
    pick = lambda r: {k: float(r[k]) for k in ("recall", "recall_at_1", "mrr", "not_indexed", "mean_hits")}  # noqa: E731
    hits = read_rows(EXP / "e6-rerank" / "retrieval_hits.csv")
    rr = "r=bge-reranker-v2-m3-int8"
    gains = {}
    for base in ("R-base", "RAG07"):
        family = [r for r in hits if r["retrieval_config"].startswith(base + " ")]
        for c in compare_arms(family, ["retrieval_config"], f"{base} k=5 q=20 r=none c=40", "evidence", "all"):
            if rr in c.arm:
                gains[c.arm] = {"diff": c.diff, "lo": c.ci_low, "hi": c.ci_high, "p": c.p, "p_holm": c.p_holm}
    return {
        "rerank_gain": gains,
        "seeded": {k: pick(v) for k, v in seeded.items()},
        "sweep": {k: pick(v) for k, v in sweep.items()},
        "rerank": {k: pick(v) for k, v in rerank.items()},
    }


def attribution(rows, arm):
    """Value cells (every repeat) by outcome: correct / partial / wrong with or without the evidence retrieved."""
    c = Counter()
    for r in rows:
        if r["pipeline"] != arm or r["label"] != "value" or r["run_state"] != "succeeded" or r["semantic"] == "":
            continue
        s = float(r["semantic"])
        if s >= 0.999:
            c["correct"] += 1
        elif s > 0.001:
            c["partial"] += 1
        else:
            c["wrong_retrieved" if r["evidence_any"] == "true" else "wrong_not_retrieved"] += 1
    n = sum(c.values())
    return {k: c[k] / n for k in ("correct", "partial", "wrong_retrieved", "wrong_not_retrieved")} | {"n": n}


def invented_by_field(rows, arms, top=8):
    counts = defaultdict(Counter)
    for r in rows:
        if r["label"] == "absent" and r["run_state"] == "succeeded" and r["status"] != "error" and r["pipeline"] in arms:
            counts[(r["field"], r["pipeline"])]["n"] += 1
            counts[(r["field"], r["pipeline"])]["inv"] += r["status"] == "extracted"
    fields = {f for f, _ in counts}
    rate = {f: {a: counts[(f, a)]["inv"] / counts[(f, a)]["n"] for a in arms if counts[(f, a)]["n"]} for f in fields}
    share = {f: sum(counts[(f, a)]["inv"] for a in arms) for f in fields}
    total = {a: sum(counts[(f, a)]["inv"] for f in fields) for a in arms}
    order = sorted(fields, key=lambda f: -share[f])[:top]
    return {"fields": [{"field": f, "cells": counts[(f, arms[0])]["n"] // 3, "rate": rate[f],
                        "share_of_invented": {a: counts[(f, a)]["inv"] / total[a] for a in arms}} for f in order],
            "totals": total}


def copied_example(rows):
    value = '["fraud", "IP", "data breach"]'
    out = Counter()
    for r in rows:
        if r["status"] == "extracted" and r["value"] == value:
            out[(r["pipeline"], r["label"])] += 1
    return {f"{p}|{lab}": n for (p, lab), n in sorted(out.items())}


def cost_log():
    log = []
    for name in ("e1-baseline", "e6-reader", "e6b-k10", "e8a-nullpolicy"):
        runs = csv_rows(EXP / name / "runs.csv")
        log.append({"experiment": name, "runs": len(runs),
                    "succeeded": sum(r["state"] == "succeeded" for r in runs),
                    "cost": sum(float(r["cost_usd"] or 0) for r in runs)})
    return log


def grader():
    a = agreement(read_rows(EXP / "e1-baseline" / "semantic_crosscheck.csv"))
    return a


# ---------- figures ----------

def fig_recall_vs_k(ret):
    ks = [5, 10, 20]
    fig, ax = plt.subplots(figsize=(5.2, 3.0), dpi=200)
    for name, label, color in (("RAG02", "Dense (RAG02)", BLUE), ("RAG07", "Hybrid + anchors (RAG07)", ORANGE)):
        ys = [ret["sweep"][f"{name} k={k} t=0 q=20"]["recall"] * 100 for k in ks]
        ax.plot(ks, ys, color=color, linewidth=2, marker="o", markersize=5, label=label)
        for k, y in zip(ks, ys):
            ax.annotate(f"{y:.0f}%", (k, y), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(ks)
    ax.set_xlabel("Chunks passed to the reader (k), 20 hits per query")
    ax.set_ylabel("Evidence recall (%)")
    ax.set_ylim(40, 100)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "fig_recall_vs_k.png")
    plt.close(fig)


def fig_e1(nums):
    metrics = [("score_ci", "Score (partial credit)"), ("semantic_ci", "Semantic score"), ("invented_ci", "Invented on absent")]
    arms = [(CURRENT, GREY), (RBASE, BLUE)]
    fig, ax = plt.subplots(figsize=(5.4, 3.0), dpi=200)
    width = 0.36
    for i, (arm, color) in enumerate(arms):
        cis = [nums[arm][m] for m, _ in metrics]
        xs = [j + (i - 0.5) * (width + 0.03) for j in range(len(metrics))]
        ax.bar(xs, [c["mean"] for c in cis], width, color=color, label=LABEL[arm] + (" (Llama 3.1 8B, 7 configs + judge)" if arm == CURRENT else " (Qwen3 30B)"),
               yerr=errorbar_args(cis), error_kw={"elinewidth": 0.8, "capsize": 2.5, "ecolor": INK})
        for x, c in zip(xs, cis):
            ax.annotate(f"{c['mean']:.2f}", (x, c["hi"]), textcoords="offset points", xytext=(0, 2), ha="center", fontsize=7, color=INK)
    ax.set_xticks(range(len(metrics)), [m for _, m in metrics])
    ax.set_ylim(0, 0.6)
    ax.set_ylabel("Mean over cells")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=2, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(OUT / "fig_e1_baseline.png")
    plt.close(fig)


def fig_context(nums):
    ks = [5, 10, 20]
    arms = [K5, K10, K20]
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.0), dpi=200)
    for metric, label, color in (("semantic_ci", "Semantic", BLUE), ("score_ci", "Score (partial credit)", ORANGE),
                                 ("exact_ci", "Exact", AQUA)):
        cis = [nums[x][metric] for x in arms]
        a.errorbar(ks, [c["mean"] for c in cis], yerr=errorbar_args(cis), color=color, marker="o", markersize=4,
                   linewidth=1.8, capsize=2.5, elinewidth=0.8, label=label)
        rr = nums[RR][metric]
        a.errorbar([5.6], [rr["mean"]], yerr=errorbar_args([rr]), color=color, marker="D", markersize=4, mfc="white",
                   linestyle="none", capsize=2.5, elinewidth=0.8)
    a.set_xticks(ks)
    a.set_xlabel("Chunks passed to the reader (k)\n(open diamonds: k = 5 + reranker)")
    a.set_ylabel("Mean over value cells")
    a.set_ylim(0.1, 0.7)
    a.set_title("A. Quality on fields with a value", fontsize=9, loc="left")
    a.legend(loc="upper left", fontsize=7.5)
    for metric, label, color in (("recall_ci", "Evidence recall", VIOLET), ("invented_ci", "Invented on absent", RED)):
        cis = [nums[x][metric] for x in arms]
        b.errorbar(ks, [c["mean"] for c in cis], yerr=errorbar_args(cis), color=color, marker="o", markersize=4,
                   linewidth=1.8, capsize=2.5, elinewidth=0.8, label=label)
        rr = nums[RR][metric]
        b.errorbar([5.6], [rr["mean"]], yerr=errorbar_args([rr]), color=color, marker="D", markersize=4, mfc="white",
                   linestyle="none", capsize=2.5, elinewidth=0.8)
    b.set_xticks(ks)
    b.set_xlabel("Chunks passed to the reader (k)")
    b.set_ylabel("Share of cells")
    b.set_ylim(0, 1)
    b.set_title("B. Recall and invented values", fontsize=9, loc="left")
    b.legend(loc="center right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(OUT / "fig_context_size.png")
    plt.close(fig)


def fig_forest(d):
    metrics = [("semantic", "Semantic"), ("score", "Score"), ("exact", "Exact"), ("invented", "Invented on absent")]
    arms = [(K10, BLUE), (K20, ORANGE), (RR, AQUA), (NULLP, VIOLET)]
    fig, axes = plt.subplots(1, len(metrics), figsize=(7.2, 2.9), dpi=200, sharey=True)
    for ax, (m, title) in zip(axes, metrics):
        for i, (arm, color) in enumerate(arms):
            y = len(arms) - 1 - i
            for key, offset, filled in ((m, 0.13, True), (m + "_high", -0.13, False)):
                c = d[key][arm]
                ax.errorbar([c["diff"]], [y + offset], xerr=[[c["diff"] - c["lo"]], [c["hi"] - c["diff"]]], color=color,
                            marker="o", markersize=4, mfc=color if filled else "white", capsize=2, elinewidth=0.9)
        ax.axvline(0, color=MUTED, linewidth=0.8)
        ax.set_title(title, fontsize=8.5)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="x", labelsize=7)
    axes[0].set_yticks(range(len(arms)), [LABEL[a] for a, _ in reversed(arms)])
    fig.supxlabel("Paired difference vs k = 5 (95% CI); filled = all labels, open = high-confidence labels", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_forest.png")
    plt.close(fig)


def fig_cost(nums):
    arms = [CURRENT, RBASE, K5, K10, K20, RR, NULLP]
    colors = {CURRENT: GREY, RBASE: BLUE, K5: ORANGE, K10: ORANGE, K20: ORANGE, RR: AQUA, NULLP: VIOLET}
    pts = [(nums[a]["cost"] * 100, nums[a]["semantic"], a) for a in arms]
    fig, ax = plt.subplots(figsize=(5.4, 3.2), dpi=200)
    front, best = [], -1
    for x, y, a in sorted(pts):
        if y > best:
            front.append((x, y))
            best = y
    ax.plot(*zip(*front), color=MUTED, linewidth=0.9, linestyle="--", zorder=1, label="Pareto front")
    for x, y, a in pts:
        ci = nums[a]["semantic_ci"]
        ax.errorbar([x], [y], yerr=[[y - ci["lo"]], [ci["hi"] - y]], color=colors[a], marker="o", markersize=5,
                    capsize=2, elinewidth=0.8, zorder=2)
        dx, dy, ha = {CURRENT: (-7, -3, "right"), RBASE: (7, -3, "left"), K5: (-7, 4, "right"), NULLP: (-7, -12, "right"),
                      RR: (7, 6, "left"), K10: (7, -3, "left"), K20: (-7, 6, "right")}[a]
        ax.annotate(LABEL[a], (x, y), textcoords="offset points", xytext=(dx, dy), ha=ha, fontsize=7, color=INK,
                    arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.5} if a in (K5, NULLP, RR) else None)
    ax.set_xlabel("Cost per contract (US cents, OpenRouter list prices)")
    ax.set_ylabel("Semantic score")
    ax.set_xlim(0, 1.2)
    ax.set_ylim(0.25, 0.65)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(OUT / "fig_cost_quality.png")
    plt.close(fig)


def fig_attribution(att):
    arms = [CURRENT, RBASE, K5, K10, K20, RR]
    parts = [("correct", "Correct", AQUA), ("partial", "Partially correct", "#9fd8c2"),
             ("wrong_retrieved", "Wrong, evidence retrieved (reading)", ORANGE),
             ("wrong_not_retrieved", "Wrong, evidence not retrieved (retrieval)", GREY)]
    fig, ax = plt.subplots(figsize=(6.2, 3.1), dpi=200)
    left = [0.0] * len(arms)
    ys = range(len(arms) - 1, -1, -1)
    for key, label, color in parts:
        vals = [att[a][key] for a in arms]
        ax.barh(list(ys), vals, left=left, color=color, label=label, height=0.62)
        for y, l, v in zip(ys, left, vals):
            if v >= 0.06:
                ax.text(l + v / 2, y, f"{v:.0%}", ha="center", va="center", fontsize=7, color=INK)
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(list(ys), [LABEL[a] for a in arms])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_xlabel("Share of value cells (all repeats), by semantic grade")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, 1.2), ncol=2, fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "fig_error_attribution.png")
    plt.close(fig)


def fig_invented(inv, arms):
    fields = inv["fields"]
    colors = {K5: ORANGE, K20: RED, NULLP: VIOLET}
    fig, ax = plt.subplots(figsize=(6.2, 3.3), dpi=200)
    height = 0.26
    for i, a in enumerate(arms):
        ys = [len(fields) - 1 - j + (1 - i) * height for j in range(len(fields))]
        ax.barh(ys, [f["rate"].get(a, 0) for f in fields], height, color=colors[a], label=LABEL[a])
    ax.set_yticks([len(fields) - 1 - j for j in range(len(fields))], [f"{f['field']} ({f['cells']})" for f in fields], fontsize=7.5)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_xlabel("Invented-value rate on absent labels (cells per repeat in brackets)")
    ax.legend(loc="lower right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(OUT / "fig_invented_by_field.png")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    nums = {"arms": {}}
    for arm, rows in ((CURRENT, E1), (RBASE, E1), (K5, E6), (K10, E6), (K20, E6), (RR, E6), (NULLP, E8)):
        nums["arms"][arm] = arm_numbers(rows, arm) | {"label": LABEL[arm]}
    d6 = {}
    for m in ("semantic", "score", "exact", "lenient"):
        d6[m] = diffs(E6, K5, m)
        d6[m + "_high"] = diffs(E6, K5, m, where=HIGH)
    d6["invented"] = diffs(E6, K5, "invented", labels="absent")
    d6["invented_high"] = diffs(E6, K5, "invented", labels="absent", where=HIGH)
    d6["k10_vs_k20_semantic"] = diffs([r for r in E6 if r["pipeline"] in (K10, K20)], K20, "semantic")[K10]
    d8 = {}
    for m in ("semantic", "score", "exact", "lenient"):
        d8[m] = diffs(E8, K5, m)
        d8[m + "_high"] = diffs(E8, K5, m, where=HIGH)
    d8["invented"] = diffs(E8, K5, "invented", labels="absent")
    d8["invented_high"] = diffs(E8, K5, "invented", labels="absent", where=HIGH)
    d1 = {}
    for m in ("semantic", "score", "exact"):
        d1[m] = diffs(E1, CURRENT, m)[RBASE]
        d1[m + "_high"] = diffs(E1, CURRENT, m, where=HIGH)[RBASE]
    d1["invented"] = diffs(E1, CURRENT, "invented", labels="absent")[RBASE]
    nums |= {"e1_diff": d1, "e6_diff": d6, "e8_diff": d8, "retrieval": retrieval_numbers(),
             "attribution": {a: attribution(rows, a) for a, rows in ((CURRENT, E1), (RBASE, E1), (K5, E6), (K10, E6),
                                                                      (K20, E6), (RR, E6), (NULLP, E8))},
             "invented_by_field": invented_by_field(E6 + [r for r in E8 if r["pipeline"] == NULLP], [K5, K20, NULLP]),
             "copied_example": copied_example(E6 + [r for r in E8 if r["pipeline"] == NULLP]), "cost_log": cost_log(), "grader": grader()}
    forest = {k: {**d6[k], NULLP: d8[k][NULLP]} for k in ("semantic", "score", "exact", "invented",
                                                          "semantic_high", "score_high", "exact_high", "invented_high")}
    fig_recall_vs_k(nums["retrieval"])
    fig_e1(nums["arms"])
    fig_context(nums["arms"])
    fig_forest(forest)
    fig_cost(nums["arms"])
    fig_attribution(nums["attribution"])
    fig_invented(nums["invented_by_field"], [K5, K20, NULLP])
    (OUT / "numbers.json").write_text(json.dumps(nums, indent=1, default=float))
    old = OUT / "fig_e6_end_to_end.png"
    if old.exists():
        old.unlink()
    a = nums["arms"]
    print("check:", {x: (round(a[x]["semantic"], 3), round(a[x]["score"], 3), round(a[x]["invented"], 4), a[x]["recall"]) for x in a})
    print("e6 semantic diffs:", {k: (round(v["diff"], 3), round(v["lo"], 3), round(v["hi"], 3)) for k, v in d6["semantic"].items()})
    print("e8 semantic:", {k: (round(v["diff"], 3), round(v["lo"], 3), round(v["hi"], 3)) for k, v in d8["semantic"].items()})
    print("grader:", nums["grader"])
    print("cost:", nums["cost_log"])
    print("copied:", nums["copied_example"])
