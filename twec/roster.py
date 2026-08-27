"""歸戶：把違規名單裡的名稱收斂成「一個雇主一列」。

`twec.names` 產出的 `org` 是地基，但字串當 key 有兩個治不好的毛病：
法人改名會把歷史切成兩半，分公司與母公司對不起來。`twec.uniform_no`
把統編補上之後，這裡才是真正把統編用進歸戶的地方。

合併規則只有一條，而且刻意保守：

    只有 `high_confidence` 的統編才拿來合併。

`sole_operating`（同名多統編、只剩一家營業中）取的是「現在還營業的那家」，
未必是裁處當時的那家。它的統編仍寫進 `uniform_no` 當加值欄位，但**不合併**——
分裂了還能靠別名表補，錯併就救不回來了。
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass

from twec.names import normalize, split_entity
from twec.uniform_no import Registry

# 勞動部八個違規資料集共用的欄位名。
NAME_COLUMN = "事業單位名稱或負責人"


def count_orgs(source: str | os.PathLike[str]) -> Counter[str]:
    """讀違規名單，回傳 org -> 裁處列數。

    歸戶主流程的入口：正規化與拆解都在這裡發生，之後下游看到的一律是 org。
    """
    counts: Counter[str] = Counter()
    with open(source, encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            raw = row.get(NAME_COLUMN) or ""
            if raw.strip():
                counts[split_entity(normalize(raw)).org] += 1
    return counts


@dataclass(frozen=True)
class Entity:
    """一個雇主。

    key:
        歸戶用的身分。有可信統編時就是統編，否則是 org 名稱字串。
    key_kind:
        uniform_no / name，讓下游知道這一列的身分有多硬。
    uniform_no:
        統編。`key_kind` 是 name 時仍可能有值（低信心的 sole_operating）。
    names:
        歸到這個 key 底下的所有 org，依裁處次數多到少。
    """

    key: str
    key_kind: str
    uniform_no: str | None
    names: tuple[str, ...]
    count: int

    @property
    def display(self) -> str:
        """報告上顯示的名稱，取裁處次數最多的那個。"""
        return self.names[0]


class Roster:
    """歸戶結果。"""

    def __init__(self, entities: list[Entity]) -> None:
        self._entities = entities
        self._by_org = {name: e for e in entities for name in e.names}

    @property
    def entities(self) -> list[Entity]:
        return self._entities

    @property
    def renamed(self) -> list[Entity]:
        """靠統編併起來的雇主，也就是同一法人的不同名稱。

        統編白送的改名，是待辦第 7 項那個偵測器不必再處理的一半。
        """
        return [e for e in self._entities if len(e.names) > 1]

    def of(self, org: str) -> Entity:
        """查一個 org 歸到哪個雇主。"""
        return self._by_org[org]

    @classmethod
    def build(cls, counts: dict[str, int], registry: Registry) -> Roster:
        """輸入 org -> 裁處列數，輸出歸戶結果。

        分組的 key 帶著 key_kind，避免萬一有個 org 剛好長得像統編時撞在一起。
        """
        groups: dict[tuple[str, str], list[tuple[str, int]]] = {}
        hints: dict[tuple[str, str], str | None] = {}
        for org, count in counts.items():
            got = registry.resolve(org)
            if got.high_confidence:
                group = ("uniform_no", got.uniform_no)
            else:
                group = ("name", org)
            groups.setdefault(group, []).append((org, count))
            hints[group] = got.uniform_no

        entities = []
        for (kind, key), members in groups.items():
            # 名稱依裁處次數多到少，第一個就是報告上的代表名。
            # 次數相同時用字串排序定序，讓每次跑出來的結果一致。
            members.sort(key=lambda m: (-m[1], m[0]))
            entities.append(
                Entity(
                    key=key,
                    key_kind=kind,
                    uniform_no=hints[(kind, key)],
                    names=tuple(name for name, _ in members),
                    count=sum(n for _, n in members),
                )
            )
        entities.sort(key=lambda e: (-e.count, e.display))
        return cls(entities)
