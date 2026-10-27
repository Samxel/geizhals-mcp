"""Pure helpers: paging, text cleanup, title matching and price maths."""

import main
from geizhals import api, matching, summaries


def test_page_size_snaps_up_to_an_allowed_value():
    assert api.page_size(1) == 1
    assert api.page_size(7) == 10
    assert api.page_size(31) == 100
    assert api.page_size(5000) == 1000


def test_clean_html_strips_markup_and_normalizes_dates():
    assert summaries.clean_html('<a href="x">12GB</a><br>GDDR7') == "12GB / GDDR7"
    assert summaries.clean_html("Tom &amp; Jerry") == "Tom & Jerry"
    assert summaries.clean_html("07.01.2025") == "2025-01-07"
    assert summaries.clean_html(None) is None


def test_iso_date_takes_seconds_and_milliseconds():
    assert summaries.iso_date(1735689600) == "2025-01-01"
    assert summaries.iso_date(1735689600000) == "2025-01-01"
    assert summaries.iso_date("x") is None


def test_leaf_cat_is_the_deepest_category_code():
    path = [{"id": {"m": 1}}, {"id": {"o": 53}}, {"id": {"cat": "gra16_512"}}]
    assert summaries._leaf_cat(path) == "gra16_512"
    assert summaries._leaf_cat(None) is None


def test_title_tokens_drop_ad_noise_and_split_fused_models():
    assert matching.title_tokens("Gigabyte RTX5070 Windforce NEU OVP mit Rechnung") == [
        "gigabyte", "rtx", "5070", "windforce"]
    assert matching.title_tokens("Grafikkarte für GTX1080") == ["grafikkarte", "gtx", "1080"]


def test_match_score_penalizes_number_and_variant_mismatches():
    query = set(matching.title_tokens("RTX 4070"))
    exact = matching.match_score(query, "MSI GeForce RTX 4070 Ventus 2X, 12GB GDDR6X")
    ti = matching.match_score(query, "MSI GeForce RTX 4070 Ti Ventus 2X, 12GB GDDR6X")
    other = matching.match_score(query, "MSI GeForce RTX 4060 Ventus 2X, 8GB GDDR6")
    assert exact > 0.8
    assert ti < exact / 1.5
    assert other < exact / 2


def test_model_variants_keep_siblings_out():
    hits = [{"name": "ASUS RTX 4070 Dual"}, {"name": "ASUS RTX 4070 Super Dual"},
            {"name": "ASUS RTX 4070 Ti TUF"}, {"name": "ASUS RTX 4060 Dual"}]
    wanted = set(matching.title_tokens("RTX 4070"))
    assert [h["name"] for h in matching.model_variants(hits, wanted)] == ["ASUS RTX 4070 Dual"]


def test_median():
    assert matching.median([]) is None
    assert matching.median([3, 1, 2]) == 2
    assert matching.median([1, 2, 3, 4]) == 2.5


def test_weekly_keeps_each_iso_weeks_last_point():
    points = [["2026-10-05", 10.0], ["2026-10-06", 11.0], ["2026-10-12", 12.0]]
    assert main._weekly(points) == [["2026-10-06", 11.0], ["2026-10-12", 12.0]]
