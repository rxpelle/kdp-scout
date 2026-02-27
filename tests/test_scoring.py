"""Tests for keyword scoring algorithm."""

import pytest
from unittest.mock import MagicMock, patch
from kdp_scout.keyword_engine import KeywordScorer


def make_keyword_row(**overrides):
    """Create a mock keyword row with metric fields."""
    defaults = {
        'autocomplete_position': None,
        'competition_count': None,
        'avg_bsr_top_results': None,
        'impressions': None,
        'orders': None,
    }
    defaults.update(overrides)
    return defaults


class TestScoreKeyword:
    """Tests for the composite scoring algorithm."""

    @pytest.fixture
    def scorer(self):
        """Create a KeywordScorer with mocked DB access."""
        with patch('kdp_scout.keyword_engine.init_db'):
            with patch('kdp_scout.keyword_engine.KeywordRepository') as mock_repo:
                s = KeywordScorer()
                s._repo = mock_repo()
                return s

    def test_no_signals_returns_zero(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row()
        assert scorer.score_keyword(1) == 0.0

    def test_nonexistent_keyword_returns_zero(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = None
        assert scorer.score_keyword(999) == 0.0

    # -- Autocomplete scoring --

    def test_autocomplete_position_1(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=1
        )
        score = scorer.score_keyword(1)
        assert score == 100.0  # (11-1)*10

    def test_autocomplete_position_5(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=5
        )
        score = scorer.score_keyword(1)
        assert score == 60.0  # (11-5)*10

    def test_autocomplete_position_10(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=10
        )
        score = scorer.score_keyword(1)
        assert score == 10.0  # (11-10)*10

    def test_autocomplete_position_11_gives_zero(self, scorer):
        """Position 11+ should contribute 0 (max(0, 11-11)*10 = 0)."""
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=11
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    def test_autocomplete_position_zero_ignored(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=0
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    # -- Competition scoring --

    def test_low_competition_under_50k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            competition_count=30000
        )
        score = scorer.score_keyword(1)
        assert score == 30.0

    def test_medium_competition_under_200k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            competition_count=100000
        )
        score = scorer.score_keyword(1)
        assert score == 15.0

    def test_high_competition_over_200k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            competition_count=500000
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    def test_competition_boundary_50k(self, scorer):
        """Exactly 50,000 should get the lower tier (15 pts)."""
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            competition_count=50000
        )
        score = scorer.score_keyword(1)
        assert score == 15.0

    # -- BSR scoring --

    def test_bsr_under_100k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            avg_bsr_top_results=50000
        )
        score = scorer.score_keyword(1)
        assert score == 25.0

    def test_bsr_under_500k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            avg_bsr_top_results=300000
        )
        score = scorer.score_keyword(1)
        assert score == 10.0

    def test_bsr_over_500k(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            avg_bsr_top_results=600000
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    # -- Impressions scoring --

    def test_high_impressions(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            impressions=500
        )
        score = scorer.score_keyword(1)
        assert score == 20.0

    def test_low_impressions(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            impressions=50
        )
        score = scorer.score_keyword(1)
        assert score == 5.0

    def test_zero_impressions(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            impressions=0
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    # -- Orders scoring --

    def test_orders_base_score(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            orders=1
        )
        score = scorer.score_keyword(1)
        assert score == 30.0

    def test_orders_5_plus_bonus(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            orders=5
        )
        score = scorer.score_keyword(1)
        assert score == 40.0  # 30 base + 10 bonus

    def test_orders_10_plus_double_bonus(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            orders=10
        )
        score = scorer.score_keyword(1)
        assert score == 50.0  # 30 base + 10 + 10

    def test_zero_orders(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            orders=0
        )
        score = scorer.score_keyword(1)
        assert score == 0.0

    # -- Combined scoring --

    def test_max_theoretical_score(self, scorer):
        """All signals at best values = 225 max.

        Autocomplete pos 1 = 100, competition <50k = 30, BSR <100k = 25,
        impressions >100 = 20, orders >0 = 30 + >=5 bonus 10 + >=10 bonus 10 = 50.
        Total: 100 + 30 + 25 + 20 + 50 = 225.
        """
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=1,     # 100
            competition_count=1000,      # 30
            avg_bsr_top_results=1000,    # 25
            impressions=1000,            # 20
            orders=15,                   # 30 + 10 + 10 = 50
        )
        score = scorer.score_keyword(1)
        assert score == 225.0

    def test_typical_moderate_keyword(self, scorer):
        scorer._repo.get_keyword_with_metrics.return_value = make_keyword_row(
            autocomplete_position=5,     # 60
            competition_count=100000,    # 15
            avg_bsr_top_results=300000,  # 10
            impressions=50,              # 5
            orders=2,                    # 30
        )
        score = scorer.score_keyword(1)
        assert score == 120.0
