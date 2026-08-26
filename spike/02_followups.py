"""
Spike 02：追查 spike 01 冒出來的三個疑點。

1. 罰鍰金額 39.8% 空值 —— 是資料缺漏還是本來就沒罰鍰？
2. 法條字串「勞基法」vs「勞動基準法」—— 正規化後真正有幾條？
3. 品牌名 ≠ 法人名（家樂福 → 家福）—— 這個洞有多大？
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "lsa_violations_raw.csv"


def section(t: str) -> None:
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


df = pd.read_csv(RAW, dtype=str, encoding="utf-8").fillna("")
df["年"] = df["公告日期"].str[:4]
amt = pd.to_numeric(df["罰鍰金額"].str.replace(r"[,\s]", "", regex=True), errors="coerce")
df["有金額"] = amt.notna()

section("1. 罰鍰金額空值分布")
by_year = df.groupby("年")["有金額"].agg(["size", "sum"])
by_year["有金額率"] = by_year["sum"] / by_year["size"]
print(by_year.to_string(formatters={"有金額率": "{:.1%}".format}))

print("\n依主管機關（有金額率最低的 10 個）：")
by_ag = df.groupby("主管機關")["有金額"].agg(["size", "mean"]).sort_values("mean")
by_ag = by_ag[by_ag["size"] >= 200]
print(by_ag.head(10).to_string(formatters={"mean": "{:.1%}".format}))

print("\n無金額列的『備註說明』前 8 名：")
for v, n in df.loc[~df["有金額"], "備註說明"].value_counts().head(8).items():
    print(f"  {n:>6,}  {v!r}")

section("2. 法條字串正規化")
flat = df["違法法規法條"].str.split(";").explode().str.strip()
flat = flat[flat != ""]
print(f"正規化前不重複 : {flat.nunique()}")

norm = (flat
        .str.replace("勞基法", "勞動基準法", regex=False)
        .str.replace(r"\s+", "", regex=True)
        .map(lambda s: unicodedata.normalize("NFKC", s)))
print(f"統一『勞基法』後: {norm.nunique()}")

# 只取到「條」層級，看主條文有幾條
article = norm.str.extract(r"第(\d+(?:-\d+)?)條")[0]
print(f"不重複『條』     : {article.nunique()}")
print(f"\n引用的法規名稱分布：")
lawname = norm.str.extract(r"^([^第]+)")[0].fillna("(無法解析)")
for v, n in lawname.value_counts().head(10).items():
    print(f"  {n:>7,}  {v}")

section("3. 品牌名 vs 法人名")
name = (df["事業單位名稱或負責人"]
        .map(lambda s: unicodedata.normalize("NFKC", s).replace("臺", "台"))
        .str.replace(r"[（(][^（()）]*[)）]\s*$", "", regex=True)
        .str.strip())

cases = {
    "家樂福": ["家樂福", "家福"],
    "全聯": ["全聯"],
    "誠品": ["誠品"],
    "王品": ["王品"],
    "星巴克": ["星巴克", "統一星巴克"],
    "路易莎": ["路易莎"],
    "南山人壽": ["南山"],
}
for brand, keys in cases.items():
    print(f"\n  品牌『{brand}』")
    for k in keys:
        hit = name[name.str.contains(k, regex=False)]
        vc = hit.value_counts()
        print(f"    關鍵字 '{k}' → {len(hit):>4} 筆 / {len(vc)} 種寫法")
        for n_, c in vc.head(3).items():
            print(f"         {c:>4}  {n_}")

section("4. 巢狀括號 parse 失敗量")
nested = df["事業單位名稱或負責人"].str.count(r"[（(]") > 1
print(f"含兩層以上括號 : {nested.sum():,} ({nested.mean():.2%})  ← spike01 的『空括號』其實是這個")
for s in df.loc[nested, "事業單位名稱或負責人"].drop_duplicates().head(5):
    print(f"    {s}")
