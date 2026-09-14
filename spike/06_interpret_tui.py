"""判讀層 + CLI 輸出樣式原型（PROTOTYPE，拋棄式）。

跑法：
    python spike/06_interpret_tui.py

驗證的問題見 06_interpret_logic.py 開頭的說明。這支檔案只是包在邏輯外面的
互動殼，本身不該被移進正式程式——驗證完之後，`twec/interpret.py` 該長怎樣
由 06_interpret_logic.py 決定，CLI 輸出格式由這支檔案跑起來的觀感決定。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spike"))

from importlib import import_module

logic = import_module("06_interpret_logic")  # 檔名數字開頭，不能用 import 語法

from twec.roster import count_orgs  # noqa: E402

LAW_TABLE_PATH = ROOT / "data" / "勞基法白話對照表.xlsx"
RAW_CSV_PATH = ROOT / "data" / "lsa_violations_raw.csv"

SEVERITY_DOT = {1: "●", 2: "●●", 3: "●●●", 4: "●●●●", 5: "●●●●●"}


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render_candidates(query: str, candidates: list[tuple[str, int]]) -> None:
    print(f"搜尋關鍵字：{query or '（空＝顯示裁處最多的前 20 家）'}")
    print("-" * 60)
    if not candidates:
        print("（沒有符合的雇主）")
    for i, (org, count) in enumerate(candidates, start=1):
        print(f"  [{i:>2}] {org}　（{count} 列）")
    print("-" * 60)


def render_report(report) -> None:
    print("=" * 60)
    print(f"雇主：{report.org}　（裁處列數：{report.total_rows}）")
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
            sev = item.severity_source  # 本身已經是「未評級（原因）」，不用再包一層
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
    print("判讀層原型 —— 輸入關鍵字搜尋雇主，輸入編號查看判讀結果\n")
    render_candidates(state["query"], state["candidates"])
    if state["report"] is not None:
        print()
        render_report(state["report"])
    print("\n[打關鍵字] 搜尋　[數字] 選雇主　[q] 離開")


def main() -> None:
    if not RAW_CSV_PATH.exists():
        sys.exit(f"找不到 {RAW_CSV_PATH}，請先依 README 下載原始資料。")
    if not LAW_TABLE_PATH.exists():
        sys.exit(f"找不到 {LAW_TABLE_PATH}，請先跑 scripts/build_law_workbook.py。")

    print("載入中……（讀全量違規名單 + 白話對照表）")
    all_orgs = count_orgs(RAW_CSV_PATH)  # org -> 裁處列數
    law_table = logic.load_law_table(LAW_TABLE_PATH)
    buckets = logic.build_severity_buckets(law_table)

    state = {
        "query": "",
        "candidates": sorted(all_orgs.items(), key=lambda kv: -kv[1])[:20],
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
                org = state["candidates"][i][0]
                state["report"] = logic.interpret_org(org, RAW_CSV_PATH, law_table, buckets)
        elif line:
            state["query"] = line
            state["candidates"] = [
                (org, n) for org, n in sorted(all_orgs.items(), key=lambda kv: -kv[1])
                if line in org
            ][:20]
            state["report"] = None
        # 空白輸入：什麼都不做，重render目前畫面


if __name__ == "__main__":
    main()
