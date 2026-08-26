"""替違規名單裡的每個 org 補統一編號，產出對照表並印出驗收數字。

執行：
    python scripts/build_uniform_no.py                  # 勞基法
    python scripts/build_uniform_no.py data/raw/osha_職業安全衛生法.csv

需要 data/raw/ 底下有財政部稅籍三檔，下載方式見 README。

產出 data/uniform_no_map.csv（不進版控，隨時可重生）：
    org, uniform_no, method, high_confidence, org_type, status, hq_no, candidates, 裁處次數
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twec.names import normalize, split_entity  # noqa: E402
from twec.uniform_no import Registry, Resolution  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_SOURCE = ROOT / "data" / "lsa_violations_raw.csv"
OUT = ROOT / "data" / "uniform_no_map.csv"
COL = "事業單位名稱或負責人"


def count_orgs(source: Path) -> Counter[str]:
    """讀違規資料，回傳 org -> 裁處列數。"""
    counts: Counter[str] = Counter()
    with open(source, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row.get(COL) or ""
            if raw:
                counts[split_entity(normalize(raw)).org] += 1
    return counts


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        sys.exit(f"找不到 {source}，請先依 README 下載原始資料。")

    print(f"讀稅籍名冊 {RAW_DIR} …")
    registry = Registry.from_dir(RAW_DIR)
    print(f"  {len(registry):,} 列 / {registry.distinct_names:,} 個不重複名稱")

    orgs = count_orgs(source)
    total_orgs = len(orgs)
    total_rows = sum(orgs.values())
    print(f"讀違規名單 {source.name}：{total_orgs:,} 家 / {total_rows:,} 列")

    by_method: Counter[str] = Counter()
    rows_by_method: Counter[str] = Counter()
    unresolved: list[tuple[int, str, str]] = []

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "org", "uniform_no", "method", "high_confidence",
            "org_type", "status", "hq_no", "candidates", "裁處次數",
        ])
        for org, count in orgs.most_common():
            got = registry.resolve(org)
            by_method[got.method] += 1
            rows_by_method[got.method] += count
            first = got.candidates[0] if got.candidates else None
            writer.writerow([
                org,
                got.uniform_no or "",
                got.method,
                "Y" if got.high_confidence else "N",
                first.org_type if first else "",
                first.status if first else "",
                first.hq_no if first else "",
                ";".join(dict.fromkeys(c.uniform_no for c in got.candidates)) if not got.resolved else "",
                count,
            ])
            if not got.resolved:
                unresolved.append((count, org, got.method))

    high = Resolution.HIGH_CONFIDENCE_METHODS
    high_orgs = sum(by_method[m] for m in high)
    high_rows = sum(rows_by_method[m] for m in high)
    all_orgs = high_orgs + by_method["sole_operating"]
    all_rows = high_rows + rows_by_method["sole_operating"]

    print(f"\n寫出 {OUT}")
    print(f"\n名稱層 {total_orgs:,} 家：")
    print(f"  比對出統編      {high_orgs:>7,} ({high_orgs / total_orgs:.1%})")
    print(f"  含唯一營業中挑選 {all_orgs:>7,} ({all_orgs / total_orgs:.1%})")
    print(f"裁處列 {total_rows:,} 列：")
    print(f"  比對出統編      {high_rows:>7,} ({high_rows / total_rows:.1%})")
    print(f"  含唯一營業中挑選 {all_rows:>7,} ({all_rows / total_rows:.1%})")

    print("\n各方法（家數 / 裁處列數）：")
    for method, n in by_method.most_common():
        mark = " " if method in high else ("~" if method == "sole_operating" else "✗")
        print(f"  {mark} {method:<18} {n:>7,}  {rows_by_method[method]:>8,}")

    print("\n未取得統編、裁處次數最多的 20 家：")
    for count, org, method in sorted(unresolved, reverse=True)[:20]:
        print(f"  {count:>4}  [{method}] {org}")


if __name__ == "__main__":
    main()
