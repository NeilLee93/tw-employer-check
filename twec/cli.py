"""命令列進入點（待辦第 9 項）：`twec search` 找雇主、`twec report` 看三法規分軌報告。

設計上刻意保守，只做已經定案的事：

    分軌：勞基法／勞退／職安三份 `InterpretedReport` 各自一個區塊，
    嚴重度各自用自己的罰鍰分位數（待辦第 8 項），**不跨法規加總**——
    勞退 97.6% 是未按月提繳的欠費滯納金，與勞基法等權相加會讓排名被
    欠費案件淹沒（交接文件第四個發現的硬規則）。彙總列只並列三個數字。

    不下結論：輸出一律稱「裁處紀錄」，行政救濟中的列標「尚未確定」，
    不逕稱該公司違法（已知資料坑第 7 點的硬規則）。

尚未做、等使用者決定的：「跨多部法規有紀錄 = 系統性問題」的旗標。
門檻（幾部法規、幾年內、勞退欠費算不算）是勞動法判斷，不是工程問題。

雇主名冊用 `data/roster.csv`（`scripts/build_roster.py` 的快取），不在
查詢時重讀 380 MB 稅籍資料。名冊只由勞基法資料建出，只出現在勞退／職安
的雇主查不到別名，此時退回「用輸入名稱正規化後逐字比對」。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from twec.interpret import (
    InterpretedReport,
    LawEntry,
    article_of,
    build_law_table_from_data,
    build_severity_buckets,
    interpret_entity,
    load_law_table,
    parse_lpa_violation_row,
    parse_osha_violation_row,
    parse_violation_row,
)
from twec.names import normalize, split_entity
from twec.roster import Entity

DATA_DIR = Path("data")
DEFAULT_ROSTER = DATA_DIR / "roster.csv"
DEFAULT_LAW_TABLE = DATA_DIR / "勞基法白話對照表.xlsx"
DEFAULT_LSA = DATA_DIR / "lsa_violations_raw.csv"
DEFAULT_LPA = DATA_DIR / "raw" / "lpa_勞工退休金條例.csv"
DEFAULT_OSHA = DATA_DIR / "raw" / "osha_職業安全衛生法.csv"

SEVERITY_DOT = {1: "●", 2: "●●", 3: "●●●", 4: "●●●●", 5: "●●●●●"}

DISCLAIMER = (
    "以下為主管機關公布之裁處紀錄。標「尚未確定」者仍在行政救濟中，"
    "不得逕認該雇主違法。"
)


# ---------------------------------------------------------------------------
# 名冊：讀取與查找
# ---------------------------------------------------------------------------


def load_roster(path: str | os.PathLike[str]) -> list[Entity]:
    """讀 `scripts/build_roster.py` 產出的 `data/roster.csv`，依裁處次數多到少。"""
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
    entities.sort(key=lambda e: (-e.count, e.display))
    return entities


def search(entities: list[Entity], query: str, limit: int = 20) -> list[Entity]:
    """任一別名含關鍵字（子字串）或統編完全相同就算命中。

    關鍵字也先做一次名稱正規化（臺→台、全形、空白），否則使用者打「臺灣」
    會找不到已經被正規化成「台灣」的名冊。
    """
    q = query.strip()
    if not q:
        return entities[:limit]
    nq = normalize(q)
    hits = [
        e for e in entities
        if e.uniform_no == q or any(q in n or (nq and nq in n) for n in e.names)
    ]
    return hits[:limit]


@dataclass(frozen=True)
class Resolved:
    """`resolve_target` 的結果：找到一個雇主，或列出候選要使用者再縮小。"""

    entity: Entity | None
    candidates: list[Entity]
    in_roster: bool


def resolve_target(entities: list[Entity], query: str) -> Resolved:
    """把使用者輸入對到一個雇主。順序由硬到軟，寧可要求縮小也不猜：

    1. 統編或 key 完全相同
    2. 正規化＋拆解後的 org 與某個別名完全相同
    3. 子字串只命中一家 → 就是它；命中多家 → 回傳候選，不挑
    4. 名冊完全沒有 → 用正規化後的 org 臨時建一個 Entity（只會逐字比對，
       不含任何別名），讓只出現在勞退／職安的雇主也查得到
    """
    q = query.strip()
    for e in entities:
        if q and (e.uniform_no == q or e.key == q):
            return Resolved(e, [], True)

    org = split_entity(normalize(q)).org
    for e in entities:
        if org in e.names:
            return Resolved(e, [], True)

    hits = search(entities, q, limit=len(entities))
    if len(hits) == 1:
        return Resolved(hits[0], [], True)
    if len(hits) > 1:
        return Resolved(None, hits, True)

    adhoc = Entity(key=org, key_kind="name", uniform_no=None, names=(org,), count=0)
    return Resolved(adhoc, [], False)


# ---------------------------------------------------------------------------
# 三條法規軌道
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Track:
    """一部法規的判讀設定。三部法規各自一份，嚴重度不共用。"""

    key: str
    label: str
    source: Path
    parse_row: Callable
    caveat: str | None = None
    law_table_xlsx: Path | None = None

    def load_law_table(self) -> dict[str, LawEntry]:
        """有人工白話對照表就用（目前只有勞基法），否則從原始 CSV 現算。"""
        if self.law_table_xlsx is not None and self.law_table_xlsx.exists():
            return load_law_table(self.law_table_xlsx)
        return build_law_table_from_data(self.source, parse_row=self.parse_row)


def default_tracks(
    lsa: Path = DEFAULT_LSA,
    lpa: Path = DEFAULT_LPA,
    osha: Path = DEFAULT_OSHA,
    law_table: Path = DEFAULT_LAW_TABLE,
) -> list[Track]:
    return [
        Track("lsa", "勞動基準法", Path(lsa), parse_violation_row, law_table_xlsx=Path(law_table)),
        Track(
            "lpa", "勞工退休金條例", Path(lpa), parse_lpa_violation_row,
            caveat="本法紀錄絕大多數為「未按月提繳退休金」的欠費與滯納金，"
                   "性質與勞基法裁罰不同，不與其他法規合併計算。",
        ),
        Track("osha", "職業安全衛生法", Path(osha), parse_osha_violation_row),
    ]


@dataclass(frozen=True)
class TrackResult:
    track: Track
    report: InterpretedReport | None
    skipped: str | None = None


def run_tracks(entity: Entity, tracks: list[Track]) -> list[TrackResult]:
    """每部法規各自建對照表、各自切嚴重度分位數、各自判讀。

    缺資料檔的法規只標「略過」，不讓整份報告失敗——使用者可能只下載了勞基法。
    """
    results = []
    for t in tracks:
        if not t.source.exists():
            results.append(TrackResult(t, None, f"找不到資料檔 {t.source}"))
            continue
        table = t.load_law_table()
        buckets = build_severity_buckets(table)
        report = interpret_entity(
            entity, t.source, table, buckets, parse_row=t.parse_row, get_article=article_of,
        )
        results.append(TrackResult(t, report))
    return results


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------


def render_candidates(entities: list[Entity]) -> str:
    if not entities:
        return "（沒有符合的雇主）"
    lines = []
    for i, e in enumerate(entities, start=1):
        uno = f"［{e.uniform_no}］" if e.uniform_no else ""
        alias = f"　別名：{'、'.join(e.names[1:])}" if len(e.names) > 1 else ""
        lines.append(f"{i:>3}. {e.display}{uno}（勞基法 {e.count} 列）{alias}")
    return "\n".join(lines)


def _render_track(result: TrackResult, limit: int) -> list[str]:
    t = result.track
    lines = [f"■ {t.label}"]
    if result.report is None:
        lines.append(f"  略過：{result.skipped}")
        return lines
    if t.caveat:
        lines.append(f"  說明：{t.caveat}")

    r = result.report
    if not r.items:
        lines.append("  查無裁處紀錄。")
        return lines

    lines.append(
        f"  {len(r.items)} 筆 / 涉及 {r.distinct_laws} 個法條 / "
        f"{r.disputed_count} 列尚未確定 / 本法最高嚴重度：{r.top_severity or '未評級'}"
    )
    if r.repeat_offenses:
        lines.append("  同一法條 2 次以上：")
        for law, n in sorted(r.repeat_offenses.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {law} × {n}")

    shown = r.items[:limit]
    lines.append(f"  最新 {len(shown)} / {len(r.items)} 筆：")
    for item in shown:
        if item.severity:
            sev = f"{SEVERITY_DOT.get(item.severity, str(item.severity))}（{item.severity_source}）"
        else:
            sev = item.severity_source
        status = "　⚠ 尚未確定（行政救濟中）" if item.disputed else ""
        fine = f"{item.fine:,} 元" if item.fine else "（無金額資料）"
        lines.append(f"    [{item.date}] {item.agency}｜{item.law}{status}")
        lines.append(f"      {item.text}（{item.text_source}）")
        lines.append(f"      嚴重度 {sev}　金額 {fine}")
        if item.note:
            lines.append(f"      備註：{item.note}")
    return lines


def render_report(entity: Entity, results: list[TrackResult], in_roster: bool, limit: int = 10) -> str:
    lines = [f"雇主：{entity.display}"]
    if entity.uniform_no:
        lines.append(f"統編：{entity.uniform_no}（{'可信' if entity.key_kind == 'uniform_no' else '低信心，僅供參考'}）")
    if len(entity.names) > 1:
        lines.append(f"別名：{'、'.join(entity.names[1:])}")
    if not in_roster:
        lines.append("（名冊中查無此雇主，以輸入名稱正規化後逐字比對，不含任何別名）")
    lines.append(DISCLAIMER)

    for result in results:
        lines.append("")
        lines.extend(_render_track(result, limit))

    # 彙總只並列，不加總：三部法規性質不同，嚴重度也各自分軌。
    lines.append("")
    lines.append("彙總（各法規分列，不加總）：")
    for result in results:
        if result.report is None:
            lines.append(f"  {result.track.label}：略過")
        else:
            lines.append(f"  {result.track.label}：{len(result.report.items)} 筆")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 進入點
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twec", description="查台灣雇主的勞動法裁處紀錄（勞基法／勞退／職安分軌判讀）",
    )
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER, help="雇主名冊（build_roster.py 產出）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="用關鍵字或統編找雇主")
    p_search.add_argument("query", help="名稱關鍵字（子字串）或統一編號")
    p_search.add_argument("--limit", type=int, default=20)

    p_report = sub.add_parser("report", help="看一個雇主的三法規分軌報告")
    p_report.add_argument("query", help="完整名稱、統一編號，或只命中一家的關鍵字")
    p_report.add_argument("--limit", type=int, default=10, help="每部法規顯示幾筆明細")
    p_report.add_argument("--lsa", type=Path, default=DEFAULT_LSA, help="勞基法 CSV")
    p_report.add_argument("--lpa", type=Path, default=DEFAULT_LPA, help="勞退 CSV")
    p_report.add_argument("--osha", type=Path, default=DEFAULT_OSHA, help="職安 CSV")
    p_report.add_argument("--law-table", type=Path, default=DEFAULT_LAW_TABLE, help="勞基法白話對照表")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 主控台預設編碼不是 UTF-8，中文會變亂碼或直接丟例外。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)

    if not args.roster.exists():
        print(f"找不到雇主名冊 {args.roster}，請先跑 python scripts/build_roster.py。", file=sys.stderr)
        return 1
    entities = load_roster(args.roster)

    if args.command == "search":
        print(render_candidates(search(entities, args.query, args.limit)))
        return 0

    resolved = resolve_target(entities, args.query)
    if resolved.entity is None:
        print(f"「{args.query}」命中 {len(resolved.candidates)} 家，請改用完整名稱或統編：", file=sys.stderr)
        print(render_candidates(resolved.candidates[:20]), file=sys.stderr)
        return 2

    tracks = default_tracks(args.lsa, args.lpa, args.osha, args.law_table)
    results = run_tracks(resolved.entity, tracks)
    print(render_report(resolved.entity, results, resolved.in_roster, args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
