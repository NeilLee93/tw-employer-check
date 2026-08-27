# tw-employer-check

查詢台灣雇主的勞動法違規紀錄，並用勞動法視角判讀「這代表什麼」。給求職者、人資與勞動法工作者使用。

> **目前狀態：實作起步。** 歸戶主流程（`twec/names.py` → `twec/uniform_no.py` → `twec/roster.py`）
> 已完整串起來並通過全量驗收，判讀層與 CLI 尚未實作。`spike/` 內為拋棄式驗證腳本，不再維護。
> 驗證結論見 [`可行性調查.md`](可行性調查.md)，進度與待辦見 [`交接文件.md`](交接文件.md)。

---

## 功能特色

以下為規劃中的功能，尚未實作：

- **跨法規彙整**：一次看完勞基法、就服法、性平法、勞退條例、職災保護法、工會法、中高齡就業法、職安法的違規紀錄
- **法條白話化**：把「勞動基準法第 22 條第 2 項」翻成「薪水沒有全額直接給你」，並標註嚴重度權重
- **品牌名查詢**：搜「家樂福」也能查到「家福股份有限公司」的紀錄（實測差距為 3 筆 vs 143 筆）
- **累犯與模式辨識**：反覆違反同一條 = 明知故犯；跨多部法規有紀錄 = 系統性問題
- **完全本機**：資料下載後離線查詢，不上雲

---

## 系統需求

| 項目 | 需求 |
|---|---|
| 作業系統 | Windows / macOS / Linux |
| Python | 3.12 以上（開發環境為 3.12.10） |
| 主要套件 | pandas 3.x |
| 網路 | 僅下載資料時需要，查詢階段離線可用 |
| API 金鑰 | 不需要 |

---

## 快速啟動

```bash
# 1. 安裝（含測試相依）
pip install -e ".[dev]"

# 2. 跑測試
pytest

# 3. 下載勞動部原始資料（約 16.5 MB）
curl -o data/lsa_violations_raw.csv \
  https://apiservice.mol.gov.tw/OdService/download/A17000000J-030225-svj

# 4. 拿全量資料驗收名稱模組
python scripts/audit_names.py

# 5.（選用）下載財政部稅籍三檔以補統一編號，解開後約 380 MB
curl -o data/raw/fia_BGMOPEN1.zip  https://eip.fia.gov.tw/data/BGMOPEN1.zip
curl -o data/raw/fia_BGMOPEN1X.csv https://eip.fia.gov.tw/data/BGMOPEN1X.csv
curl -o data/raw/fia_BGMOPEN1Y.csv https://eip.fia.gov.tw/data/BGMOPEN1Y.csv
# zip 內檔名為 BGMOPEN1.csv，需更名為 fia_BGMOPEN1.csv

python scripts/build_uniform_no.py
```

### 使用名稱正規化模組

```python
from twec.names import normalize, split_entity

split_entity(normalize("優志旺股份有限公司(渡&#37001;剛德)"))
# EntityName(org='優志旺股份有限公司', person='渡邉剛德', kind='company', related_org=None, site=None)

split_entity(normalize("友達光電股份有限公司台中廠"))
# EntityName(org='友達光電股份有限公司', person=None, kind='company', related_org=None, site='台中廠')

split_entity(normalize("中華航空股份有限公司企業工會"))
# EntityName(org='中華航空股份有限公司企業工會', person=None, kind='union',
#            related_org='中華航空股份有限公司', site=None)
```

`org` 是歸戶用的 key。工會依工會法是獨立法人，不併入母公司，改以 `related_org` 標註關聯；
廠區與分公司屬同一法人，併入母公司並以 `site` 保留明細。

### 補統一編號

```python
from twec.uniform_no import Registry

registry = Registry.from_dir("data/raw")     # 讀 389 萬列稅籍資料，約 2 分鐘

registry.resolve("和德昌股份有限公司").uniform_no
# '12411160'

registry.resolve("香港商世界健身事業有限公司")
# Resolution(uniform_no='27940499', method='hq_via_prefix', ...)
# 外商母公司無台灣稅籍，經各分公司的「總機構統一編號」指回在台總機構

registry.resolve("交通部台灣鐵路管理局").uniform_no
# None —— 政府機關沒有營業稅籍，查不到就不給，不猜
```

### 歸戶（一個雇主一列）

```python
from twec.roster import Roster, count_orgs
from twec.uniform_no import Registry

orgs = count_orgs("data/lsa_violations_raw.csv")   # org -> 裁處列數
roster = Roster.build(orgs, Registry.from_dir("data/raw"))

roster.of("台灣麥當勞餐廳股份有限公司")
# Entity(key='12411160', key_kind='uniform_no', uniform_no='12411160',
#        names=('和德昌股份有限公司', '台灣麥當勞餐廳股份有限公司'), count=22)

roster.of("交通部台灣鐵路管理局").key_kind
# 'name' —— 沒有統編就用名稱字串當 key，不與任何人合併

len(roster.renamed)
# 202 —— 統編直接指出的更名組數
```

合併規則只有一條，而且刻意保守：**只有 `high_confidence` 的統編才拿來合併**。
`sole_operating`（同名多統編、只剩一家營業中）的統編仍寫進 `uniform_no` 當加值欄位，
但不合併——分裂了還能靠別名表補，錯併就救不回來了。

