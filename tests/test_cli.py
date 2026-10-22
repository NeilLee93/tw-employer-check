"""twec.cli 的行為規格（待辦第 9 項）。

用暫存的小 CSV 模擬名冊與三部法規的原始資料，不需要下載真資料。
"""

from __future__ import annotations

import csv

import pytest

from twec.cli import (
    default_tracks,
    load_roster,
    main,
    render_report,
    resolve_target,
    run_tracks,
    search,
)
from twec.roster import Entity

LSA_HEADER = [
    "主管機關", "公告日期", "處分日期", "處分字號",
    "事業單位名稱或負責人", "違法法規法條", "違反法規內容", "罰鍰金額", "備註說明",
]
LPA_HEADER = [
    "主管機關", "公告日期", "處分日期", "處分字號",
    "事業單位名稱或負責人", "違法法規法條", "違反法規內容", "處分金額或滯納金", "備註說明",
]


def write_csv(path, header, rows, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for r in rows:
            writer.writerow([r.get(h, "") for h in header])
    return path


def entity(*names, key=None, key_kind="name", uniform_no=None, count=1):
    return Entity(
        key=key or names[0], key_kind=key_kind, uniform_no=uniform_no, names=tuple(names), count=count,
    )


ROSTER = [
    entity("和德昌股份有限公司", "台灣麥當勞餐廳股份有限公司",
           key="12411160", key_kind="uniform_no", uniform_no="12411160", count=22),
    entity("富利餐飲股份有限公司", count=33),
    entity("富利食品股份有限公司", count=5),
]


@pytest.fixture
def data(tmp_path):
    """名冊＋三部法規 CSV，和德昌在三部法規都有紀錄。"""
    roster = write_csv(
        tmp_path / "roster.csv",
        ["key", "key_kind", "uniform_no", "代表名稱", "名稱數", "裁處次數", "其他名稱"],
        [
            {"key": e.key, "key_kind": e.key_kind, "uniform_no": e.uniform_no or "",
             "代表名稱": e.display, "名稱數": str(len(e.names)), "裁處次數": str(e.count),
             "其他名稱": ";".join(e.names[1:])}
            for e in ROSTER
        ],
        encoding="utf-8-sig",
    )
    lsa = write_csv(tmp_path / "lsa.csv", LSA_HEADER, [
        {"處分日期": "20250101", "事業單位名稱或負責人": "和德昌股份有限公司",
         "違法法規法條": "勞動基準法第24條", "違反法規內容": "延長工作時間未依規定加給工資",
         "罰鍰金額": "20000"},
        {"處分日期": "20160301", "事業單位名稱或負責人": "台灣麥當勞餐廳股份有限公司(某負責人)",
         "違法法規法條": "勞動基準法第24條", "違反法規內容": "延長工作時間未依規定加給工資",
         "罰鍰金額": "", "備註說明": "行政救濟中"},
    ])
    lpa = write_csv(tmp_path / "lpa.csv", LPA_HEADER, [
        {"處分日期": "20240101", "事業單位名稱或負責人": "和德昌股份有限公司",
         "違法法規法條": "勞工退休金條例第19條第1項", "違反法規內容": "未依規定按月提繳",
         "處分金額或滯納金": "3000"},
    ])
    osha = write_csv(tmp_path / "osha.csv", LSA_HEADER, [
        {"處分日期": "20230101", "事業單位名稱或負責人": "只在職安出現的營造有限公司",
         "違法法規法條": "營造安全衛生設施標準第19條第1項暨職業安全衛生法第6條第1項",
         "違反法規內容": "未設置護欄", "罰鍰金額": "250000"},
    ])
    return {"roster": roster, "lsa": lsa, "lpa": lpa, "osha": osha,
            "law_table": tmp_path / "no_such.xlsx"}


def argv(data, *rest):
    return [
        "--roster", str(data["roster"]), *rest,
        "--lsa", str(data["lsa"]), "--lpa", str(data["lpa"]), "--osha", str(data["osha"]),
        "--law-table", str(data["law_table"]),
    ]


class TestRoster:
    def test_load_roster_restores_all_aliases_and_sorts_by_count(self, data):
        loaded = load_roster(data["roster"])
        assert loaded[0].names == ("富利餐飲股份有限公司",)
        mcd = next(e for e in loaded if e.key == "12411160")
        assert mcd.names == ("和德昌股份有限公司", "台灣麥當勞餐廳股份有限公司")
        assert mcd.uniform_no == "12411160"


class TestSearch:
    def test_matches_any_alias_by_substring(self):
        assert [e.key for e in search(ROSTER, "麥當勞")] == ["12411160"]

    def test_matches_uniform_no_exactly(self):
        assert [e.key for e in search(ROSTER, "12411160")] == ["12411160"]

    def test_normalizes_the_query_so_臺_finds_台(self):
        assert [e.key for e in search(ROSTER, "臺灣麥當勞")] == ["12411160"]

    def test_respects_the_limit(self):
        assert len(search(ROSTER, "富利", limit=1)) == 1


class TestResolveTarget:
    def test_uniform_no_resolves_to_the_merged_entity(self):
        got = resolve_target(ROSTER, "12411160")
        assert got.entity.key == "12411160" and got.in_roster

    def test_exact_old_name_resolves_to_the_merged_entity(self):
        # 用改名前的舊名查，也要拿到含新名的整個雇主，報告才會把歷史接起來。
        got = resolve_target(ROSTER, "台灣麥當勞餐廳股份有限公司")
        assert got.entity.key == "12411160"

    def test_raw_name_with_person_in_parentheses_is_normalized_first(self):
        got = resolve_target(ROSTER, "和德昌股份有限公司(某負責人)")
        assert got.entity.key == "12411160"

    def test_ambiguous_keyword_returns_candidates_instead_of_guessing(self):
        # 富利食品與富利餐飲統編不同，是兩家法人，不能替使用者挑一家。
        got = resolve_target(ROSTER, "富利")
        assert got.entity is None
        assert {e.display for e in got.candidates} == {"富利餐飲股份有限公司", "富利食品股份有限公司"}

    def test_unique_keyword_resolves_directly(self):
        assert resolve_target(ROSTER, "和德昌").entity.key == "12411160"

    def test_name_not_in_roster_falls_back_to_exact_org(self):
        got = resolve_target(ROSTER, "只在職安出現的營造有限公司")
        assert not got.in_roster
        assert got.entity.names == ("只在職安出現的營造有限公司",)


class TestRunTracks:
    def test_each_regime_gets_its_own_report(self, data):
        tracks = default_tracks(data["lsa"], data["lpa"], data["osha"], data["law_table"])
        results = run_tracks(ROSTER[0], tracks)
        counts = {r.track.key: len(r.report.items) for r in results}
        assert counts == {"lsa": 2, "lpa": 1, "osha": 0}

    def test_missing_data_file_is_skipped_not_fatal(self, data, tmp_path):
        tracks = default_tracks(data["lsa"], tmp_path / "missing.csv", data["osha"], data["law_table"])
        results = run_tracks(ROSTER[0], tracks)
        lpa = next(r for r in results if r.track.key == "lpa")
        assert lpa.report is None and "找不到資料檔" in lpa.skipped


class TestRenderReport:
    def render(self, data):
        tracks = default_tracks(data["lsa"], data["lpa"], data["osha"], data["law_table"])
        return render_report(ROSTER[0], run_tracks(ROSTER[0], tracks), in_roster=True)

    def test_shows_three_separate_sections(self, data):
        out = self.render(data)
        assert "■ 勞動基準法" in out and "■ 勞工退休金條例" in out and "■ 職業安全衛生法" in out

    def test_summary_lists_counts_side_by_side_without_a_total(self, data):
        # 硬規則：勞退不得與勞基法等權相加。彙總只並列，不出現總數。
        out = self.render(data)
        summary = out.split("彙總（各法規分列，不加總）：")[1]
        assert "勞動基準法：2 筆" in summary
        assert "勞工退休金條例：1 筆" in summary
        assert "職業安全衛生法：0 筆" in summary
        assert "合計" not in out and "總計" not in out

    def test_disputed_rows_are_marked_not_final(self, data):
        out = self.render(data)
        assert "尚未確定（行政救濟中）" in out
        assert "不得逕認該雇主違法" in out

    def test_lpa_section_carries_the_arrears_caveat(self, data):
        assert "欠費與滯納金" in self.render(data)


class TestMain:
    def test_search_prints_candidates(self, data, capsys):
        assert main(["--roster", str(data["roster"]), "search", "富利"]) == 0
        out = capsys.readouterr().out
        assert "富利餐飲股份有限公司" in out and "富利食品股份有限公司" in out

    def test_report_prints_the_merged_entity(self, data, capsys):
        assert main(argv(data, "report", "麥當勞")) == 0
        out = capsys.readouterr().out
        assert "雇主：和德昌股份有限公司" in out
        assert "別名：台灣麥當勞餐廳股份有限公司" in out

    def test_ambiguous_report_exits_2_with_candidates_on_stderr(self, data, capsys):
        assert main(argv(data, "report", "富利")) == 2
        assert "命中 2 家" in capsys.readouterr().err

    def test_missing_roster_exits_1_with_a_hint(self, tmp_path, capsys):
        assert main(["--roster", str(tmp_path / "none.csv"), "search", "x"]) == 1
        assert "build_roster.py" in capsys.readouterr().err
