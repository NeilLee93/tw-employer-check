"""
Spike 05：不靠網路搜尋，先用手上資料替「待查」公司做分診。

核心假設：
  需要品牌別名的一定是「連鎖／多據點」企業。
  單一縣市、單一據點的公司不會有消費者品牌別名問題。

所以先看縣市分布，就能把大部分待查案件直接判掉，不必上網亂查。
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "lsa_violations_raw.csv"

TARGETS = [
    # 待查
    "威合股份有限公司", "宏華國際股份有限公司", "美德耐股份有限公司",
    "台灣善商股份有限公司", "和德昌股份有限公司", "笑笑笑國際股份有限公司",
    "樹籽股份有限公司", "大無限健康事業股份有限公司", "天廬育樂事業股份有限公司",
    "豐隆大飯店股份有限公司", "朝陽富元教育股份有限公司", "裕利股份有限公司",
    "黑浮國際餐飲有限公司", "河邊股份有限公司", "富利餐飲股份有限公司",
    # 中信心，一併分診
    "山隆通運股份有限公司", "星裕國際股份有限公司", "北基國際股份有限公司",
    "五花馬國際行銷股份有限公司", "三商行股份有限公司",
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).replace("臺", "台")
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[（(][^（()）]*[)）]\s*$", "", s).strip()


def main() -> None:
    df = pd.read_csv(RAW, dtype=str, encoding="utf-8").fillna("")
    df["entity"] = df["事業單位名稱或負責人"].map(norm)
    sub = df[df["entity"].isin(TARGETS)]

    rows = []
    for name, g in sub.groupby("entity"):
        cities = g["主管機關"].value_counts()
        laws = (g["違反法規內容"].str.split(";").explode().str.strip()
                .value_counts().head(2).index.tolist())
        rows.append({
            "法人名稱": name,
            "違規次數": len(g),
            "縣市數": len(cities),
            "縣市分布": "、".join(f"{c}({n})" for c, n in cities.items()),
            "期間": f"{g['公告日期'].min()[:6]}~{g['公告日期'].max()[:6]}",
            "常見違規": "；".join(laws),
        })

    out = pd.DataFrame(rows).sort_values(["縣市數", "違規次數"], ascending=False)

    print("=" * 78)
    print("分診結果：縣市數 >= 3 才可能是連鎖，才需要品牌別名")
    print("=" * 78)
    for _, r in out.iterrows():
        verdict = "★ 可能是連鎖，需查品牌" if r["縣市數"] >= 3 else "  單一/少數據點，多半不需別名"
        print(f"\n{r['法人名稱']}  ({r['違規次數']} 次, {r['縣市數']} 個縣市)  {verdict}")
        print(f"    分布  : {r['縣市分布']}")
        print(f"    期間  : {r['期間']}")
        print(f"    違規  : {r['常見違規']}")

    n_chain = (out["縣市數"] >= 3).sum()
    print(f"\n{'=' * 78}")
    print(f"需要真正上網查品牌的：{n_chain} 家（原本 {len(out)} 家）")
    out.to_csv(ROOT / "data" / "unknowns_triage.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
