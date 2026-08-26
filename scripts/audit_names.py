"""拿全量資料驗收 twec.names，並與舊 spike 的正規化對照。

單元測試只覆蓋挑出來的個案，這支腳本負責回答「在 77,813 列真實資料上有沒有壞掉」。
改動 twec/names.py 之後應該跑一次。

執行：python scripts/audit_names.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twec.names import normalize, split_entity  # noqa: E402

RAW = Path(__file__).resolve().parents[1] / "data" / "lsa_violations_raw.csv"
COL = "事業單位名稱或負責人"

# 機關/單位字尾。人名不會長這樣，出現在 person 欄就是分類錯了。
_UNIT_SUFFIX = re.compile(r"(所|局|部|處|站|課|廠|店|館|園|校|隊|組|室)$")


def main() -> None:
    if not RAW.exists():
        sys.exit(f"找不到 {RAW}，請先依 README 下載原始資料。")

    df = pd.read_csv(RAW, dtype=str).fillna("")
    normalized = df[COL].map(normalize)
    parsed = normalized.map(split_entity)
    org = parsed.map(lambda e: e.org)

    print(f"原始不重複名稱      : {df[COL].nunique():,}")
    print(f"正規化＋拆解後      : {org.nunique():,}")
    print(f"收斂率              : {1 - org.nunique() / df[COL].nunique():.1%}")

    print("\n殘留缺陷（都應為 0）：")
    leftovers = {
        "HTML entity 未解碼": org.str.contains(r"&#|&nbsp;|�", regex=True).sum(),
        "空白或換行": org.str.contains(r"\s").sum(),
    }
    for label, count in leftovers.items():
        print(f"  {label:<20} {count:>6,}")

    # 只檢查「無括號串接」判出來的人名。括號內的內容是資料本身標成負責人的，
    # 我們沒有猜；會誤報 劉柏園、呂文局 這類以單位字尾結尾的真實姓名。
    suspicious = {
        e.person
        for raw, e in zip(normalized, parsed)
        if e.person and f"({e.person})" not in raw and _UNIT_SUFFIX.search(e.person)
    }
    print(f"  {'誤判為人名的單位名':<20} {len(suspicious):>6,}  {sorted(suspicious)}")

    print("\n拆解結果：")
    print(f"  kind 分布          {parsed.map(lambda e: e.kind).value_counts().to_dict()}")
    print(f"  抽出 person        {parsed.map(lambda e: e.person is not None).sum():,} 列")
    sites = parsed.map(lambda e: e.site).dropna()
    print(f"  抽出 site          {len(sites):,} 列 / {sites.nunique()} 種")

    print("\n合併筆數最多的 10 家：")
    for name, n in org.value_counts().head(10).items():
        print(f"  {n:>4}  {name}")


if __name__ == "__main__":
    main()
