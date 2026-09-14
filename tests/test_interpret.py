"""`twec.interpret` 的行為規格。

判讀層：把 `twec.roster` 歸戶出的一個雇主，套上「法條白話對照表」的白話與
嚴重度，輸出一份人看得懂的違規報告。規則是 spike/06_interpret_logic.py
用真實資料（data/lsa_violations_raw.csv + 使用者手填的白話對照表）驗證過的：

    白話：人工填了就用人工的；沒填就用這一列自己的官方描述文字（不是表格裡
    「這條底下最常見」的那句——那句可能跟這一列實際發生的事對不上）。

    嚴重度：人工填了就用人工的；沒填就用罰鍰**平均**（不是中位數——實測
    40 條項裡 27 條中位數都卡在法定最低罰鍰 20,000，分不出高下；平均會被
    累犯/加重情節個案拖高，才有鑑別力）在「有罰鍰平均資料的條項」裡切五級
    分位數。完全沒罰鍰資料的條項標「未評級（無罰鍰資料）」；法條根本不在
    白話對照表裡的標「未評級（不在表格範圍）」。

    歸戶：吃 `twec.roster.Entity`，用 `entity.names`（該雇主所有別名，含
    統編併起來的更名組）撈違規列，不是只查單一名稱字串。
"""

import csv

from twec.interpret import (
    LawEntry,
    article_of,
    build_law_table_from_data,
    build_severity_buckets,
    interpret_entity,
    load_law_table,
    normalize_law,
    normalize_lpa_law,
    parse_lpa_violation_row,
    parse_osha_law_citation,
    parse_osha_violation_row,
    parse_violation_row,
    resolve_severity,
    resolve_text,
    severity_from_fine,
)
from twec.roster import Entity


def entry(law, plain=None, manual_severity=None, fine_median=None, fine_mean=None, official_text=""):
    return LawEntry(
        law=law,
        topic="",
        plain=plain,
        manual_severity=manual_severity,
        fine_median=fine_median,
        fine_mean=fine_mean,
        official_text=official_text,
    )


class TestNormalizingLawStrings:
    """`build_law_workbook.py` 已經踩過的坑，判讀層讀同一份原始資料，得踩過同一批。"""

    def test_collapses_short_form_into_full_form(self):
        assert normalize_law("勞基法第24條第1項") == "勞動基準法第24條第1項"

    def test_removes_duplicated_trailing_law_name(self):
        # 全量 62 對，尾巴重複串接法規名稱。
        assert normalize_law("勞動基準法第24條勞動基準法勞動基準法") == "勞動基準法第24條"

    def test_extracts_the_article_number(self):
        assert article_of("勞動基準法第24條第1項") == 24

    def test_article_of_returns_none_for_unrecognized_strings(self):
        assert article_of("性別平等工作法第7條") is None


class TestNormalizingLpaLawStrings:
    """勞退資料的法規字串本身就乾淨（全量掃過只有 9 列頭尾夾雜換行），不需要
    勞基法那套簡稱／重複尾巴清理，只需去空白。"""

    def test_cleans_whitespace_and_keeps_the_law_string(self):
        assert normalize_lpa_law("勞工退休金條例第19條第1項") == "勞工退休金條例第19條第1項"

    def test_strips_stray_newlines(self):
        assert normalize_lpa_law("勞工退休金條例\n第12條第2項") == "勞工退休金條例第12條第2項"


class TestParsingAViolationRow:
    """`違法法規法條` 與 `違反法規內容` 是兩串平行的 `;` 分隔字串。"""

    def test_pairs_up_laws_and_texts(self):
        row = {
            "違法法規法條": "勞動基準法第24條第1項;勞動基準法第30條第6項",
            "違反法規內容": "延長工作時間未依規定加給工資;未逐日記載勞工出勤情形",
            "罰鍰金額": "20000",
        }

        pairs = parse_violation_row(row)

        assert pairs == [
            ("勞動基準法第24條第1項", "延長工作時間未依規定加給工資", 20000),
            ("勞動基準法第30條第6項", "未逐日記載勞工出勤情形", 20000),
        ]

    def test_returns_none_when_law_and_text_counts_disagree(self):
        # 數量對不上，無法確定哪句對哪條，整列跳過不猜（全量 3.87%）。
        row = {
            "違法法規法條": "勞動基準法第24條第1項;勞動基準法第30條第6項",
            "違反法規內容": "延長工作時間未依規定加給工資",
            "罰鍰金額": "20000",
        }

        assert parse_violation_row(row) is None

    def test_missing_fine_becomes_none_not_zero(self):
        row = {"違法法規法條": "勞動基準法第24條", "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": ""}

        assert parse_violation_row(row)[0][2] is None


