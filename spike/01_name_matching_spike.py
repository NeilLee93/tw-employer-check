"""
Spike 01：驗證「事業單位名稱或負責人」欄位到底能不能拿來做公司比對。

這是拋棄式驗證腳本，目的只有一個：回答「這個專案做不做得成」。
不要在這上面加功能，驗證完就該重寫。

執行：python spike/01_name_matching_spike.py
"""

import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "lsa_violations_raw.csv"

# --- 公司型態關鍵字：用來判斷括號內是「人名」還是「另一個組織」 ---
ORG_TOKENS = [
    "公司", "有限", "股份", "商行", "企業社", "工作室", "事務所", "商號",
    "工廠", "農場", "牧場", "漁船", "診所", "醫院", "學校", "大學", "中心",
    "協會", "基金會", "合作社", "工程行", "銀行", "飯店", "旅館", "分公司",
]


def load() -> pd.DataFrame:
    df = pd.read_csv(RAW, dtype=str, encoding="utf-8").fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df


def normalise(name: str) -> str:
    """最基本的名稱正規化：全形轉半形、臺台統一、去空白與常見雜訊。"""
    s = unicodedata.normalize("NFKC", name)      # 全形 → 半形
    s = s.replace("臺", "台")
    s = re.sub(r"\s+", "", s)
    return s


def strip_paren(name: str) -> str:
    """去掉最外層括號內容（全形與半形都處理）。"""
    return re.sub(r"[（(][^（()）]*[)）]\s*$", "", name).strip()


def classify_paren(inner: str) -> str:
    if any(t in inner for t in ORG_TOKENS):
        return "組織名"
    if 2 <= len(inner) <= 4 and re.fullmatch(r"[一-鿿·．]+", inner):
        return "疑似人名"
    if not inner:
        return "空括號"
    return "其他"


def section(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def main() -> None:
    df = load()

    section("1. 基本規模")
    print(f"總筆數           : {len(df):,}")
    print(f"欄位             : {list(df.columns)}")
    col = "事業單位名稱或負責人"
    print(f"公告日期範圍     : {df['公告日期'].min()} ~ {df['公告日期'].max()}")
    print(f"原始名稱不重複數 : {df[col].nunique():,}")

    section("2. 括號結構分析（決定 parse 難度）")
    has_paren = df[col].str.contains(r"[（(]", regex=True)
    print(f"含括號筆數       : {has_paren.sum():,} ({has_paren.mean():.1%})")

    inner = df.loc[has_paren, col].str.extract(r"[（(]([^（()）]*)[)）]\s*$")[0].fillna("")
    kinds = inner.map(classify_paren)
    print("\n括號內容分類：")
    for k, n in kinds.value_counts().items():
        print(f"  {k:<8} {n:>7,}  ({n / len(inner):.1%})")

    print("\n各類抽樣：")
    for k in kinds.unique():
        samples = df.loc[has_paren][kinds == k][col].drop_duplicates().head(4).tolist()
        print(f"  [{k}]")
        for s in samples:
            print(f"      {s}")

    section("3. 正規化後能收斂多少")
    raw_n = df[col].nunique()
    norm = df[col].map(normalise)
    norm_n = norm.nunique()
    entity = norm.map(strip_paren)
    entity_n = entity.nunique()
    print(f"原始不重複            : {raw_n:,}")
    print(f"正規化後不重複        : {norm_n:,}   (減少 {raw_n - norm_n:,})")
    print(f"再去括號後不重複      : {entity_n:,}   (再減少 {norm_n - entity_n:,})")
    print(f"總收斂率              : {(raw_n - entity_n) / raw_n:.1%}")

    section("4. 名稱型態盤點（除了公司還有什麼）")
    patterns = {
        "含『即』(自然人即商號)": r"即",
        "分公司": r"分公司",
        "個人(無組織關鍵字)": None,
        "漁船": r"漁船",
        "工程行/商行/企業社": r"(工程行|商行|企業社)",
    }
    for label, pat in patterns.items():
        if pat is None:
            m = ~entity.str.contains("|".join(ORG_TOKENS), regex=True)
            print(f"  {label:<24} {m.sum():>7,} ({m.mean():.1%})")
        else:
            m = entity.str.contains(pat, regex=True)
            print(f"  {label:<24} {m.sum():>7,} ({m.mean():.1%})")

    section("5. 實測查詢：知名企業查得到嗎")
    targets = ["台灣積體電路", "鴻海", "統一超商", "全家便利商店", "長榮", "中華電信", "家樂福", "麥當勞"]
    for t in targets:
        hit = entity[entity.str.contains(normalise(t), regex=False)]
        variants = hit.value_counts()
        print(f"\n  『{t}』→ {len(hit):,} 筆，{len(variants)} 種名稱寫法")
        for name, n in variants.head(5).items():
            print(f"       {n:>5}  {name}")

    section("6. 違法法規法條欄位（多法條問題）")
    law = df["違法法規法條"]
    multi = law.str.contains(";")
    print(f"單筆含多法條      : {multi.sum():,} ({multi.mean():.1%})")
    flat = law.str.split(";").explode().str.strip()
    flat = flat[flat != ""]
    print(f"展開後法條總數    : {len(flat):,}")
    print(f"不重複法條數      : {flat.nunique():,}   ← 嚴重度對照表要建這麼多條")
    print("\nTop 15 高頻法條：")
    for name, n in flat.value_counts().head(15).items():
        print(f"  {n:>6,}  {name}")

    section("7. 罰鍰金額可解析性")
    amt = pd.to_numeric(df["罰鍰金額"].str.replace(r"[,\s]", "", regex=True), errors="coerce")
    print(f"可轉數值          : {amt.notna().sum():,} ({amt.notna().mean():.1%})")
    print(f"無法轉數值        : {amt.isna().sum():,}")
    if amt.isna().any():
        bad = df.loc[amt.isna(), "罰鍰金額"].value_counts().head(5)
        print("  無法解析的值抽樣：")
        for v, n in bad.items():
            print(f"      {n:>6,}  {v!r}")
    print(f"\n金額中位數        : {amt.median():,.0f}")
    print(f"金額最大值        : {amt.max():,.0f}")

    section("8. 累犯偵測可行性（本專案核心價值）")
    counts = entity.value_counts()
    print(f"只被罰 1 次的事業單位 : {(counts == 1).sum():,} ({(counts == 1).mean():.1%})")
    print(f"被罰 2 次以上         : {(counts >= 2).sum():,}")
    print(f"被罰 5 次以上         : {(counts >= 5).sum():,}")
    print(f"被罰 10 次以上        : {(counts >= 10).sum():,}")
    print("\n違規次數最多的 10 家：")
    for name, n in counts.head(10).items():
        print(f"  {n:>4}  {name}")


if __name__ == "__main__":
    main()
