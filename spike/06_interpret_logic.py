"""判讀層邏輯原型（PROTOTYPE，拋棄式）。

**已驗證並移進正式模組 `twec/interpret.py`（2026-09-14），這支檔案保留當原始出處，不再維護。**
正式版差異：`interpret_org(org: str, ...)` 換成 `interpret_entity(entity: Entity, ...)`，
吃 `twec.roster.Entity.names`（該雇主所有別名）而不是單一 org 字串。
行為規格見 `tests/test_interpret.py`。

要驗證的設計問題：
    org 查詢 → 拿到違規紀錄 → 套用白話/嚴重度 → 輸出，這個資料流合不合理？

背景決定（2026-09-14 確認，見交接文件待辦第 4 項）：
    - 白話說明缺空時，fallback 用**這一列自己的官方描述文字**（已經半白話，
      比套用表格裡「這條底下最常見的那句」更貼近這一列的真實情況，不失真）。
    - 嚴重度：表格若人工填了就用人工的；沒填就用罰鍰**平均**在「已知罰鍰的條項」
      裡的相對位置切五級（分位數）。完全沒有罰鍰資料的條項（例：只出現 1 次、
      2020 年前的資料）標「未評級」，不硬猜。
      （原型第一版試過用中位數，40 條項裡 27 條中位數都卡在法定最低罰鍰
      20,000，分不出高下；改用平均後，累犯/加重情節個案會把平均拖高，
      才有鑑別力——見 build_severity_buckets 的說明。）
    - 表格只涵蓋前 8 條（87% 引用量）。不在表格裡的法條：沿用官方描述，
      嚴重度標「未評級（不在表格範圍）」，不假裝有判讀。
    - 歸戶（統編合併）在此原型故意先跳過：直接用 twec.names 拆出的 org 字串
      找違規列，不套 twec.roster / twec.uniform_no。理由是這裡要驗證的是
      判讀邏輯本身，混進歸戶會讓一次只測一件事變成同時測兩件事。
      驗證過的邏輯要移進正式模組時，呼叫方應改用 Roster 查出的 Entity.names
      去撈所有別名的違規列，而不是單一 org 字串。

這支檔案只放**純邏輯**：資料型別、解析、判讀規則。沒有任何 print / input，
好讓 06_interpret_tui.py 之外也能直接單元測試或重用。
"""

from __future__ import annotations

import bisect
import csv
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

NAME_COLUMN = "事業單位名稱或負責人"
DISPUTED_MARKERS = ("行政救濟", "訴願", "撤銷")


def clean(s: str | None) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def clean_text(s: str | None) -> str:
    return clean(s).rstrip("。.、,;；:：")


def normalize_law(raw: str) -> str:
    s = clean(raw).replace("勞基法", "勞動基準法")
    s = re.sub(r"(勞動基準法)+", "勞動基準法", s)
    if s != "勞動基準法":
        s = re.sub(r"勞動基準法$", "", s)
    return s


def article_of(law: str) -> int | None:
    m = re.match(r"^勞動基準法第(\d+)條", law)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class LawEntry:
    """法條白話對照表「條項層」的一列，用 `法條` 字串當 key。"""

    law: str
    topic: str
    plain: str | None  # 人工白話說明，可能沒填
    manual_severity: int | None  # 人工嚴重度 1-5，可能沒填
    fine_median: float | None
    fine_mean: float | None
    official_text: str  # 表上「最常見的官方描述」，只在整列 plain fallback 找不到列自身文字時用


@dataclass(frozen=True)
class InterpretedItem:
    """一列違規裁處，套用白話與嚴重度之後的樣子。"""

    date: str
    agency: str
    case_no: str
    law: str
    article: int | None
    text: str  # 實際顯示的白話/官方描述
    text_source: str  # "人工白話" / "官方描述（原始文字，尚無白話）"
    severity: int | None
    severity_source: str  # "人工" / "罰鍰中位數推算" / "未評級（不在表格範圍）" / "未評級（無罰鍰資料）"
    fine: int | None
    disputed: bool  # 備註含「行政救濟中」「訴願」等，裁處未確定
    note: str


@dataclass
class InterpretedReport:
    org: str
    total_rows: int
    items: list[InterpretedItem]
    repeat_offenses: dict[str, int] = field(default_factory=dict)  # law -> 次數，只留 >1
    disputed_count: int = 0

    @property
    def top_severity(self) -> int | None:
        graded = [i.severity for i in self.items if i.severity is not None]
        return max(graded) if graded else None

    @property
    def distinct_laws(self) -> int:
        return len({i.law for i in self.items})