class TestParsingALpaViolationRow:
    """勞退的欄位形狀跟勞基法一樣（`;` 分隔的平行字串），差別只在罰鍰欄位
    叫「處分金額或滯納金」，且大部分是欠費滯納金不是裁罰。"""

    def test_pairs_up_laws_and_texts_using_the_lpa_fine_column(self):
        row = {
            "違法法規法條": "勞工退休金條例第19條第1項",
            "違反法規內容": "雇主應為適用勞退新制之勞工按月提繳退休金，未依規定按月提繳。",
            "處分金額或滯納金": "15000",
        }

        pairs = parse_lpa_violation_row(row)

        assert pairs == [
            ("勞工退休金條例第19條第1項", "雇主應為適用勞退新制之勞工按月提繳退休金,未依規定按月提繳", 15000),
        ]

    def test_returns_none_when_law_and_text_counts_disagree(self):
        row = {
            "違法法規法條": "勞工退休金條例第12條第1項;勞工退休金條例第12條第2項",
            "違反法規內容": "雇主未依規定於終止勞動契約後30日內發給勞工退休金",
            "處分金額或滯納金": "300000",
        }

        assert parse_lpa_violation_row(row) is None


class TestParsingAnOshaLawCitation:
    """職安的法條欄位常見「子法暨母法」引用（子法授權自母法概括義務條款），
    使用者決定：視為一筆違規，用子法（較具體的那個引用）代表整列。

    子法一律排在「暨」前面（全量掃過 65,016 個「暨」區段裡 98.4% 如此），
    唯一例外是母法自己「先引細款、後引概括款」（如「第37條第2項第3款暨
    第37條第2項」），此時取「暨」前面那個一樣是較具體的那個，規則不用分岔。
    """

    def test_plain_single_law_citation_passes_through(self):
        assert parse_osha_law_citation("職業安全衛生法第37條第2項第1款") == "職業安全衛生法第37條第2項第1款"

    def test_takes_the_subordinate_law_before_暨(self):
        assert (
            parse_osha_law_citation("營造安全衛生設施標準第19條第1項暨職業安全衛生法第6條第1項")
            == "營造安全衛生設施標準第19條第1項"
        )

    def test_takes_the_more_specific_citation_when_both_sides_are_the_base_law(self):
        assert (
            parse_osha_law_citation("職業安全衛生法第37條第2項第3款暨職業安全衛生法第37條第2項")
            == "職業安全衛生法第37條第2項第3款"
        )

    def test_ignores_everything_after_a_semicolon(self):
        # 分號後是同一列的其他子違規；列層級判讀只取第一個。
        assert (
            parse_osha_law_citation("職業安全衛生法第6條第1項;職業安全衛生設施規則第118條")
            == "職業安全衛生法第6條第1項"
        )

    def test_strips_a_leading_list_marker_and_a_line_break(self):
        # 「1.」「2.」是資料裡混進來的列點標記，不是法條的一部分；換行是另一種
        # 分隔符，跟分號一樣只取第一段。
        assert (
            parse_osha_law_citation("1.營造安全衛生設施標準第129條第09款暨職業安全衛生法第6條第1項第5款\n2.職業安全衛生法第27條第1項第3款")
            == "營造安全衛生設施標準第129條第09款"
        )


class TestParsingAnOshaViolationRow:
    """職安走列層級判讀（使用者決定）：一列違規 CSV = 一筆 InterpretedItem，
    `違反法規內容` 整欄當作這一列的文字，不像勞基法／勞退拆成多筆。"""

    def test_returns_exactly_one_item_using_the_child_law_and_whole_text(self):
        row = {
            "違法法規法條": "營造安全衛生設施標準第19條第1項暨職業安全衛生法第6條第1項",
            "違反法規內容": "對於高度2公尺以上之外牆施工架開口部分等場所作業,未於該處設置護欄、護蓋或安全網等防護設備",
            "罰鍰金額": "250000",
        }

        pairs = parse_osha_violation_row(row)

        assert pairs == [
            (
                "營造安全衛生設施標準第19條第1項",
                "對於高度2公尺以上之外牆施工架開口部分等場所作業,未於該處設置護欄、護蓋或安全網等防護設備",
                250000,
            ),
        ]

    def test_missing_fine_becomes_none_not_zero(self):
        row = {"違法法規法條": "職業安全衛生法第6條第1項", "違反法規內容": "違規描述", "罰鍰金額": ""}

        assert parse_osha_violation_row(row)[0][2] is None


