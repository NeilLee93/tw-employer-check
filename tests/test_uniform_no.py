"""`twec.uniform_no` 的行為規格。

期望值來源是財政部稅籍三檔與勞動部違規資料裡的真實字串
（統編、組織別、狀態都照抄實際資料），不是從實作反推的。

不讀 390 萬列的稅籍檔，直接餵 Registration 建 Registry。
"""

import pytest

from twec.uniform_no import Registration, Registry


def reg(name, no, org_type="股份有限公司", status="營業中", hq_no=""):
    return Registration(name=name, uniform_no=no, org_type=org_type, status=status, hq_no=hq_no)


class TestExactMatch:
    """絕大多數（29,421 / 45,311 家）走這條，名稱一字不差。"""

    def test_matches_identical_name(self):
        r = Registry([reg("和德昌股份有限公司", "12411160")])
        got = r.resolve("和德昌股份有限公司")
        assert got.uniform_no == "12411160"
        assert got.method == "exact"

    def test_same_name_in_multiple_files_is_still_one_company(self):
        # 同一家在營業中檔與停業檔各出現一次，統編相同，不算歧義。
        r = Registry([
            reg("某某企業社", "12345678", "獨資", "營業中"),
            reg("某某企業社", "12345678", "獨資", "停業"),
        ])
        assert r.resolve("某某企業社").uniform_no == "12345678"

    def test_unknown_name_is_a_miss(self):
        r = Registry([reg("和德昌股份有限公司", "12411160")])
        got = r.resolve("晶元光電股份有限公司")
        assert got.uniform_no is None
        assert got.method == "miss"


class TestSoleOperatingCandidate:
    """同名多統編、但舊的都歇業了只剩一個營業中。
    連鎖總部改組（萊爾富、全家、國泰人壽）全走這條，都正確。"""

    def test_picks_the_only_operating_one(self):
        r = Registry([
            reg("萊爾富國際股份有限公司", "23285582", status="營業中"),
            reg("萊爾富國際股份有限公司", "70809977", status="非營業中"),
        ])
        got = r.resolve("萊爾富國際股份有限公司")
        assert got.uniform_no == "23285582"
        assert got.method == "sole_operating"

    def test_is_not_high_confidence(self):
        # 這是從候選裡挑的，不是比對出來的。要嚴格的下游可以只收比對結果。
        r = Registry([
            reg("萊爾富國際股份有限公司", "23285582", status="營業中"),
            reg("萊爾富國際股份有限公司", "70809977", status="非營業中"),
        ])
        assert r.resolve("萊爾富國際股份有限公司").high_confidence is False

    def test_exact_single_match_is_high_confidence(self):
        r = Registry([reg("和德昌股份有限公司", "12411160")])
        assert r.resolve("和德昌股份有限公司").high_confidence is True


class TestAmbiguousNameYieldsNothing:
    """兩家同名的都還在營業，光靠名稱分不出是哪一家。
    專案的保守原則是寧可分裂不可錯併，所以不挑、不猜。"""

    def test_two_operating_companies_resolve_to_none(self):
        r = Registry([
            reg("永泰實業社", "95108620", "獨資", "營業中"),
            reg("永泰實業社", "82476263", "獨資", "營業中"),
        ])
        got = r.resolve("永泰實業社")
        assert got.uniform_no is None
        assert got.method == "ambiguous_name"

    def test_candidates_are_kept_for_manual_review(self):
        r = Registry([
            reg("永泰實業社", "95108620", "獨資", "營業中"),
            reg("永泰實業社", "82476263", "獨資", "營業中"),
        ])
        got = r.resolve("永泰實業社")
        assert {c.uniform_no for c in got.candidates} == {"95108620", "82476263"}

    def test_no_operating_candidate_at_all_resolves_to_none(self):
        r = Registry([
            reg("某某商行", "11111111", "獨資", "非營業中"),
            reg("某某商行", "22222222", "獨資", "停業"),
        ])
        got = r.resolve("某某商行")
        assert got.uniform_no is None
        assert got.method == "ambiguous_name"

    def test_operating_candidate_is_listed_first(self):
        r = Registry([
            reg("某某商行", "11111111", "獨資", "非營業中"),
            reg("某某商行", "22222222", "獨資", "營業中"),
            reg("某某商行", "33333333", "獨資", "營業中"),
        ])
        got = r.resolve("某某商行")
        assert got.candidates[0].status == "營業中"


