"""用財政部營業（稅籍）登記資料替事業單位名稱補上統一編號。

勞動部的違規資料集沒有統編欄位，`twec.names` 產出的 `org` 是唯一的
join key。字串當 key 有兩個治不好的毛病：法人改名會把歷史切斷，
分公司與母公司對不起來。統編兩個都能解。

資料源是財政部財政資訊中心「全國營業(稅籍)登記資料集」三個檔：

    BGMOPEN1.csv   營業中      約 171 萬列
    BGMOPEN1X.csv  停業        約 12 萬列
    BGMOPEN1Y.csv  非營業中    約 206 萬列（歇業、註銷、撤銷）

三個檔都有 `總機構統一編號` 欄位，分公司靠它指回母公司——這比名稱
字串規則可靠得多，是選這個資料源而不是經濟部 GCIS API 的主因
（GCIS 只有逐筆 API，沒有全量下載，且不含商號與財團法人）。

保守原則與 `twec.names` 一致：**分不出來就不給統編**。
同名多統編、前綴命中但總機構不一致的，一律回 `uniform_no=None`
並把候選放進 `candidates`，讓下游自己決定要不要人工判讀。
"""

from __future__ import annotations

import bisect
import csv
import os
from dataclasses import dataclass, field

from twec.names import normalize

# 三個稅籍檔與它們代表的營業狀態。順序即優先序：同一個名稱在多個檔案
# 裡出現時，營業中的那筆才是現在的雇主。
REGISTRY_FILES = (
    ("fia_BGMOPEN1.csv", "營業中"),
    ("fia_BGMOPEN1X.csv", "停業"),
    ("fia_BGMOPEN1Y.csv", "非營業中"),
)

_STATUS_RANK = {"營業中": 0, "停業": 1, "非營業中": 2}

# 違規資料裡的法人全名帶這些前綴，稅籍登記的名稱常常沒有。
# 例：「財團法人元智大學」在稅籍是「元智大學」。
_JURIDICAL_PREFIXES = (
    "醫療財團法人",
    "學校財團法人",
    "財團法人",
    "社團法人",
)


@dataclass(frozen=True)
class Registration:
    """稅籍檔的一列。"""

    name: str
    uniform_no: str
    org_type: str  # 組織別名稱：獨資／合夥／有限公司／外國公司在台之分公司…
    status: str  # 營業中／停業／非營業中
    hq_no: str  # 總機構統一編號，分公司才有


@dataclass(frozen=True)
class Resolution:
    """一次查詢的結果。

    `uniform_no` 是 None 就代表**不要用**——不是查不到就是分不出來，
    兩種都不該讓下游硬湊。要知道是哪一種看 `method`。

    method:
        exact              名稱完全相同
        strip_juridical    去掉「財團法人」這類前綴後完全相同
        natural_person     「王小明即某某商行」取「即」之後完全相同
        hq_via_prefix      前綴命中一群分公司，它們的總機構統編一致
        prefix_single      前綴命中且只有一個統編（多為外商在台分公司）
        sole_operating     名稱對到多個統編，但只有一個還在營業中
        ambiguous_name     名稱完全相同但對到多個統編，且不只一個在營業中
        ambiguous_prefix   前綴命中但統編不一致
        miss               查無

    `sole_operating` 是唯一一條「有取捨」的路徑：同名的舊統編都已歇業，
    只剩一個營業中。對連鎖總部改組（萊爾富、全家、國泰人壽）完全正確，
    對自然人商號則是「現在的那家」而未必是「裁處當時的那家」。
    要嚴格就只收 `high_confidence` 的結果。
    """

    HIGH_CONFIDENCE_METHODS = (
        "exact",
        "strip_juridical",
        "natural_person",
        "hq_via_prefix",
        "prefix_single",
    )

    uniform_no: str | None
    method: str
    candidates: tuple[Registration, ...] = field(default=())

    @property
    def resolved(self) -> bool:
        return self.uniform_no is not None

    @property
    def high_confidence(self) -> bool:
        """統編是比對出來的，不是從候選裡挑的。"""
        return self.method in self.HIGH_CONFIDENCE_METHODS


