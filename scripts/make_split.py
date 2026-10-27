"""Dev/test split of the labelled contracts, by contract, stratified by contract type and spread over source formats.

    python3 scripts/make_split.py            # writes test_data/splits.json (deterministic: same labels, same split)

Every experiment tunes on `dev` only; `test` is run once, at the end. Each type (the label file's folder) gets
round(DEV_SHARE × its contracts) dev contracts, at least one, chosen in a seeded order that prefers a format the
type's dev contracts don't have yet. Tag them for experiments with:

    uv run contract-extraction documents tag dev $(jq -r '.dev[]' ../test_data/splits.json | sed 's|^|../|')
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_SHARE = 0.28  # ≈ 40 of 144
SEED = 2026


def main() -> None:
    by_type: dict[str, list[str]] = defaultdict(list)
    for label in sorted((ROOT / "test_data" / "labels").glob("*/*.json")):
        by_type[label.parent.name].append(json.loads(label.read_text(encoding="utf-8"))["file"])
    rng = random.Random(SEED)
    dev, test = [], []
    for kind in sorted(by_type):
        files = sorted(by_type[kind])
        rng.shuffle(files)
        n = max(1, round(DEV_SHARE * len(files)))
        chosen: list[str] = []
        while len(chosen) < n:
            formats = Counter(Path(f).suffix for f in chosen)
            chosen.append(min((f for f in files if f not in chosen), key=lambda f: formats[Path(f).suffix]))
        dev += sorted(chosen)
        test += sorted(f for f in files if f not in chosen)
    out = ROOT / "test_data" / "splits.json"
    out.write_text(json.dumps({"seed": SEED, "dev_share": DEV_SHARE, "dev": dev, "test": test}, indent=2) + "\n",
                   encoding="utf-8")
    fmt = lambda fs: dict(sorted(Counter(Path(f).suffix for f in fs).items()))  # noqa: E731
    print(f"wrote {out.relative_to(ROOT)}: dev {len(dev)} {fmt(dev)}, test {len(test)} {fmt(test)}")


if __name__ == "__main__":
    main()