統編是加值欄位，**不取代 `org`**。勞基法資料裡 79.4% 的事業單位補得上，
補不上的多為政府機關、公立學校醫院與聯合會計師事務所，名稱字串仍是備援 key。

Windows PowerShell 下載改用：

```powershell
Invoke-WebRequest -Uri "https://apiservice.mol.gov.tw/OdService/download/A17000000J-030225-svj" `
  -OutFile "data\lsa_violations_raw.csv"
```

> 若終端機出現中文亂碼，先設 `$env:PYTHONIOENCODING='utf-8'`。

---

## 目錄結構

```
tw-employer-check/
├── README.md              本檔
├── CHANGELOG.md           版本變更記錄
├── 可行性調查.md           資料源盤點、前案調查、實測結果（核心文件）
├── 交接文件.md             冷啟動用：目前進度、待辦、已知坑
├── pyproject.toml         套件與測試設定
├── twec/                  正式模組（核心邏輯，不綁 UI）
│   ├── names.py           事業單位名稱正規化與拆解
│   ├── uniform_no.py      用財政部稅籍資料補統一編號
│   └── roster.py          歸戶：把 org 收斂成「一個雇主一列」
├── tests/
│   ├── test_names.py      twec.names 的行為規格
│   ├── test_uniform_no.py twec.uniform_no 的行為規格
│   └── test_roster.py     twec.roster 的行為規格
├── scripts/
│   ├── audit_names.py     拿全量資料驗收名稱模組
│   ├── build_uniform_no.py 全量比對統編，產出對照表
│   ├── build_roster.py    跑完整條歸戶主流程，產出雇主名冊
│   └── build_law_workbook.py 產出法條白話化的填寫用 Excel
├── data/                  原始 CSV 不進版控，衍生產出進版控
│   ├── lsa_violations_raw.csv      勞動部原始資料（16.5 MB）
│   ├── raw/                        其餘 7 個資料集＋財政部稅籍三檔（不進版控）
│   ├── uniform_no_map.csv          org → 統編對照表（不進版控，可重生）
│   ├── roster.csv                  歸戶後的雇主名冊（不進版控，可重生）
│   ├── brand_alias_shortlist.csv   442 家分桶結果
│   ├── unknowns_triage.csv         待查公司縣市分診
│   └── 品牌別名核對表.xlsx          人工核對用
└── spike/                 拋棄式驗證腳本，已凍結不再維護
    ├── 01_name_matching_spike.py    名稱比對可行性
    ├── 02_followups.py              資料品質追查
    ├── 03_brand_alias_shortlist.py  442 家分桶
    ├── 04_build_alias_workbook.py   產出核對用 Excel（含別名表資產）
    └── 05_triage_unknowns.py        待查公司分診
```

---

## 資料來源

勞動部「違反勞動法令事業單位」開放資料，共 8 個資料集：

| dataset_id | 名稱 | 更新頻率 |
|---|---|---|
| 109896 | 勞動基準法 | 不定期 |
| 110908 | 就業服務法 | 不定期 |
| 109897 | 性別平等工作法 | 不定期 |
| 109898 | 勞工退休金條例 | 每 1 日 |
| 156800 | 勞工職業災害保險及保護法 | 每 1 月 |
| 156904 | 中高齡者及高齡者就業促進法 | 不定期 |
| 166670 | 工會法 | 不定期 |
| 155978 | 職業安全衛生法（職安署） | 每 1 日 |

補統一編號另用財政部財政資訊中心資料：

| dataset_id | 名稱 | 列數 | 更新頻率 |
|---|---|---:|---|
| 9400 | 全國營業(稅籍)登記資料集（營業中） | 171 萬 | 每 1 日 |
| 75140 | 全國營業(稅籍)登記(停業)資料集 | 12 萬 | 每 1 日 |
| 75141 | 全國營業(稅籍)登記(停業以外之非營業中)資料集 | 206 萬 | 每 1 月 |

授權：兩邊皆為政府資料開放授權條款－第 1 版。使用時須標示：

> 資料來源：勞動部「違反勞動法令事業單位」開放資料（data.gov.tw）
> 資料來源：財政部財政資訊中心「全國營業(稅籍)登記資料集」（data.gov.tw）

---

## 注意事項 / 已知限制

- **罰鍰金額欄位 2020 年以前為空**。涉及金額的分析起點必須設在 2021 年（約 44,000 筆）；純次數分析可用 2016 年起全量。
- **資料無統一編號欄位**。已用財政部稅籍資料補上 79.4%，補不上的 20.6% 是結構性的
  （政府機關、公立學校醫院、聯合會計師事務所本體無營業稅籍），名稱字串仍是備援 key。
- **品牌名 ≠ 法人名**，需人工維護對照表，否則知名連鎖品牌會嚴重漏報。
- **裁處未確定亦可能公布**（資料中可見「行政救濟中」「訴願駁回」等備註），查詢結果須據實標示狀態，不得逕稱該公司「違法」。
- 資料含負責人姓名，屬政府依法公布事項；若對外發布本工具，二次利用範圍須再行確認。

---

## 相依套件

| 套件 | 用途 |
|---|---|
| pandas | 資料載入、聚合分析 |
| openpyxl | 產出人工填寫用的 Excel |
| pytest | 測試（開發用） |
