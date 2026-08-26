"""`twec.names` 的行為規格。

測試打在兩個 seam 上：
  - normalize(raw) -> str
  - split_entity(normalized) -> EntityName

期望值來源是勞動部原始資料裡的真實字串，不是從實作反推的。
"""

from twec.names import normalize, split_entity


class TestNormalizeDecodesHtmlEntities:
    """原始 CSV 有 437 個未解碼的數值 entity 與 68 個 &nbsp;，
    影響 198 列的公司名稱本體。不解碼會讓這些公司歸戶失敗。"""

    def test_decodes_numeric_entity_in_company_name(self):
        assert normalize("&#32675;益企業有限公司") == "羣益企業有限公司"

    def test_decodes_numeric_entity_mid_name(self):
        assert normalize("裕&#29641;遊覽車客運公司") == "裕珉遊覽車客運公司"

    def test_decodes_multiple_entities_in_one_name(self):
        assert normalize("黃麗靜即旺民&#34886;彩&#21173;行") == "黃麗靜即旺民衆彩劵行"

    def test_drops_entity_with_invalid_codepoint(self):
        # &#2013268209; 超出 Unicode 範圍，html.unescape 會吐出 U+FFFD。
        # 留著它會讓名稱永遠對不上，丟掉才有機會靠其餘字元比對。
        assert normalize("測試&#2013268209;有限公司") == "測試有限公司"


class TestNormalizeStripsWhitespace:
    """`事業單位名稱或負責人` 有 863 列含換行、1,308 列含空白（含全形 U+3000）。"""

    def test_removes_newline_inside_field(self):
        assert normalize("基隆汽車客運股份有限公司\n(呂奇&#23791;)") == "基隆汽車客運股份有限公司(呂奇峯)"

    def test_removes_fullwidth_space(self):
        assert normalize("台灣　電力股份有限公司") == "台灣電力股份有限公司"

    def test_removes_space_inside_parenthesis(self):
        assert normalize("峰瑞科技有限公司( 林&#23791;旭)") == "峰瑞科技有限公司(林峯旭)"

    def test_nbsp_entity_becomes_nothing_not_a_space(self):
        # &nbsp; 解碼後是 U+00A0，必須被當成空白清掉，
        # 否則會殘留在公司名稱裡造成歸戶失敗。
        assert normalize("某某有限公司&nbsp;(王小明)") == "某某有限公司(王小明)"


class TestNormalizeUnifiesVariantForms:
    """含「臺」1,428 列、含「台」4,090 列，不統一會分裂成兩家。"""

    def test_unifies_tai_variant(self):
        assert normalize("臺灣中油股份有限公司") == "台灣中油股份有限公司"

    def test_converts_fullwidth_digits_and_letters(self):
        assert normalize("ＡＢＣ１２３有限公司") == "ABC123有限公司"


class TestNormalizeIsIdempotent:
    """正規化會被反覆套用在不同層（載入、查詢輸入、別名表），
    跑兩次必須與跑一次相同，否則結果依呼叫次數而變。"""

    def test_running_twice_matches_running_once(self):
        for raw in [
            "臺灣　電力股份有限公司",
            "&#32675;益企業有限公司",
            "某某有限公司&nbsp;(王小明)",
            "測試&#2013268209;有限公司",
        ]:
            assert normalize(normalize(raw)) == normalize(raw)


class TestSplitEntityRemovesResponsiblePerson:
    """59,181 列（76.1%）含括號，其中 96.9% 括號內是負責人姓名。
    負責人會換人，公司不會，所以歸戶 key 必須把人名拿掉。"""

    def test_strips_trailing_person_in_parenthesis(self):
        e = split_entity("優志旺股份有限公司(渡邉剛德)")
        assert e.org == "優志旺股份有限公司"
        assert e.person == "渡邉剛德"

    def test_strips_nested_parenthesis_person(self):
        # 589 列有巢狀括號，舊的 strip_paren 完全抓不到。
        e = split_entity("台灣超捷國際股份有限公司(畢揚賀(JamesEricBjornholt))")
        assert e.org == "台灣超捷國際股份有限公司"
        assert e.person == "畢揚賀(JamesEricBjornholt)"

    def test_strips_person_annotated_with_role(self):
        e = split_entity("関山三八有限公司(謝幸延(清算人))")
        assert e.org == "関山三八有限公司"
        assert e.person == "謝幸延(清算人)"


class TestSplitEntityKeepsInstitutionTypeMarker:
    """長照機構的名稱本體就含「(養護型)」，那是機構類型不是負責人。
    剝掉會把「晨閔老人長期照顧中心(養護型)」和同名的其他型別混為一談。
    全資料集裡以「型」結尾的括號內容共 85 列，全部是類型註記，無人名誤入。"""

    def test_keeps_yanghu_type_marker(self):
        e = split_entity("彰化縣私立晨閔老人長期照顧中心(養護型)")
        assert e.org == "彰化縣私立晨閔老人長期照顧中心(養護型)"
        assert e.person is None

    def test_keeps_long_term_care_type_marker(self):
        e = split_entity("新北市私立長勤老人長期照顧中心(長期照顧型)")
        assert e.org == "新北市私立長勤老人長期照顧中心(長期照顧型)"
        assert e.person is None