def load_law_table(xlsx_path: str | Path) -> dict[str, LawEntry]:
    """讀「條項層（必填）」分頁，回傳 法條 -> LawEntry。"""
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb["條項層（必填）"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    table: dict[str, LawEntry] = {}
    for r in rows[1:]:
        law = r[idx["法條"]]
        if not law:
            continue
        table[law] = LawEntry(
            law=law,
            topic=r[idx["主題"]] or "",
            plain=r[idx["白話說明（一句話）"]] or None,
            manual_severity=r[idx["嚴重度"]] or None,
            fine_median=r[idx["罰鍰中位數"]],
            fine_mean=r[idx["罰鍰平均"]],
            official_text=r[idx["最常見的官方描述"]] or "",
        )
    return table


def build_severity_buckets(table: dict[str, LawEntry]) -> list[float]:
    """用表格裡「有罰鍰平均」的條項，切出五級分位數邊界（4 條分界線）。

    原型第一版用「罰鍰中位數」切分位數，實測失敗：40 條項裡 27 條的中位數
    剛好都卡在法定最低罰鍰 20,000（多數個案沒有加重情節，法院/主管機關
    就判最低），quantiles 幾乎全部撞在同一個值上，27 條裡有 26 條會被
    分到同一級，中位數對這批資料沒有鑑別力。

    改用「罰鍰平均」：同樣以 20,000 為主體，但只要條項底下有累犯／加重
    情節的個案把平均拉高（例：第 32 條第 1 項平均 201,768，中位數卻同樣是
    50,000），平均就會被拖高，恰好是嚴重度想抓的信號——不是「一般情況多
    重」，是「這條底下最壞能壞到多重」。人工沒填嚴重度時，用這個當客觀錨點。
    """
    means = sorted(e.fine_mean for e in table.values() if e.fine_mean)
    if len(means) < 5:
        return []
    return statistics.quantiles(means, n=5)


def severity_from_fine(fine_mean: float, buckets: list[float]) -> int:
    """罰鍰平均落在分位數第幾段，就是嚴重度 1-5（段數低＝罰得輕＝分數低）。"""
    return bisect.bisect_right(buckets, fine_mean) + 1


def resolve_severity(entry: LawEntry | None, buckets: list[float]) -> tuple[int | None, str]:
    if entry is None:
        return None, "未評級（不在表格範圍）"
    if entry.manual_severity is not None:
        return entry.manual_severity, "人工"
    if entry.fine_mean and buckets:
        return severity_from_fine(entry.fine_mean, buckets), "罰鍰平均推算"
    return None, "未評級（無罰鍰資料）"


def resolve_text(entry: LawEntry | None, row_text: str) -> tuple[str, str]:
    """白話 fallback 順序：人工白話 → 這一列自己的官方描述文字（不是表格裡「最常見」那句）。"""
    if entry is not None and entry.plain:
        return entry.plain, "人工白話"
    return row_text, "官方描述（原始文字，尚無白話）"


def parse_violation_row(row: dict[str, str]) -> list[tuple[str, str, int | None]] | None:
    """一列違規 CSV 展開成 [(法條, 官方描述, 罰鍰)]。數量對不上回傳 None（整列跳過，不猜）。"""
    laws = (row.get("違法法規法條") or "").split(";")
    texts = (row.get("違反法規內容") or "").split(";")
    if len(laws) != len(texts):
        return None
    fine = (row.get("罰鍰金額") or "").strip()
    fine_value = int(fine) if fine.isdigit() else None
    out = []
    for law, text in zip(laws, texts):
        law = normalize_law(law)
        if law:
            out.append((law, clean_text(text), fine_value))
    return out


def interpret_org(
    org: str,
    raw_csv_path: str | Path,
    law_table: dict[str, LawEntry],
    buckets: list[float],
) -> InterpretedReport:
    """查一個 org 在違規名單裡的所有列，套用白話與嚴重度。

    原型限定：org 必須是 twec.names.split_entity 拆出的字串（不經統編歸戶）。
    """
    from twec.names import normalize as norm_name
    from twec.names import split_entity

    items: list[InterpretedItem] = []
    law_counter: dict[str, int] = {}
    disputed = 0

    with open(raw_csv_path, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            raw_name = row.get(NAME_COLUMN) or ""
            if not raw_name.strip():
                continue
            if split_entity(norm_name(raw_name)).org != org:
                continue

            parsed = parse_violation_row(row)
            if parsed is None:
                continue

            note = (row.get("備註說明") or "").strip()
            is_disputed = any(m in note for m in DISPUTED_MARKERS)
            if is_disputed:
                disputed += 1

            for law, text, fine in parsed:
                entry = law_table.get(law)
                display_text, text_source = resolve_text(entry, text)
                severity, severity_source = resolve_severity(entry, buckets)
                law_counter[law] = law_counter.get(law, 0) + 1
                items.append(
                    InterpretedItem(
                        date=row.get("處分日期") or "",
                        agency=row.get("主管機關") or "",
                        case_no=row.get("處分字號") or "",
                        law=law,
                        article=article_of(law),
                        text=display_text,
                        text_source=text_source,
                        severity=severity,
                        severity_source=severity_source,
                        fine=fine,
                        disputed=is_disputed,
                        note=note,
                    )
                )

    items.sort(key=lambda i: i.date, reverse=True)
    repeat = {law: n for law, n in law_counter.items() if n > 1}
    return InterpretedReport(
        org=org,
        total_rows=len({(i.date, i.case_no) for i in items}) or len(items),
        items=items,
        repeat_offenses=repeat,
        disputed_count=disputed,
    )
