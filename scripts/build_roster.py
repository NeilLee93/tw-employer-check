"""跑完整條歸戶主流程：違規名單 → 名稱正規化 → 統編 → 一個雇主一列。

執行：
    python scripts/build_roster.py                  # 勞基法
    python scripts/build_roster.py data/raw/osha_職業安全衛生法.csv

需要 data/raw/ 底下有財政部稅籍三檔，下載方式見 README。

產出 data/roster.csv（不進版控，隨時可重生）：
    key, key_kind, uniform_no, 代表名稱, 名稱數, 裁處次數, 其他名稱
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twec.roster import Roster, count_orgs  # noqa: E402
from twec.uniform_no import Registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_SOURCE = ROOT / "data" / "lsa_violations_raw.csv"
OUT = ROOT / "data" / "roster.csv"


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        sys.exit(f"找不到 {source}，請先依 README 下載原始資料。")

    orgs = count_orgs(source)
    print(f"讀違規名單 {source.name}：{len(orgs):,} 個 org / {sum(orgs.values()):,} 列")

    print(f"讀稅籍名冊 {RAW_DIR} …")
    registry = Registry.from_dir(RAW_DIR)
    print(f"  {len(registry):,} 列 / {registry.distinct_names:,} 個不重複名稱")

    roster = Roster.build(orgs, registry)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["key", "key_kind", "uniform_no", "代表名稱", "名稱數", "裁處次數", "其他名稱"]
        )
        for e in roster.entities:
            writer.writerow([
                e.key,
                e.key_kind,
                e.uniform_no or "",
                e.display,
                len(e.names),
                e.count,
                ";".join(e.names[1:]),
            ])

    by_uniform_no = [e for e in roster.entities if e.key_kind == "uniform_no"]
    hinted = [e for e in roster.entities if e.key_kind == "name" and e.uniform_no]
    merged_names = sum(len(e.names) for e in roster.renamed)

    print(f"\n寫出 {OUT}")
    print("\n歸戶：")
    print(f"  org（名稱層）        {len(orgs):>7,}")
    print(f"  歸戶後雇主數         {len(roster.entities):>7,}")
    print(f"  再收斂              {len(orgs) - len(roster.entities):>7,} 個名稱")
    print("\nkey 的來源：")
    print(f"  統編（可信）         {len(by_uniform_no):>7,} ({len(by_uniform_no) / len(roster.entities):.1%})")
    print(f"  名稱字串             {len(roster.entities) - len(by_uniform_no):>7,}")
    print(f"    其中有低信心統編   {len(hinted):>7,}（只當加值欄位，不合併）")
    print(f"\n統編併起來的改名：{len(roster.renamed):,} 組，涵蓋 {merged_names:,} 個名稱")

    print("\n合併後裁處次數最多的 15 家：")
    for e in roster.entities[:15]:
        extra = f"  ← {'、'.join(e.names[1:])}" if len(e.names) > 1 else ""
        print(f"  {e.count:>5}  [{e.key_kind:<10}] {e.display}{extra}")

    print("\n併進最多名稱的 10 組：")
    for e in sorted(roster.renamed, key=lambda x: -len(x.names))[:10]:
        print(f"  {e.uniform_no}  {e.count:>4} 次  {'、'.join(e.names)}")


if __name__ == "__main__":
    main()