class Registry:
    """稅籍名冊。建構成本高（約 390 萬列），一個 process 建一次就好。"""

    def __init__(self, records: list[Registration]) -> None:
        self._records = sorted(records, key=lambda r: r.name)
        self._names = [r.name for r in self._records]
        self._exact: dict[str, list[Registration]] = {}
        for r in self._records:
            self._exact.setdefault(r.name, []).append(r)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def distinct_names(self) -> int:
        return len(self._exact)

    @classmethod
    def from_dir(cls, raw_dir: str | os.PathLike[str]) -> Registry:
        """從 `data/raw/` 讀三個稅籍檔。缺哪個檔就跳過哪個。"""
        records: list[Registration] = []
        for filename, status in REGISTRY_FILES:
            path = os.path.join(raw_dir, filename)
            if not os.path.exists(path):
                continue
            records.extend(cls._read_file(path, status))
        if not records:
            raise FileNotFoundError(
                f"{raw_dir} 底下找不到任何稅籍檔，"
                f"預期檔名：{', '.join(f for f, _ in REGISTRY_FILES)}"
            )
        return cls(records)

    @staticmethod
    def _read_file(path: str, status: str) -> list[Registration]:
        # 檔案第一列資料是產製日期（如 26-AUG-26 塞在營業地址欄），
        # 統編為空自然會被下面的檢查濾掉，不必特判。
        out: list[Registration] = []
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                name = normalize(row.get("營業人名稱") or "")
                uniform_no = (row.get("統一編號") or "").strip()
                if not name or not uniform_no:
                    continue
                out.append(
                    Registration(
                        name=name,
                        uniform_no=uniform_no,
                        org_type=(row.get("組織別名稱") or "").strip(),
                        status=status,
                        hq_no=(row.get("總機構統一編號") or "").strip(),
                    )
                )
        return out

    def _prefix_matches(self, prefix: str) -> list[Registration]:
        """所有以 prefix 開頭的登記。名冊已排序，二分搜尋取區間。"""
        lo = bisect.bisect_left(self._names, prefix)
        hi = bisect.bisect_left(self._names, prefix + "￿")
        return self._records[lo:hi]

    @staticmethod
    def _single_uniform_no(matches: list[Registration]) -> str | None:
        nos = {m.uniform_no for m in matches}
        return nos.pop() if len(nos) == 1 else None

    @classmethod
    def _by_exact_name(cls, matches: list[Registration], method: str) -> Resolution:
        """名稱比對命中之後的收斂邏輯，三條精確路徑共用。"""
        no = cls._single_uniform_no(matches)
        if no:
            return Resolution(no, method, tuple(matches))
        ordered = tuple(_by_status(matches))
        # 同名不同統編。常見於連鎖總部改組（萊爾富、全家）與菜市場名商號。
        # 舊統編都歇業了、只剩一個營業中的話還救得回來，否則不猜。
        operating = {m.uniform_no for m in matches if m.status == "營業中"}
        if len(operating) == 1:
            return Resolution(operating.pop(), "sole_operating", ordered)
        return Resolution(None, "ambiguous_name", ordered)

    def resolve(self, org: str) -> Resolution:
        """把 `twec.names` 的 org 換成統編。

        輸入必須是 `split_entity(normalize(...)).org` 的產出。
        """
        exact = self._exact.get(org)
        if exact:
            return self._by_exact_name(exact, "exact")

        for prefix in _JURIDICAL_PREFIXES:
            if org.startswith(prefix):
                stripped = self._exact.get(org[len(prefix) :])
                if stripped:
                    return self._by_exact_name(stripped, "strip_juridical")
                break

        # 自然人商號：勞動部寫「王小明即某某商行」，稅籍只登記商號名。
        # `twec.names` 刻意不拆這個字串（怕錯拆），在這裡才拆。
        if "即" in org:
            shop = org.split("即", 1)[1]
            hit = self._exact.get(shop)
            if hit:
                return self._by_exact_name(hit, "natural_person")

        # 外商在台只有分公司有稅籍，母公司名查不到；連鎖店的總部有時
        # 也只登記各分店。前綴命中的那群若同屬一個總機構，那就是答案。
        matches = self._prefix_matches(org)
        if matches:
            hq = {m.hq_no for m in matches if m.hq_no}
            if len(hq) == 1:
                return Resolution(hq.pop(), "hq_via_prefix", tuple(_by_status(matches))[:8])
            if not hq:
                no = self._single_uniform_no(matches)
                if no:
                    return Resolution(no, "prefix_single", tuple(matches))
            return Resolution(None, "ambiguous_prefix", tuple(_by_status(matches))[:8])

        return Resolution(None, "miss")


def _by_status(records: list[Registration]) -> list[Registration]:
    """營業中的排前面，方便人工判讀時先看還活著的那筆。"""
    return sorted(records, key=lambda r: _STATUS_RANK.get(r.status, 3))
