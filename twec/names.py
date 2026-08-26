"""事業單位名稱的正規化與拆解。

勞動部的資料集沒有統一編號欄位，`事業單位名稱或負責人` 這個字串是
唯一的 join key。本模組是整個專案的地基：歸戶、品牌別名比對、
跨資料集彙整全部掛在這裡的產出上。
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

# html.unescape() 對超出 Unicode 範圍的碼位（如 &#2013268209;）會吐出
# U+FFFD replacement character，對無法辨識的 entity 則原樣保留。
# 兩種殘骸都會讓名稱永遠對不上，移除後至少還能靠其餘字元比對。
_UNRESOLVED_ENTITY = re.compile(r"&#\w+;|�")


def normalize(raw: str) -> str:
    """把原始欄位值清成可比對的字串。

    依序做四件事，順序不可調換：
      1. HTML entity 解碼——必須最先，因為 &nbsp; 解出來是空白，
         要交給第 4 步一併清掉。
      2. NFKC——全形轉半形，順帶把全形空格 U+3000 轉成一般空格。
      3. 臺 → 台。
      4. 移除所有空白字元（欄位內含換行與空白）。

    不處理括號，那是 split_entity 的事。
    """
    s = html.unescape(raw)
    s = _UNRESOLVED_ENTITY.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("臺", "台")
    s = re.sub(r"\s+", "", s)
    return s


# 事業單位型態關鍵字，長的排前面，比對時取最後一個出現的位置。
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

_ORG_SUFFIX_RE = re.compile("|".join(_ORG_SUFFIX))


@dataclass(frozen=True)
class EntityName:
    """一筆 `事業單位名稱或負責人` 拆解後的結果。

    `org` 是歸戶用的 key，其餘欄位是為了讓報告能講清楚細節而保留的。

    kind:
        company —— 一般事業單位
        union   —— 企業工會／產業工會，依工會法是獨立法人，不歸戶到母公司
    """

    org: str
    person: str | None = None
    kind: str = "company"
    related_org: str | None = None
    site: str | None = None


def _split_after_org_suffix(name: str) -> tuple[str, str] | None:
    """在最後一個事業單位型態關鍵字之後切開，回傳（本體, 殘餘）。

    殘餘為空字串時回傳 None——名稱本來就以型態關鍵字結尾，沒有東西要拆。
    這一步是為了處理「負責人姓名沒加括號直接串在公司名後面」，
    以及分公司、廠區、企業工會這些附加在法人名後面的單位。
    """
    # 取最後一個「後面還有東西」的關鍵字。不能單純取最後一個，因為
    #「分公司」本身含有「公司」，會讓 香港商世界健身事業有限公司台灣分公司
    # 的最後一個關鍵字落在字尾而切不出殘餘。
    cut = None
    for m in _ORG_SUFFIX_RE.finditer(name):
        if m.end() < len(name):
            cut = m.end()
    if cut is None:
        return None
    return name[:cut], name[cut:]


def _split_trailing_parenthesis(name: str) -> tuple[str, str | None]:
    """切出字尾那一組括號的內容，支援巢狀。

    從字串最後一個字元往回掃並記錄括號深度，深度歸零時就是配對的左括號。
    用掃描而非正則，是因為正則處理不了 `(畢揚賀(JamesEricBjornholt))` 這種巢狀。
    """
    if not name or name[-1] not in ")）":
        return name, None

    depth = 0
    for i in range(len(name) - 1, -1, -1):
        if name[i] in ")）":
            depth += 1
        elif name[i] in "(（":
            depth -= 1
            if depth == 0:
                inner = name[i + 1 : -1]
                return name[:i], inner or None
    # 括號不配對（左括號缺失），當作沒有括號處理。
    return name, None


def _is_institution_type_marker(inner: str) -> bool:
    """判斷括號內容是不是機構類型註記，如「養護型」「長期照顧型」。

    這種註記是機構名稱的一部分，剝掉會讓同一機構的不同型別混為一談。
    全資料集裡以「型」結尾的括號內容共 85 列，全為類型註記，無人名誤入，
    所以用字尾判斷就夠，不需要維護白名單。
    """
    return inner.endswith("型")


# 同一法人底下的營運據點。歸戶時併入母公司，但保留明細供報告拆分。
_SITE_SUFFIX = (
    "分公司",
    "廠",
    "營業處",
    "事業部",
    "分行",
    "門市",
    "分校",
    "分班",
    "機構",
    "營運處",
    "辦事處",
    "郵局",
    "所",
)

# 這些是欄位裡的標籤而非姓名，不能當人名收下來。
_NOT_A_PERSON = frozenset({"負責人", "代表人", "雇主"})


def _is_site(tail: str) -> bool:
    """判斷公司名後面接的殘餘字串是不是營運據點。

    「附設」開頭的是附設機構（多為長照、補習班），同屬一個法人，比照廠區處理。
    """
    return tail.startswith("附設") or tail.endswith(_SITE_SUFFIX)


# 中文姓名長度。四字涵蓋複姓與日籍姓名（井上浩利、渡邉剛德）。
_PERSON_TAIL_RE = re.compile(r"[一-鿿]{2,4}")


def _is_person_tail(tail: str) -> bool:
    """判斷公司名後面接的殘餘字串是不是沒加括號的負責人姓名。

    只認 2-4 個純中文字，且要排除兩種長得像人名的殘餘：
      - 含「即」：「連進企業社即陳連進」這種自然人商號的本體就是整串。
      - 本身是事業單位型態關鍵字：「笨蛋工作室有限公司」的殘餘是「有限公司」，
        剛好四個中文字，不擋掉會被砍成「笨蛋工作室」。
    分不出來的一律留著：造成分裂還能靠別名表補，錯併就救不回來了。
    """
    if "即" in tail or tail in _NOT_A_PERSON or _ORG_SUFFIX_RE.search(tail):
        return False
    return _PERSON_TAIL_RE.fullmatch(tail) is not None


def split_entity(name: str) -> EntityName:
    """把正規化後的名稱拆成事業單位與負責人。

    輸入必須是 normalize() 的產出。
    """
    org, inner = _split_trailing_parenthesis(name)
    if inner is not None and _is_institution_type_marker(inner):
        org, inner = name, None

    split = _split_after_org_suffix(org)
    if split is not None:
        body, tail = split
        if tail.endswith("工會"):
            # 工會是獨立法人，org 保留全名不歸戶到母公司，
            # 但記下母公司讓報告能標註關聯。
            # 這個判斷必須早於廠區，否則工會會被誤併進母公司。
            return EntityName(org=org, person=inner, kind="union", related_org=body)
        if _is_site(tail):
            return EntityName(org=body, person=inner, site=tail)
        if inner is None and _is_person_tail(tail):
            return EntityName(org=body, person=tail)

    return EntityName(org=org, person=inner)
