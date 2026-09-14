"""改名候選偵測器：統編白送的 202 組改名已經算完，這裡抓殘餘那一半。

只吃 `Roster` 裡 `key_kind == "name"`（兩邊都沒有可信統編）的雇主。
訊號是「時間軸不重疊 + 名稱相似」，但這訊號不足以證明改名——
富利食品／富利餐飲時間軸接續無重疊、名稱高度相似，統編一查卻是兩家法人。
所以這裡只產生候選，不做任何合併，合不合併是勞動法或人工查證的事。

比對相似度前要先去掉公司型態字尾（股份有限公司…），否則「股份有限公司」
這種菜市場字尾會把毫不相干的公司配對在一起（見 `_core`）。
"""

from __future__ import annotations

import csv
import difflib
import os
from dataclasses import dataclass

from twec.names import normalize, split_entity
from twec.roster import Entity, Roster

NAME_COLUMN = "事業單位名稱或負責人"
DATE_COLUMN = "處分日期"

DateRange = tuple[str, str]

# 與 names.py 的公司型態關鍵字一致，只用來去掉字尾算比對用的核心字串。
_ORG_SUFFIX = (
    "股份有限公司",
    "有限公司",
    "無限公司",
    "兩合公司",
    "公司",
    "企業社",
    "工程行",
    "合作社",
    "事務所",
    "工作室",
    "商行",
    "商號",
    "農場",
    "牧場",
)


def _core(org: str) -> str:
    for suffix in _ORG_SUFFIX:
        if org.endswith(suffix):
            return org[: -len(suffix)] or org
    return org


def date_ranges(source: str | os.PathLike[str]) -> dict[str, DateRange]:
    """讀違規名單，回傳 org -> (最早處分日期, 最晚處分日期)。"""
    ranges: dict[str, DateRange] = {}
    with open(source, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row.get(NAME_COLUMN) or ""
            date = (row.get(DATE_COLUMN) or "").strip()
            if not raw.strip() or not date:
                continue
            org = split_entity(normalize(raw)).org
            lo, hi = ranges.get(org, (date, date))
            ranges[org] = (min(lo, date), max(hi, date))
    return ranges


def _overlaps(a: DateRange, b: DateRange) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1])


def _entity_range(entity: Entity, ranges: dict[str, DateRange]) -> DateRange | None:
    subs = [ranges[name] for name in entity.names if name in ranges]
    if not subs:
        return None
    return (min(lo for lo, _ in subs), max(hi for _, hi in subs))


@dataclass(frozen=True)
class RenameCandidate:
    """一組候選：`old` 時間軸較早，`new` 較晚。`similarity` 只是排序用的分數。"""

    old: Entity
    new: Entity
    similarity: float


def find_candidates(
    roster: Roster,
    ranges: dict[str, DateRange],
    threshold: float = 0.5,
) -> list[RenameCandidate]:
    """在沒有可信統編的雇主裡找改名候選，最相似的排最前面。"""
    residual = [
        (e, _entity_range(e, ranges))
        for e in roster.entities
        if e.key_kind == "name"
    ]
    dated = [(e, r) for e, r in residual if r is not None]

    candidates: list[RenameCandidate] = []
    for i, (e1, r1) in enumerate(dated):
        for e2, r2 in dated[i + 1 :]:
            if _overlaps(r1, r2):
                continue
            score = difflib.SequenceMatcher(
                None, _core(e1.display), _core(e2.display)
            ).ratio()
            if score < threshold:
                continue
            old, new = (e1, e2) if r1 < r2 else (e2, e1)
            candidates.append(RenameCandidate(old=old, new=new, similarity=score))

    candidates.sort(key=lambda c: -c.similarity)
    return candidates