class TestJuridicalPrefixIsStripped:
    """勞動部寫全名「財團法人元智大學」，稅籍登記的是「元智大學」。"""

    def test_strips_foundation_prefix(self):
        r = Registry([reg("元智大學", "13554572", "其他")])
        got = r.resolve("財團法人元智大學")
        assert got.uniform_no == "13554572"
        assert got.method == "strip_juridical"

    def test_strips_medical_foundation_prefix(self):
        r = Registry([reg("聖保祿醫院", "12345678", "其他")])
        assert r.resolve("醫療財團法人聖保祿醫院").uniform_no == "12345678"

    def test_does_not_strip_when_full_name_matches(self):
        # 全名本身就有稅籍時不該再剝前綴，剝了會對到別家。
        r = Registry([
            reg("財團法人某某基金會", "11111111", "其他"),
            reg("某某基金會", "22222222", "其他"),
        ])
        got = r.resolve("財團法人某某基金會")
        assert got.uniform_no == "11111111"
        assert got.method == "exact"


class TestNaturalPersonShop:
    """「王小明即某某商行」佔違規名單 7,314 家，是最大的單一修補來源。
    `twec.names` 刻意不拆這個字串，在這裡才拆。"""

    def test_takes_shop_name_after_ji(self):
        r = Registry([reg("立宇小吃店", "18463306", "獨資")])
        got = r.resolve("陳怡秀即立宇小吃店")
        assert got.uniform_no == "18463306"
        assert got.method == "natural_person"

    def test_shop_not_in_registry_is_a_miss(self):
        r = Registry([reg("別家小吃店", "18463306", "獨資")])
        assert r.resolve("陳怡秀即立宇小吃店").uniform_no is None


class TestForeignBranchViaPrefix:
    """外國公司在台只有分公司有稅籍，母公司名查不到。
    前綴命中的那群若同屬一個總機構，那個總機構就是在台雇主。"""

    def test_branches_sharing_one_hq_resolve_to_that_hq(self):
        r = Registry([
            reg("香港商世界健身事業有限公司草屯分公司", "83750963",
                "外國公司在台之分公司", hq_no="27940499"),
            reg("香港商世界健身事業有限公司基隆分公司", "42987351",
                "外國公司在台之分公司", hq_no="27940499"),
        ])
        got = r.resolve("香港商世界健身事業有限公司")
        assert got.uniform_no == "27940499"
        assert got.method == "hq_via_prefix"

    def test_single_taiwan_branch_resolves_to_itself(self):
        r = Registry([
            reg("荷蘭商海尼根股份有限公司台灣分公司", "16099470", "外國公司在台之分公司"),
        ])
        got = r.resolve("荷蘭商海尼根股份有限公司")
        assert got.uniform_no == "16099470"
        assert got.method == "prefix_single"

    def test_branches_of_different_hqs_resolve_to_nothing(self):
        # 「台北市立聯合醫院」底下各院區統編各異又無總機構統編，
        # 猜任何一個都是錯的。
        r = Registry([
            reg("台北市立聯合醫院(松德院區)", "03750343", "其他"),
            reg("台北市立聯合醫院松德院區營養科", "26277282", "其他"),
        ])
        got = r.resolve("台北市立聯合醫院")
        assert got.uniform_no is None
        assert got.method == "ambiguous_prefix"

    def test_prefix_must_not_swallow_a_different_company(self):
        # 「大同股份有限公司」不該因為「大同股份有限公司這不是同一家」
        # 這種名稱而被前綴法對到——前綴法只在統編或總機構收斂時才給答案。
        r = Registry([
            reg("某某企業有限公司甲店", "11111111", "獨資"),
            reg("某某企業有限公司乙店", "22222222", "獨資"),
        ])
        assert r.resolve("某某企業有限公司").uniform_no is None


class TestRegistryConstruction:
    def test_missing_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            Registry.from_dir("/nonexistent-path-for-test")

    def test_distinct_names_counts_names_not_rows(self):
        r = Registry([
            reg("某某企業社", "12345678", "獨資", "營業中"),
            reg("某某企業社", "12345678", "獨資", "停業"),
        ])
        assert len(r) == 2
        assert r.distinct_names == 1
