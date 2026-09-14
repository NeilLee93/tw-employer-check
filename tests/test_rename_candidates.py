"""`twec.rename_candidates` 的行為規格。

待辦第 7 項的殘餘那一半：統編白送的 202 組改名已經在 `Roster.renamed`
不必再處理，這裡只吃 `key_kind == "name"`（兩邊都沒可信統編）的雇主，
用「時間軸不重疊 + 名稱相似」找候選。這訊號不足以證明改名
（富利食品／富利餐飲一查統編是兩家法人），所以只產候選，不自動合併。
"""

from twec.rename_candidates import date_ranges, find_candidates
from twec.roster import Entity, Roster


def entity(key, names, count=1):
    return Entity(key=key, key_kind="name", uniform_no=None, names=tuple(names), count=count)


class TestDateRanges:
    """讀違規名單，回傳 org -> (最早處分日期, 最晚處分日期)。"""

    def write(self, tmp_path, *rows):
        path = tmp_path / "violations.csv"
        lines = ["處分日期,事業單位名稱或負責人"]
        lines += [f"{date},{name}" for date, name in rows]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_returns_min_and_max_date_per_org(self, tmp_path):
        source = self.write(
            tmp_path,
            ("20160101", "台灣麥當勞餐廳股份有限公司"),
            ("20160501", "台灣麥當勞餐廳股份有限公司"),
        )

        assert date_ranges(source) == {
            "台灣麥當勞餐廳股份有限公司": ("20160101", "20160501")
        }

    def test_normalizes_before_grouping(self, tmp_path):
        # 全形、臺／台、負責人括號都要先收斂再算日期範圍，否則同一個雇主會被切成兩筆。
        source = self.write(
            tmp_path,
            ("20160101", "臺灣積體電路製造股份有限公司(魏哲家)"),
            ("20160601", "台灣積體電路製造股份有限公司"),
        )

        assert date_ranges(source) == {
            "台灣積體電路製造股份有限公司": ("20160101", "20160601")
        }

    def test_ignores_rows_missing_date_or_name(self, tmp_path):
        source = self.write(
            tmp_path,
            ("", "和德昌股份有限公司"),
            ("20160101", ""),
            ("20160601", "和德昌股份有限公司"),
        )

        assert date_ranges(source) == {"和德昌股份有限公司": ("20160601", "20160601")}


class TestFindCandidates:
    """在沒有可信統編的雇主裡找改名候選。"""

    def test_flags_similar_names_with_non_overlapping_time_ranges(self):
        # 台鐵公司化改制：局改制成公司，時間軸接續不重疊，核心名稱「台灣鐵路」相同。
        roster = Roster([
            entity("交通部台灣鐵路管理局", ["交通部台灣鐵路管理局"]),
            entity("國營台灣鐵路股份有限公司", ["國營台灣鐵路股份有限公司"]),
        ])
        ranges = {
            "交通部台灣鐵路管理局": ("20180101", "20180601"),
            "國營台灣鐵路股份有限公司": ("20190101", "20190601"),
        }

        candidates = find_candidates(roster, ranges, threshold=0.4)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.old.key == "交通部台灣鐵路管理局"
        assert c.new.key == "國營台灣鐵路股份有限公司"

    def test_does_not_flag_when_time_ranges_overlap(self):
        # 同時期都在營業，不可能是改名，是兩家真的不同的公司。
        roster = Roster([
            entity("交通部台灣鐵路管理局", ["交通部台灣鐵路管理局"]),
            entity("國營台灣鐵路股份有限公司", ["國營台灣鐵路股份有限公司"]),
        ])
        ranges = {
            "交通部台灣鐵路管理局": ("20180101", "20190601"),
            "國營台灣鐵路股份有限公司": ("20190101", "20200601"),
        }

        assert find_candidates(roster, ranges, threshold=0.4) == []

    def test_does_not_flag_dissimilar_names_even_if_non_overlapping(self):
        roster = Roster([
            entity("威合股份有限公司", ["威合股份有限公司"]),
            entity("台灣善商股份有限公司", ["台灣善商股份有限公司"]),
        ])
        ranges = {
            "威合股份有限公司": ("20180101", "20180601"),
            "台灣善商股份有限公司": ("20190101", "20190601"),
        }

        assert find_candidates(roster, ranges, threshold=0.4) == []

    def test_common_legal_suffix_alone_is_not_enough_similarity(self):
        # 兩家毫不相干的公司只因為都叫「XX股份有限公司」而字尾撞在一起，不該被配對。
        roster = Roster([
            entity("台灣善商股份有限公司", ["台灣善商股份有限公司"]),
            entity("好市多股份有限公司", ["好市多股份有限公司"]),
        ])
        ranges = {
            "台灣善商股份有限公司": ("20180101", "20180601"),
            "好市多股份有限公司": ("20190101", "20190601"),
        }

        assert find_candidates(roster, ranges, threshold=0.4) == []

    def test_ignores_entities_that_already_have_a_uniform_no(self):
        # key_kind == "uniform_no" 的雇主已經被 Roster.renamed 處理過，不進殘餘比對。
        with_uniform_no = Entity(
            key="12411160", key_kind="uniform_no", uniform_no="12411160",
            names=("和德昌股份有限公司",), count=1,
        )
        roster = Roster([
            with_uniform_no,
            entity("台灣善商股份有限公司", ["台灣善商股份有限公司"]),
        ])
        ranges = {
            "和德昌股份有限公司": ("20180101", "20180601"),
            "台灣善商股份有限公司": ("20190101", "20190601"),
        }

        assert find_candidates(roster, ranges, threshold=0.0) == []
