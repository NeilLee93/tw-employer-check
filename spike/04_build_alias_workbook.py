"""
Spike 04：產出品牌別名人工核對用的 Excel。

分四類處理，讓人只需要看真正需要判斷的那一小撮：
  A. 可自動處理（插字規則）    —— 「XX汽車客運」→「XX客運」，regex 可解，不需人工建表
  B. 需歸戶合併               —— 同一實體的不同法人名（改制、總分公司）
  C. 別名候選（需人工核）      —— 法人名 ≠ 消費者品牌，已附建議值與信心等級
  D. 其餘                     —— 名稱本身即可搜，或未逐一檢視

信心等級說明：
  高   = 明確且廣為人知的對應
  中   = 有相當把握但請務必查證
  待查 = 我不知道這家的消費者品牌是什麼，需要你查
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
SHORTLIST = ROOT / "data" / "brand_alias_shortlist.csv"
OUT = ROOT / "data" / "品牌別名核對表.xlsx"

# --- C. 別名候選：法人名 -> (建議別名, 信心) ---
ALIAS: dict[str, tuple[str, str]] = {
    # 零售 / 通路
    "家福股份有限公司": ("家樂福、Carrefour", "高"),
    "惠康百貨股份有限公司": ("頂好、Wellcome", "高"),
    "來來超商股份有限公司": ("OK超商、OK mart", "高"),
    "三商家購股份有限公司": ("美廉社", "高"),
    "統一超商股份有限公司": ("7-ELEVEN、小七、統一超商", "高"),
    "全家便利商店股份有限公司": ("FamilyMart、全家", "高"),
    "萊爾富國際股份有限公司": ("Hi-Life、萊爾富", "高"),
    "全聯實業股份有限公司": ("全聯福利中心、PXMart", "高"),
    "大潤發流通事業股份有限公司": ("大潤發、RT-Mart", "高"),
    "寶雅國際股份有限公司": ("寶雅、POYA", "高"),
    "台灣屈臣氏個人用品商店股份有限公司": ("屈臣氏、Watsons", "高"),
    "金石堂圖書股份有限公司": ("金石堂", "高"),
    "東森得易購股份有限公司": ("東森購物", "高"),
    "富邦媒體科技股份有限公司": ("momo購物網、momo", "高"),
    # 餐飲
    "安心食品服務股份有限公司": ("摩斯漢堡、MOS Burger", "高"),
    "雲雀國際股份有限公司": ("藏壽司、Kura Sushi", "高"),
    "台灣東利多股份有限公司": ("丸龜製麵", "高"),
    "饗賓餐旅事業股份有限公司": ("饗食天堂、旭集、果然匯", "高"),
    "豆府股份有限公司": ("涓豆腐、北村豆腐家", "高"),
    "王品餐飲股份有限公司": ("王品、西堤、陶板屋、原燒、聚", "高"),
    "路易莎職人咖啡股份有限公司": ("路易莎、Louisa", "高"),
    "爭鮮股份有限公司": ("爭鮮、爭鮮迴轉壽司", "高"),
    "五花馬國際行銷股份有限公司": ("五花馬水餃館", "中"),
    "富利餐飲股份有限公司": ("必勝客 Pizza Hut、肯德基 KFC", "高"),
    "台灣善商股份有限公司": ("すき家 SUKIYA、食其家、はま寿司 HAMASUSHI、濱壽司", "高"),
    "和德昌股份有限公司": ("麥當勞 McDonald's", "高"),
    "笑笑笑國際股份有限公司": ("", "待查"),
    "黑浮國際餐飲有限公司": ("", "待查"),
    "河邊股份有限公司": ("", "待查"),
    # 食品製造
    "宜蘭食品工業股份有限公司": ("旺旺", "高"),
    "佳格食品股份有限公司": ("桂格、得意的一天、福樂", "高"),
    "聯華食品工業股份有限公司": ("可樂果、元本山", "高"),
    "宏亞食品股份有限公司": ("77乳加、禮坊", "高"),
    "金車股份有限公司": ("伯朗咖啡、噶瑪蘭威士忌、波爾", "高"),
    "味全食品工業股份有限公司": ("味全、林鳳營、貝納頌", "高"),
    "大成長城企業股份有限公司": ("大成", "中"),
    "台灣卜蜂企業股份有限公司": ("卜蜂", "中"),
    # 物流 / 運輸
    "統一速達股份有限公司": ("黑貓宅急便", "高"),
    "嘉里大榮物流股份有限公司": ("大榮貨運", "高"),
    "台灣順豐速運股份有限公司": ("順豐、SF Express", "高"),
    "富胖達股份有限公司": ("foodpanda、空腹熊貓", "高"),
    "交通部台灣鐵路管理局": ("台鐵", "高"),
    "國營台灣鐵路股份有限公司": ("台鐵", "高"),
    "台灣高速鐵路股份有限公司": ("高鐵、THSR", "高"),
    "中華航空股份有限公司": ("華航、China Airlines", "高"),
    "遠東航空股份有限公司": ("遠航", "高"),
    "台灣虎航股份有限公司": ("虎航、tigerair", "高"),
    "山隆通運股份有限公司": ("（疑為山隆加油站，請查證）", "中"),
    # 科技 / 電信 / 媒體
    "宏達國際電子股份有限公司": ("HTC、宏達電", "高"),
    "台灣國際航電股份有限公司": ("Garmin", "高"),
    "日月光半導體製造股份有限公司": ("日月光、ASE", "高"),
    "和碩聯合科技股份有限公司": ("和碩、PEGATRON", "高"),
    "佳世達科技股份有限公司": ("（前身明基電通，BenQ 品牌現屬明基電通，勿混用）", "中"),
    "壹傳媒電視廣播股份有限公司": ("壹電視", "中"),
    "神腦國際企業股份有限公司": ("神腦", "高"),
    # 公用事業 / 服務
    "台灣電力股份有限公司": ("台電", "高"),
    "中華郵政股份有限公司": ("郵局", "高"),
    "台灣中油股份有限公司": ("中油", "高"),
    "香港商世界健身事業有限公司": ("World Gym、世界健身房", "高"),
    "香港商世界健身事業有限公司台灣分公司": ("World Gym、世界健身房", "高"),
    "媚登峰健康事業股份有限公司": ("媚登峰", "高"),
    "新加坡商傲勝全球股份有限公司": ("OSIM", "高"),
    "台灣通力電梯股份有限公司": ("KONE、通力", "高"),
    "六福開發股份有限公司": ("六福村主題遊樂園", "高"),
    "威秀影城股份有限公司": ("威秀影城、Vieshow", "高"),
    "晶華國際酒店股份有限公司": ("晶華酒店、Regent", "高"),
    "福華大飯店股份有限公司": ("福華飯店", "高"),
    "理想大地股份有限公司": ("花蓮理想大地", "中"),
    "三商行股份有限公司": ("三商（旗下品牌歸屬須確認，部分在三商餐飲等他法人）", "中"),
    "星裕國際股份有限公司": ("（疑為 New Balance 台灣代理，請查證）", "中"),
    "北基國際股份有限公司": ("（疑為北基加油站，請查證）", "中"),
    "台灣富士全錄股份有限公司": ("富士全錄、Fuji Xerox（現已更名，須確認現行名稱）", "中"),
    # 我不知道其消費者品牌者
    "宏華國際股份有限公司": ("", "待查"),
    "美德耐股份有限公司": ("", "待查"),
    "威合股份有限公司": ("（無消費者品牌：機構後勤外包，UEM EDGENTA 集團「威合威務」，名稱即可搜）", "高"),
    "樹籽股份有限公司": ("", "待查"),
    "大無限健康事業股份有限公司": ("", "待查"),
    "天廬育樂事業股份有限公司": ("", "待查"),
    "豐隆大飯店股份有限公司": ("", "待查"),
    "朝陽富元教育股份有限公司": ("", "待查"),
    "裕利股份有限公司": ("", "待查"),
}

# --- B. 需歸戶合併：同一實體的不同法人名 ---
MERGE_GROUPS = [
    ("台鐵", ["交通部台灣鐵路管理局", "國營台灣鐵路股份有限公司"], "高",
     "公司化改制，同一實體前後兩個名稱。65 + 10 = 75"),
    ("World Gym", ["香港商世界健身事業有限公司", "香港商世界健身事業有限公司台灣分公司"], "高",
     "總公司與台灣分公司分列，同一營運實體。31 + 15 = 46"),
    ("麥當勞", ["和德昌股份有限公司", "台灣麥當勞餐廳股份有限公司"], "高",
     "2017 年台灣經營權移轉並更名。時間軸無重疊（台灣麥當勞 201601~201605、"
     "和德昌 201905~202607），強力佐證為同一實體。3 + 19 = 22"),
    ("富利（必勝客／肯德基）", ["富利餐飲股份有限公司", "富利食品股份有限公司"], "中",
     "時間軸接續無重疊（富利食品 201507~201607、富利餐飲 201609~202607），"
     "疑為同一實體更名，請查證。5 + 33 = 38"),
    ("威合威務", ["威合股份有限公司", "威務股份有限公司"], "中",
     "同屬 UEM EDGENTA 集團「威合威務」後勤服務，但為兩個法人且期間重疊，"
     "是否應合併須確認。35 + 20 = 55"),
]


def auto_bus_alias(name: str) -> str | None:
    """插字規則：XX汽車客運 -> XX客運（大家實際會搜的寫法）。"""
    m = re.match(r"^(.+?)汽車客運股份有限公司$", name)
    if m:
        return f"{m.group(1)}客運"
    m = re.match(r"^(.+?)汽車運輸股份有限公司$", name)
    if m:
        return f"{m.group(1)}客運"
    return None


def style_sheet(ws, widths: dict[str, int], freeze: str = "A2") -> None:
    ws.freeze_panes = freeze
    head_fill = PatternFill("solid", fgColor="D9E2F3")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = head_fill
        c.alignment = Alignment(vertical="center")
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)


def main() -> None:
    df = pd.read_csv(SHORTLIST, encoding="utf-8-sig")
    review = df[df["需人工判斷"]].copy()

    merged_names = {n for _, names, _, _ in MERGE_GROUPS for n in names}

    review["插字別名"] = review["法人名稱"].map(auto_bus_alias)

    # 分桶
    bus = review[review["插字別名"].notna()].copy()
    rest = review[review["插字別名"].isna()].copy()
    alias_rows = rest[rest["法人名稱"].isin(ALIAS)].copy()
    other = rest[~rest["法人名稱"].isin(ALIAS)].copy()

    alias_rows["建議別名"] = alias_rows["法人名稱"].map(lambda n: ALIAS[n][0])
    alias_rows["信心"] = alias_rows["法人名稱"].map(lambda n: ALIAS[n][1])
    alias_rows["需歸戶"] = alias_rows["法人名稱"].isin(merged_names).map({True: "是", False: ""})
    alias_rows["✅ 你確認的別名"] = ""
    alias_rows["備註"] = ""
    conf_order = {"高": 0, "中": 1, "待查": 2}
    alias_rows = alias_rows.sort_values(
        ["信心", "違規次數"],
        key=lambda s: s.map(conf_order) if s.name == "信心" else -s,
    )

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        # 說明
        readme = pd.DataFrame({
            "項目": [
                "資料來源", "資料範圍", "篩選門檻", "產出時間", "",
                "怎麼用", "", "分頁 1", "分頁 2", "分頁 3", "分頁 4", "分頁 5", "",
                "信心等級", "", "重要提醒",
            ],
            "說明": [
                "勞動部「違反勞動法令事業單位－勞動基準法」開放資料（data.gov.tw, dataset 109896）",
                "公告日期 2011-11-15 ~ 2026-08-15，共 77,813 筆",
                "違規次數 >= 10 次的事業單位，共 442 家",
                "2026-08-26",
                "",
                "只需要看「3_別名候選」這一頁。填「✅ 你確認的別名」欄即可，其餘分頁供參。",
                "",
                "1_歸戶合併：同一實體被拆成多個法人名，次數必須合計，否則嚴重低估",
                "2_客運插字規則：可用 regex 自動產生，不需人工建表",
                "3_別名候選：**需要你核對的主清單**",
                "4_其餘未標註：我判斷名稱本身即可搜，或未逐一檢視。有空再掃",
                "5_自動排除：保全／營造／長照等，名稱即品牌，不需別名",
                "",
                "高＝明確且廣為人知；中＝有把握但請查證；待查＝我不知道，需要你查",
                "",
                "「待查」欄位我刻意留空，沒有猜測填入。請勿把空白當成「沒有別名」。",
            ],
        })
        readme.to_excel(xw, sheet_name="0_說明", index=False)

        pd.DataFrame(
            [{"品牌": b, "應合併的法人名": " ／ ".join(names), "信心": conf, "說明": note}
             for b, names, conf, note in MERGE_GROUPS]
        ).to_excel(xw, sheet_name="1_歸戶合併", index=False)

        bus[["法人名稱", "違規次數", "插字別名", "主要主管機關"]].rename(
            columns={"插字別名": "自動產生的別名"}
        ).sort_values("違規次數", ascending=False).to_excel(
            xw, sheet_name="2_客運插字規則", index=False)

        alias_rows[["法人名稱", "違規次數", "產業推測", "建議別名", "信心",
                    "需歸戶", "✅ 你確認的別名", "備註"]].to_excel(
            xw, sheet_name="3_別名候選", index=False)

        other[["法人名稱", "違規次數", "產業推測", "主要主管機關"]].sort_values(
            "違規次數", ascending=False).to_excel(
            xw, sheet_name="4_其餘未標註", index=False)

        df[~df["需人工判斷"]][["法人名稱", "違規次數", "排除理由"]].sort_values(
            "違規次數", ascending=False).to_excel(
            xw, sheet_name="5_自動排除", index=False)

        wb = xw.book
        style_sheet(wb["0_說明"], {"A": 14, "B": 88})
        style_sheet(wb["1_歸戶合併"], {"A": 22, "B": 52, "C": 8, "D": 62})
        style_sheet(wb["2_客運插字規則"], {"A": 34, "B": 10, "C": 18, "D": 14})
        style_sheet(wb["3_別名候選"], {"A": 36, "B": 10, "C": 16, "D": 44,
                                        "E": 8, "F": 8, "G": 26, "H": 22})
        style_sheet(wb["4_其餘未標註"], {"A": 36, "B": 10, "C": 16, "D": 14})
        style_sheet(wb["5_自動排除"], {"A": 36, "B": 10, "C": 18})

        # 別名候選頁：依信心上色
        ws = wb["3_別名候選"]
        fills = {"高": "E2EFDA", "中": "FFF2CC", "待查": "FCE4E4"}
        for row in ws.iter_rows(min_row=2):
            conf = row[4].value
            if conf in fills:
                for c in row:
                    c.fill = PatternFill("solid", fgColor=fills[conf])

    print(f"已輸出：{OUT}\n")
    print(f"  1_歸戶合併      {len(MERGE_GROUPS)} 組")
    print(f"  2_客運插字規則   {len(bus)} 家（自動處理，不需人工）")
    print(f"  3_別名候選      {len(alias_rows)} 家 ← 你只要看這頁")
    for k in ("高", "中", "待查"):
        print(f"       信心 {k:<3} {(alias_rows['信心'] == k).sum():>3} 家")
    print(f"  4_其餘未標註    {len(other)} 家")
    print(f"  5_自動排除      {(~df['需人工判斷']).sum()} 家")


if __name__ == "__main__":
    main()
