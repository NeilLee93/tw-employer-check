"""跑改名候選偵測：殘餘（兩邊都沒可信統編）的雇主裡，找時間軸不重疊＋名稱相似的組。

執行：
    python scripts/build_rename_candidates.py

需要先能重建 Roster（見 build_roster.py 的說明：財政部稅籍三檔）。

產出 data/改名候選.csv：只是候選，不是結論。合不合併要人工查證
（統編白送的 202 組確定改名不在這裡，見 `roster.renamed`）。

效能備忘：殘餘約 1 萬個雇主，兩兩比對是 O(n^2)，全量約需 10 分鐘，
一次性批次工作，尚無需要優化到能常駐執行的地步。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twec.rename_candidates import date_ranges, find_candidates  # noqa: E402
from twec.roster import Roster, count_orgs  # noqa: E402
from twec.uniform_no import Registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_SOURCE = ROOT / "data" / "lsa_violations_raw.csv"
OUT = ROOT / "data" / "改名候選.csv"


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        sys.exit(f"找不到 {source}，請先依 README 下載原始資料。")

    print(f"讀違規名單 {source.name} …")
    orgs = count_orgs(source)
    ranges = date_ranges(source)

    print(f"讀稅籍名冊 {RAW_DIR} …")
    registry = Registry.from_dir(RAW_DIR)
    roster = Roster.build(orgs, registry)

    residual = sum(1 for e in roster.entities if e.key_kind == "name")
    print(f"殘餘（無可信統編）雇主：{residual:,} 個，開始兩兩比對，全量約需 10 分鐘 …")

    candidates = find_candidates(roster, ranges)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["舊名", "新名", "相似度", "舊名裁處次數", "新名裁處次數"])
        for c in candidates:
            writer.writerow([
                c.old.display,
                c.new.display,
                f"{c.similarity:.3f}",
                c.old.count,
                c.new.count,
            ])

    print(f"\n寫出 {OUT}：{len(candidates):,} 組候選（只是候選，不能自動合併）")


if __name__ == "__main__":
    main()
