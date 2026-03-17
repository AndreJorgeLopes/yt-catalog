from yt_catalog.config import CATEGORIES, BASE_SCORES, DURATION_THRESHOLDS, PHASE_ORDER, get_duration_group

def test_categories_exist():
    assert "programming" in CATEGORIES
    assert "sleep" in CATEGORIES
    assert len(CATEGORIES) == 8

def test_base_scores():
    assert BASE_SCORES["programming"] == 70
    assert BASE_SCORES["general"] == 30

def test_duration_thresholds():
    assert DURATION_THRESHOLDS["super-small"] == (0, 300)
    assert DURATION_THRESHOLDS["small"] == (300, 600)
    assert DURATION_THRESHOLDS["long"] == (600, 3000)
    assert DURATION_THRESHOLDS["super-big"] == (3000, float("inf"))

def test_phase_order():
    assert PHASE_ORDER["scraping"] < PHASE_ORDER["enrichment"]
    assert PHASE_ORDER["enrichment"] < PHASE_ORDER["categorization"]

def test_duration_group_super_small():
    assert get_duration_group(120) == "super-small"

def test_duration_group_small():
    assert get_duration_group(450) == "small"

def test_duration_group_long():
    assert get_duration_group(1800) == "long"

def test_duration_group_super_big():
    assert get_duration_group(4000) == "super-big"

def test_duration_group_none():
    assert get_duration_group(None) == "long"