class TestSplitEntityKeepsUnionSeparate:
    """企業工會依工會法是獨立法人，雇主是工會本身而非公司。
    求職者查中華航空時不該看到工會的裁罰紀錄，所以不歸戶到母公司，
    但保留 related_org 讓報告能標註關聯。"""

    def test_enterprise_union_is_its_own_entity(self):
        e = split_entity("中華航空股份有限公司企業工會")
        assert e.org == "中華航空股份有限公司企業工會"
        assert e.kind == "union"

    def test_enterprise_union_records_parent_for_cross_reference(self):
        e = split_entity("中華航空股份有限公司企業工會")
        assert e.related_org == "中華航空股份有限公司"

    def test_union_with_locality_prefix_still_resolves_parent(self):
        e = split_entity("台中市漢翔航空工業股份有限公司企業工會")
        assert e.kind == "union"
        assert e.related_org == "台中市漢翔航空工業股份有限公司"

    def test_ordinary_company_is_not_a_union(self):
        assert split_entity("優志旺股份有限公司(渡邉剛德)").kind == "company"


class TestSplitEntityMergesSitesIntoParent:
    """廠區與分公司歸戶到母公司（同一法人），但 site 保留明細供報告拆分。
    勞基法資料裡這類共 1,662 列，其中「台灣分公司」單一形態就 645 列。"""

    def test_merges_factory_site(self):
        e = split_entity("友達光電股份有限公司台中廠")
        assert e.org == "友達光電股份有限公司"
        assert e.site == "台中廠"

    def test_merges_branch_office(self):
        e = split_entity("香港商世界健身事業有限公司台灣分公司")
        assert e.org == "香港商世界健身事業有限公司"
        assert e.site == "台灣分公司"

    def test_merges_numbered_factory(self):
        e = split_entity("台灣積體電路製造股份有限公司先進封測五廠")
        assert e.org == "台灣積體電路製造股份有限公司"
        assert e.site == "先進封測五廠"

    def test_merges_affiliated_institution(self):
        e = split_entity("耀聖資訊科技股份有限公司附設桃園市私立富安居家長照機構")
        assert e.org == "耀聖資訊科技股份有限公司"
        assert e.site == "附設桃園市私立富安居家長照機構"

    def test_site_is_none_when_name_ends_at_suffix(self):
        assert split_entity("友達光電股份有限公司").site is None

    def test_union_is_not_treated_as_a_site(self):
        # 「企業工會」的判斷必須早於廠區，否則會被誤併進母公司。
        e = split_entity("中華航空股份有限公司企業工會")
        assert e.site is None
        assert e.org == "中華航空股份有限公司企業工會"


class TestSplitEntityHandlesUnparenthesisedPerson:
    """交接文件坑 #2：負責人姓名有時沒有括號、直接串接在公司名後面。
    不處理會讓同一家公司因換負責人而裂成好幾個實體。"""

    def test_strips_person_appended_without_parenthesis(self):
        e = split_entity("玖盛公寓大廈管理維護有限公司劉國光")
        assert e.org == "玖盛公寓大廈管理維護有限公司"
        assert e.person == "劉國光"

    def test_strips_person_after_transport_company(self):
        e = split_entity("漢程汽車客運股份有限公司楊豐文")
        assert e.org == "漢程汽車客運股份有限公司"
        assert e.person == "楊豐文"


class TestSplitEntityDoesNotDamageLegitimateNames:
    """公司名本身就以型態關鍵字結尾時不能亂切，
    否則「笨蛋工作室有限公司」會被砍成「笨蛋工作室」。"""

    def test_keeps_name_that_ends_with_suffix(self):
        assert split_entity("笨蛋工作室有限公司").org == "笨蛋工作室有限公司"

    def test_keeps_name_with_two_stacked_suffixes(self):
        assert split_entity("武德水電商行有限公司").org == "武德水電商行有限公司"

    def test_keeps_sole_proprietor_ji_form(self):
        # 「即」型自然人商號佔 16.7%，本體是商號名，不能當成負責人切掉。
        assert split_entity("連進企業社即陳連進").org == "連進企業社即陳連進"

    def test_leaves_unrecognised_tail_attached(self):
        # 分不出來的殘餘寧可留著（造成分裂），也不要亂切（造成錯併）。
        assert split_entity("台隆手創館股份有限公司及清浩商行").org == "台隆手創館股份有限公司及清浩商行"


class TestSplitEntityLabelsBranchUnitsAsSites:
    """全量稽核抓到的三個誤判：這些殘餘的 org 切得對，但被標成 person。
    org 是歸戶 key 所以不影響比對，但報告拆明細時會顯示錯。"""

    def test_post_office_branch_is_a_site_not_a_person(self):
        e = split_entity("中華郵政股份有限公司嘉義郵局")
        assert e.org == "中華郵政股份有限公司"
        assert e.site == "嘉義郵局"
        assert e.person is None

    def test_office_suffix_is_a_site_not_a_person(self):
        e = split_entity("元大證券股份有限公司台北所")
        assert e.site == "台北所"
        assert e.person is None

    def test_bare_label_is_not_a_person_name(self):
        # 「負責人」是標籤不是姓名，不能當人名收下來。
        e = split_entity("某某企業有限公司負責人")
        assert e.person is None
