"""互動式查詢：輸入雇主名稱關鍵字，看判讀後的違規報告。

用 `data/roster.csv`（`build_roster.py` 的快取，含統編合併結果）當雇主名冊，
不必每次重讀 380 MB 的財政部稅籍資料，啟動只要幾秒。

執行：
    python scripts/search_employer.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twec.interpret import build_severity_buckets, load_law_table, interpret_entity  # noqa: E402
from twec.roster import Entity  # noqa: E402

ROSTER_PATH = ROOT / "data" / "roster.csv"
LAW_TABLE_PATH = ROOT / "data" / "勞基法白話對照表.xlsx"
RAW_CSV_PATH = ROOT / "data" / "lsa_violations_raw.csv"

SEVERITY_DOT = {1: "●", 2: "●●", 3: "●●●", 4: "●●●●", 5: "●●●●●"}


def load_roster(path: Path) -> list[Entity]:
    entities = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            others = [n for n in row["其他名稱"].split(";") if n]
            entities.append(
                Entity(
                    key=row["key"],
                    key_kind=row["key_kind"],
                    uniform_no=row["uniform_no"] or None,
                    names=(row["代表名稱"], *others),
                    count=int(row["裁處次數"]),
                )
            )
    return entities


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render_candidates(query: str, candidates: list[Entity]) -> None:
    print(f"搜尋關鍵字：{query or '（空＝顯示裁處最多的前 20 家）'}")
    print("-" * 60)
    if not candidates:
        print("（沒有符合的雇主）")
    for i, e in enumerate(candidates, start=1):
        alias = f"　（別名：{'、'.join(e.names[1:])}）" if len(e.names) > 1 else ""
        print(f"  [{i:>2}] {e.display}（{e.count} 列){alias}")
    print("-" * 60)


def render_report(report) -> None:
    print("=" * 60)
    print(f"雇主：{report.entity.display}　（裁處列數：{report.entity.count}）")
    if len(report.entity.names) > 1:
        print(f"別名：{'、'.join(report.entity.names[1:])}")
    print("=" * 60)

    if report.repeat_offenses:
        print("\n⚠ 累犯（同一法條 2 次以上）：")
        for law, n in sorted(report.repeat_offenses.items(), key=lambda kv: -kv[1]):
            print(f"    {law} × {n}")

    print(f"\n裁處明細（最新 {min(10, len(report.items))} / {len(report.items)} 筆）：")
    for item in report.items[:10]:
        if item.severity:
            sev = f"{SEVERITY_DOT.get(item.severity, str(item.severity))}（{item.severity_source}）"
        else:
            sev = item.severity_source
        dispute = "　⚠ 尚未確定" if item.disputed else ""
        fine = f"{item.fine:,} 元" if item.fine else "（無罰鍰資料）"
        print(f"\n  [{item.date}] {item.agency} | {item.law}{dispute}")
        print(f"    → {item.text}（{item.text_source}）")
        print(f"    嚴重度 {sev}　罰鍰 {fine}")
        if item.note:
            print(f"    備註：{item.note}")

    print("\n" + "-" * 60)
    print(
        f"彙總：{len(report.items)} 筆違規 / 涉及 {report.distinct_laws} 個法條 / "
        f"{report.disputed_count} 筆行政救濟中　最高嚴重度：{report.top_severity or '未評級'}"
    )
    print("-" * 60)


def render(state: dict) -> None:
    clear()
    print("雇主查詢 —— 輸入關鍵字搜尋，輸入編號看判讀結果\n")
    render_candidates(state["query"], state["candidates"])
    if state["report"] is not None:
        print()
        render_report(state["report"])
    print("\n[打關鍵字] 搜尋　[數字] 選雇主　[q] 離開")


def main() -> None:
    for path, hint in [
        (ROSTER_PATH, "先跑 python scripts/build_roster.py"),
        (LAW_TABLE_PATH, "先跑 python scripts/build_law_workbook.py"),
        (RAW_CSV_PATH, "請先依 README 下載原始資料"),
    ]:
        if not path.exists():
            sys.exit(f"找不到 {path}，{hint}。")

    print("載入中……")
    all_entities = load_roster(ROSTER_PATH)
    law_table = load_law_table(LAW_TABLE_PATH)
    buckets = build_severity_buckets(law_table)

    state = {
        "query": "",
        "candidates": sorted(all_entities, key=lambda e: -e.count)[:20],
        "report": None,
    }

    while True:
        render(state)
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line.lower() in ("q", "quit", "exit"):
            break
        elif line.isdigit():
            i = int(line) - 1
            if 0 <= i < len(state["candidates"]):
                entity = state["candidates"][i]
                state["report"] = interpret_entity(entity, RAW_CSV_PATH, law_table, buckets)
        elif line:
            state["query"] = line
            state["candidates"] = [
                e for e in sorted(all_entities, key=lambda e: -e.count)
                if any(line in name for name in e.names)
            ][:20]
            state["report"] = None

    print("再見。")


if __name__ == "__main__":
    main()
