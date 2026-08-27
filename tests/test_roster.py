"""`twec.roster` 的行為規格。

歸戶的最終產出。輸入是 `twec.names` 的 org 與各自的裁處次數，
加上 `twec.uniform_no` 的統編，輸出是「一個雇主一列」。

期望值裡的統編與名稱都照抄真實資料（麥當勞那組是 v0.6.0 查證過的更名案）。
"""

from twec.roster import Roster, count_orgs
from twec.uniform_no import Registration, Registry


def reg(name, no, org_type="股份有限公司", status="營業中", hq_no=""):
    return Registration(name=name, uniform_no=no, org_type=org_type, status=status, hq_no=hq_no)


class TestKeyIsTheUniformNoWhenWeHaveOne:
    """統編查得到就當 key，這是比名稱字串可靠的身分。"""

    def test_uses_uniform_no_as_key(self):
        registry = Registry([reg("和德昌股份有限公司", "12411160")])
        roster = Roster.build({"和德昌股份有限公司": 22}, registry)

        entity = roster.of("和德昌股份有限公司")
        assert entity.key == "12411160"
        assert entity.key_kind == "uniform_no"
        assert entity.uniform_no == "12411160"

    def test_falls_back_to_the_name_when_there_is_no_uniform_no(self):
        # 政府機關無營業稅籍，補不上是結構性的，名稱必須還能當 key。
        registry = Registry([reg("和德昌股份有限公司", "12411160")])
        roster = Roster.build({"交通部台灣鐵路管理局": 5}, registry)

        entity = roster.of("交通部台灣鐵路管理局")
        assert entity.key == "交通部台灣鐵路管理局"
        assert entity.key_kind == "name"
        assert entity.uniform_no is None

    def test_two_nameless_orgs_never_merge_into_each_other(self):
        registry = Registry([reg("和德昌股份有限公司", "12411160")])
        roster = Roster.build({"交通部台灣鐵路管理局": 5, "國立台灣大學": 3}, registry)

        assert len(roster.entities) == 2


class TestSameUniformNoIsOneEmployer:
    """統編白送的 230 組更名，就是靠這裡吃下來的。"""

    def test_a_renamed_company_becomes_one_entity(self):
        # v0.6.0 查證：兩個名稱同為 12411160，是同一法人更名，22 筆應合併計算。
        registry = Registry([
            reg("台灣麥當勞餐廳股份有限公司", "12411160", status="非營業中"),
            reg("和德昌股份有限公司", "12411160"),
        ])
        roster = Roster.build(
            {"台灣麥當勞餐廳股份有限公司": 8, "和德昌股份有限公司": 14}, registry
        )

        assert len(roster.entities) == 1
        entity = roster.of("和德昌股份有限公司")
        assert entity.count == 22
        assert entity.names == ("和德昌股份有限公司", "台灣麥當勞餐廳股份有限公司")
        assert entity.display == "和德昌股份有限公司"

    def test_both_old_and_new_names_resolve_to_the_same_entity(self):
        registry = Registry([
            reg("台灣麥當勞餐廳股份有限公司", "12411160", status="非營業中"),
            reg("和德昌股份有限公司", "12411160"),
        ])
        roster = Roster.build(
            {"台灣麥當勞餐廳股份有限公司": 8, "和德昌股份有限公司": 14}, registry
        )

        assert roster.of("台灣麥當勞餐廳股份有限公司") is roster.of("和德昌股份有限公司")

    def test_head_office_is_found_through_its_branches(self):
        # 外商在台只有分公司有稅籍，母公司名查不到，靠總機構統編指回去。
        registry = Registry([
            reg("香港商世界健身事業有限公司台北分公司", "54321000", hq_no="27940499"),
            reg("香港商世界健身事業有限公司台中分公司", "54321001", hq_no="27940499"),
        ])
        roster = Roster.build({"香港商世界健身事業有限公司": 30}, registry)

        assert roster.of("香港商世界健身事業有限公司").key == "27940499"

    def test_one_name_one_uniform_no_is_not_a_rename(self):
        registry = Registry([reg("和德昌股份有限公司", "12411160")])
        roster = Roster.build({"和德昌股份有限公司": 22}, registry)

        assert roster.renamed == []

    def test_renamed_lists_the_entities_that_merged(self):
        registry = Registry([
            reg("台灣麥當勞餐廳股份有限公司", "12411160", status="非營業中"),
            reg("和德昌股份有限公司", "12411160"),
            reg("優志旺股份有限公司", "70766299"),
        ])
        roster = Roster.build(
            {"台灣麥當勞餐廳股份有限公司": 8, "和德昌股份有限公司": 14, "優志旺股份有限公司": 1},
            registry,
        )

        assert [e.key for e in roster.renamed] == ["12411160"]


class TestLowConfidenceUniformNoDoesNotMerge:
    """`sole_operating` 取的是現在還營業的那家，未必是裁處當時的那家。"""

    def test_keeps_the_name_as_key(self):
        # 同名兩個統編，舊的已歇業 —— resolve 會走 sole_operating。
        registry = Registry([
            reg("大同商行", "11111111", status="非營業中", org_type="獨資"),
            reg("大同商行", "22222222", org_type="獨資"),
        ])
        roster = Roster.build({"大同商行": 3}, registry)

        entity = roster.of("大同商行")
        assert entity.key == "大同商行"
        assert entity.key_kind == "name"

    def test_still_records_the_uniform_no_as_a_hint(self):
        registry = Registry([
            reg("大同商行", "11111111", status="非營業中", org_type="獨資"),
            reg("大同商行", "22222222", org_type="獨資"),
        ])
        roster = Roster.build({"大同商行": 3}, registry)

        assert roster.of("大同商行").uniform_no == "22222222"

    def test_two_orgs_sharing_a_low_confidence_uniform_no_stay_apart(self):
        registry = Registry([
            reg("大同商行", "11111111", status="非營業中", org_type="獨資"),
            reg("大同商行", "22222222", org_type="獨資"),
            reg("大同商行台北店", "11111111", status="非營業中", org_type="獨資"),
            reg("大同商行台北店", "22222222", org_type="獨資"),
        ])
        roster = Roster.build({"大同商行": 3, "大同商行台北店": 1}, registry)

        assert len(roster.entities) == 2


class TestCountingTheViolationSource:
    """歸戶主流程的入口：違規 CSV 進來，org -> 裁處列數出去。"""

    def write(self, tmp_path, *raw_names):
        path = tmp_path / "violations.csv"
        lines = ["公告日期,事業單位名稱或負責人"]
        lines += [f"2026-01-01,{name}" for name in raw_names]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_counts_rows_per_org(self, tmp_path):
        source = self.write(
            tmp_path, "和德昌股份有限公司", "和德昌股份有限公司", "優志旺股份有限公司"
        )

        assert count_orgs(source) == {"和德昌股份有限公司": 2, "優志旺股份有限公司": 1}

    def test_normalizes_and_splits_before_counting(self, tmp_path):
        # 全形、臺／台、負責人括號、廠區，都必須先收斂再計數。
        source = self.write(
            tmp_path,
            "台灣積體電路製造股份有限公司",
            "臺灣積體電路製造股份有限公司(魏哲家)",
            "台灣積體電路製造股份有限公司竹科十二廠",
        )

        assert count_orgs(source) == {"台灣積體電路製造股份有限公司": 3}

    def test_ignores_rows_with_an_empty_name(self, tmp_path):
        source = self.write(tmp_path, "和德昌股份有限公司", "")

        assert count_orgs(source) == {"和德昌股份有限公司": 1}