class TestResolvingPlainText:
    """白話 fallback：人工白話 → 這一列自己的官方描述，不是表格裡「最常見」那句。"""

    def test_uses_manual_plain_text_when_filled(self):
        e = entry("勞動基準法第24條第1項", plain="加班沒給加班費")

        text, source = resolve_text(e, "延長工作時間未依規定加給工資")

        assert text == "加班沒給加班費"
        assert source == "人工白話"

    def test_falls_back_to_this_rows_own_text_when_plain_is_blank(self):
        e = entry("勞動基準法第24條第1項", plain=None, official_text="這是表格裡最常見的那句，不該被選中")

        text, source = resolve_text(e, "這一列實際發生的官方描述")

        assert text == "這一列實際發生的官方描述"
        assert source != "人工白話"

    def test_falls_back_to_the_rows_text_when_the_law_is_not_in_the_table(self):
        text, source = resolve_text(None, "這一列實際發生的官方描述")

        assert text == "這一列實際發生的官方描述"


class TestSeverityBuckets:
    """罰鍰平均在已知資料裡的相對位置，切成五級。"""

    def test_ties_at_the_statutory_minimum_no_longer_collapse_into_one_bucket(self):
        # 這是原型踩過的坑：改用中位數會讓大多數條項擠在同一級。
        # 平均值因為個案罰鍰不同而有展開，才能切出五個不同的級距。
        table = {
            "A": entry("A", fine_mean=10000),
            "B": entry("B", fine_mean=20000),
            "C": entry("C", fine_mean=25000),
            "D": entry("D", fine_mean=30000),
            "E": entry("E", fine_mean=200000),
        }

        buckets = build_severity_buckets(table)
        severities = {law: severity_from_fine(e.fine_mean, buckets) for law, e in table.items()}

        assert severities["A"] < severities["E"]
        assert len(set(severities.values())) > 1

    def test_returns_no_buckets_when_fewer_than_five_entries_have_fine_data(self):
        table = {"A": entry("A", fine_mean=10000), "B": entry("B", fine_mean=20000)}

        assert build_severity_buckets(table) == []


class TestResolvingSeverity:
    def test_manual_severity_wins_over_any_fine_data(self):
        e = entry("A", manual_severity=3, fine_mean=999999)

        severity, source = resolve_severity(e, buckets=[10000, 20000, 30000, 40000])

        assert severity == 3
        assert source == "人工"

    def test_derives_severity_from_fine_mean_when_manual_is_blank(self):
        e = entry("A", manual_severity=None, fine_mean=50000)

        severity, source = resolve_severity(e, buckets=[10000, 20000, 30000, 40000])

        assert severity == 5
        assert source == "罰鍰平均推算"

    def test_unrated_when_law_has_no_fine_data_at_all(self):
        e = entry("A", manual_severity=None, fine_mean=None)

        severity, source = resolve_severity(e, buckets=[10000, 20000, 30000, 40000])

        assert severity is None
        assert source == "未評級（無罰鍰資料）"

    def test_unrated_when_law_is_not_in_the_table(self):
        severity, source = resolve_severity(None, buckets=[10000, 20000, 30000, 40000])

        assert severity is None
        assert source == "未評級（不在表格範圍）"


