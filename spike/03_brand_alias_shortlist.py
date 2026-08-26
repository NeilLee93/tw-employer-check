"""
Spike 03：把違規次數 >= 10 的事業單位撈出來，自動分桶，縮短人工要看的清單。

分桶邏輯：
  自動排除 = 名稱本身就是大家會搜的詞（B2B、長照、學校、自然人商號等），
             或根本沒有消費者品牌。
  需人工判斷 = 有消費者接觸面、法人名可能與品牌名不同者。

自動排除只是「省時間」，不是「保證正確」。最終仍由人核。
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "lsa_violations_raw.csv"
OUT = ROOT / "data" / "brand_alias_shortlist.csv"

MIN_COUNT = 10

# --- 自動排除規則：(標籤, regex) ---
EXCLUDE_RULES = [
    ("自然人商號", r"即"),
    ("長照/醫療機構", r"長期照顧|護理之家|養護|安養|身心障礙|教養院|康復之家|居家長照|醫療社團法人"),
    ("學校/教育", r"學校財團法人|大學|學院|高級中|國民中|國民小|幼兒園|托嬰|補習班|文教"),
    ("社福/宗教/公益", r"社會福利|慈善|基金會|協會|學會|促進會|寺|宮|教會"),
    ("農漁水利會", r"農會|漁會|水利會|合作社"),
    ("保全/物業/清潔", r"保全|物業管理|清潔|環境維護|大樓管理"),
    ("人力派遣/仲介", r"人力|派遣|仲介|管理顧問|勞務"),
    ("營造/工程/製造", r"營造|工程|建設|模具|精密|機械|鋼鐵|塑膠|化工|紡織|印刷|包裝|窯業|水泥|電線|電纜|鑄造"),
]

# 產業標籤（只做分組顯示用，不影響分桶）
INDUSTRY_HINTS = [
    ("客運/運輸", r"客運|汽車運輸|通運|貨運|物流|宅配|捷運|鐵路|航空|航運|船"),
    ("零售/量販/超商", r"超商|超市|量販|百貨|購物|商場|實業|流通"),
    ("餐飲/旅宿", r"餐飲|餐廳|食品|飯店|旅館|酒店|咖啡|飲料"),
    ("金融/保險", r"人壽|保險|銀行|證券|投信|金融|租賃"),
    ("電信/媒體/科技", r"電信|通訊|網路|傳播|媒體|電視|資訊|科技|電子|半導體|光電"),
    ("醫院", r"醫院|診所"),
    ("公部門/國營", r"^交通部|^經濟部|政府|縣$|市政府|管理局|管理處|公所|郵政|自來水|電力"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).replace("臺", "台")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[（(][^（()）]*[)）]\s*$", "", s)
    return s.strip()


def tag(name: str, rules) -> str | None:
    for label, pat in rules:
        if re.search(pat, name):
            return label
    return None


def main() -> None:
    df = pd.read_csv(RAW, dtype=str, encoding="utf-8").fillna("")
    df["entity"] = df["事業單位名稱或負責人"].map(norm)

    g = (df.groupby("entity")
           .agg(違規次數=("entity", "size"),
                主要主管機關=("主管機關", lambda s: s.value_counts().index[0]),
                最近公告=("公告日期", "max"))
           .reset_index()
           .rename(columns={"entity": "法人名稱"}))
    g = g[g["違規次數"] >= MIN_COUNT].sort_values("違規次數", ascending=False)

    g["排除理由"] = g["法人名稱"].map(lambda n: tag(n, EXCLUDE_RULES))
    g["產業推測"] = g["法人名稱"].map(lambda n: tag(n, INDUSTRY_HINTS) or "其他")
    g["需人工判斷"] = g["排除理由"].isna()

    g.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"違規 >= {MIN_COUNT} 次的事業單位：{len(g)} 家")
    print(f"  自動排除    : {(~g['需人工判斷']).sum()}")
    print(f"  需人工判斷  : {g['需人工判斷'].sum()}")

    print("\n自動排除的分類統計：")
    for k, n in g.loc[~g["需人工判斷"], "排除理由"].value_counts().items():
        print(f"  {k:<16} {n:>4}")

    review = g[g["需人工判斷"]]
    print(f"\n{'=' * 72}")
    print(f"需人工判斷清單（{len(review)} 家，依違規次數排序）")
    print("=" * 72)
    for ind in review["產業推測"].value_counts().index:
        sub = review[review["產業推測"] == ind]
        print(f"\n--- {ind}（{len(sub)}）---")
        for _, r in sub.iterrows():
            print(f"  {r['違規次數']:>4}  {r['法人名稱']}")

    print(f"\n已輸出：{OUT}")


if __name__ == "__main__":
    main()