class TestInterpretingAnEntity:
    """吃 Entity（含所有別名），套白話與嚴重度，輸出一份報告。"""

    def write_csv(self, tmp_path, rows):
        path = tmp_path / "violations.csv"
        header = [
            "主管機關", "公告日期", "處分日期", "處分字號",
            "事業單位名稱或負責人", "違法法規法條", "違反法規內容",
            "罰鍰金額", "備註說明",
        ]
        lines = [",".join(header)]
        for r in rows:
            lines.append(",".join(r.get(h, "") for h in header))
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def entity(self, *names):
        return Entity(key=names[0], key_kind="name", uniform_no=None, names=tuple(names), count=0)

    def test_collects_violations_across_all_of_the_entitys_names(self, tmp_path):
        # 統編併起來的更名組：舊名跟新名都要撈進同一份報告。
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
            {"事業單位名稱或負責人": "台灣麥當勞餐廳股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
            {"事業單位名稱或負責人": "無關的公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司", "台灣麥當勞餐廳股份有限公司")

        report = interpret_entity(entity, source, law_table={}, buckets=[])

        assert len(report.items) == 2

    def test_skips_rows_with_an_empty_name(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司")

        report = interpret_entity(entity, source, law_table={}, buckets=[])

        assert report.items == []

    def test_skips_rows_where_law_and_text_counts_disagree(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "和德昌股份有限公司",
             "違法法規法條": "勞動基準法第24條;勞動基準法第30條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司")

        report = interpret_entity(entity, source, law_table={}, buckets=[])

        assert report.items == []

    def test_applies_the_law_table_to_matched_items(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司")
        table = {"勞動基準法第24條": entry("勞動基準法第24條", plain="加班沒給加班費", manual_severity=4)}

        report = interpret_entity(entity, source, law_table=table, buckets=[])

        item = report.items[0]
        assert item.text == "加班沒給加班費"
        assert item.severity == 4

    def test_flags_repeat_offenses_on_the_same_law(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第30條第6項",
             "違反法規內容": "未逐日記載勞工出勤情形", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司")

        report = interpret_entity(entity, source, law_table={}, buckets=[])

        assert report.repeat_offenses == {"勞動基準法第24條": 2}

    def test_counts_disputed_rows_from_the_note_column(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000",
             "備註說明": "訴願中"},
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞動基準法第24條",
             "違反法規內容": "延長工作時間未依規定加給工資", "罰鍰金額": "20000"},
        ])
        entity = self.entity("和德昌股份有限公司")

        report = interpret_entity(entity, source, law_table={}, buckets=[])

        assert report.disputed_count == 1
        disputed_items = [i for i in report.items if i.disputed]
        assert len(disputed_items) == 1


class TestInterpretingAnEntityAcrossRegimes:
    """待辦第 8 項：判讀層原本只吃勞基法 CSV，串接勞退／職安後改用 `parse_row`
    參數挑不同的展開規則，其餘（歸戶、累犯、行政救濟中）邏輯共用不變。"""

    def entity(self, *names):
        return Entity(key=names[0], key_kind="name", uniform_no=None, names=tuple(names), count=0)

    def write_csv(self, tmp_path, header, rows):
        path = tmp_path / "violations.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for r in rows:
                writer.writerow([r.get(h, "") for h in header])
        return path

    def test_uses_parse_row_to_read_the_lpa_fine_column(self, tmp_path):
        header = [
            "主管機關", "公告日期", "處分日期", "處分字號",
            "事業單位名稱或負責人", "違法法規法條", "違反法規內容",
            "處分金額或滯納金", "備註說明",
        ]
        source = self.write_csv(tmp_path, header, [
            {"事業單位名稱或負責人": "和德昌股份有限公司", "違法法規法條": "勞工退休金條例第19條第1項",
             "違反法規內容": "雇主應為適用勞退新制之勞工按月提繳退休金,未依規定按月提繳", "處分金額或滯納金": "15000"},
        ])
        entity = self.entity("和德昌股份有限公司")

        report = interpret_entity(
            entity, source, law_table={}, buckets=[], parse_row=parse_lpa_violation_row,
        )

        assert len(report.items) == 1
        assert report.items[0].fine == 15000
        assert report.items[0].law == "勞工退休金條例第19條第1項"

    def test_uses_parse_row_for_row_level_osha_items(self, tmp_path):
        header = [
            "主管機關", "公告日期", "處分日期", "處分字號",
            "事業單位名稱或負責人", "違法法規法條", "違反法規內容",
            "罰鍰金額", "備註說明",
        ]
        source = self.write_csv(tmp_path, header, [
            {"事業單位名稱或負責人": "崇雅營造有限公司",
             "違法法規法條": "營造安全衛生設施標準第19條第1項暨職業安全衛生法第6條第1項",
             "違反法規內容": "對於高度2公尺以上之屋頂等場所作業,未設置護欄、護蓋或安全網等防護設備",
             "罰鍰金額": "250000"},
        ])
        entity = self.entity("崇雅營造有限公司")

        report = interpret_entity(
            entity, source, law_table={}, buckets=[], parse_row=parse_osha_violation_row,
        )

        assert len(report.items) == 1
        assert report.items[0].law == "營造安全衛生設施標準第19條第1項"


class TestBuildingTheLawTableFromData:
    """勞退／職安沒有像勞基法那樣的人工白話對照表（待辦第 4 項的精神：不強求
    填表也能跑），嚴重度的罰鍰統計改直接從原始 CSV 算，`plain`／`manual_severity`
    永遠是 None，全部走 fallback。跟 `scripts/build_law_workbook.py` 一樣，
    只取「整列只引用這一條」的列計算罰鍰，避免把合併列的罰鍰誤算給某一條。
    """

    def write_csv(self, tmp_path, rows):
        path = tmp_path / "violations.csv"
        header = ["違法法規法條", "違反法規內容", "處分金額或滯納金"]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for r in rows:
                writer.writerow([r.get(h, "") for h in header])
        return path

    def test_computes_fine_mean_from_single_law_rows_only(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"違法法規法條": "勞工退休金條例第19條第1項", "違反法規內容": "未依規定按月提繳", "處分金額或滯納金": "10000"},
            {"違法法規法條": "勞工退休金條例第19條第1項", "違反法規內容": "未依規定按月提繳", "處分金額或滯納金": "30000"},
            # 合併列：這一列的罰鍰不能確定歸給哪一條，排除在統計之外。
            {"違法法規法條": "勞工退休金條例第12條第1項;勞工退休金條例第19條第1項",
             "違反法規內容": "a;b", "處分金額或滯納金": "999999"},
        ])

        table = build_law_table_from_data(source, parse_row=parse_lpa_violation_row)

        assert table["勞工退休金條例第19條第1項"].fine_mean == 20000

    def test_entries_have_no_manual_fields_so_the_fallback_path_always_runs(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"違法法規法條": "勞工退休金條例第19條第1項", "違反法規內容": "未依規定按月提繳", "處分金額或滯納金": "10000"},
        ])

        table = build_law_table_from_data(source, parse_row=parse_lpa_violation_row)

        entry = table["勞工退休金條例第19條第1項"]
        assert entry.plain is None
        assert entry.manual_severity is None

    def test_laws_with_no_alone_fine_data_still_appear_with_none_mean(self, tmp_path):
        source = self.write_csv(tmp_path, [
            {"違法法規法條": "勞工退休金條例第12條第1項;勞工退休金條例第19條第1項",
             "違反法規內容": "a;b", "處分金額或滯納金": "999999"},
        ])

        table = build_law_table_from_data(source, parse_row=parse_lpa_violation_row)

        assert table["勞工退休金條例第12條第1項"].fine_mean is None


class TestLoadingTheLawTableFromExcel:
    """讀 `scripts/build_law_workbook.py` 產出的「條項層（必填）」分頁。"""

    def write_workbook(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "條項層（必填）"
        ws.append([
            "條", "主題", "法條", "引用次數", "佔勞基法全體",
            "句型數", "單條列數", "罰鍰中位數", "罰鍰平均",
            "最常見的官方描述", "白話說明（一句話）", "嚴重度", "判讀備註",
        ])
        ws.append([
            "第 24 條", "延長工時工資（加班費）", "勞動基準法第24條", 10350, 0.1,
            180, 6444, 20000, 30442,
            "延長工作時間未依規定加給工資", "加班沒給加班費", 4, None,
        ])
        ws.append([
            "第 24 條", "延長工時工資（加班費）", "勞動基準法第24條第3項", 1, 0.0,
            1, 1, None, None,
            "延長工作時間未依規定加給工資", None, None, None,
        ])
        path = tmp_path / "law.xlsx"
        wb.save(path)
        return path

    def test_reads_each_clause_row_into_a_law_entry(self, tmp_path):
        table = load_law_table(self.write_workbook(tmp_path))

        assert set(table) == {"勞動基準法第24條", "勞動基準法第24條第3項"}
        first = table["勞動基準法第24條"]
        assert first.plain == "加班沒給加班費"
        assert first.manual_severity == 4
        assert first.fine_mean == 30442

    def test_blank_optional_cells_become_none(self, tmp_path):
        table = load_law_table(self.write_workbook(tmp_path))

        third = table["勞動基準法第24條第3項"]
        assert third.plain is None
        assert third.manual_severity is None
        assert third.fine_mean is None
