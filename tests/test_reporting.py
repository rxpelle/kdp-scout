"""Tests for reporting utility functions and algorithms."""

import pytest
from kdp_scout.reporting import _fmt_number, _fmt_price, _score_to_bid, BID_TIERS


class TestFmtNumber:
    def test_formats_with_commas(self):
        assert _fmt_number(1234567) == '1,234,567'

    def test_none_returns_dash(self):
        assert _fmt_number(None) == '-'

    def test_zero(self):
        assert _fmt_number(0) == '0'

    def test_small_number(self):
        assert _fmt_number(42) == '42'

    def test_float_truncates(self):
        assert _fmt_number(99.9) == '99'


class TestFmtPrice:
    def test_formats_with_dollar_sign(self):
        assert _fmt_price(9.99) == '$9.99'

    def test_none_returns_dash(self):
        assert _fmt_price(None) == '-'

    def test_zero_returns_dash(self):
        assert _fmt_price(0) == '-'

    def test_large_price(self):
        assert _fmt_price(1234.56) == '$1,234.56'

    def test_small_price(self):
        assert _fmt_price(0.99) == '$0.99'


class TestScoreToBid:
    def test_score_100_plus(self):
        assert _score_to_bid(100) == 1.50
        assert _score_to_bid(200) == 1.50

    def test_score_75(self):
        assert _score_to_bid(75) == 1.00
        assert _score_to_bid(99) == 1.00

    def test_score_50(self):
        assert _score_to_bid(50) == 0.75
        assert _score_to_bid(74) == 0.75

    def test_score_25(self):
        assert _score_to_bid(25) == 0.50
        assert _score_to_bid(49) == 0.50

    def test_score_0(self):
        assert _score_to_bid(0) == 0.35
        assert _score_to_bid(24) == 0.35

    def test_negative_score(self):
        """Negative scores should still return the minimum bid."""
        assert _score_to_bid(-10) == 0.35

    def test_bid_tiers_are_descending(self):
        """BID_TIERS should be ordered from highest to lowest threshold."""
        thresholds = [t for t, _ in BID_TIERS]
        assert thresholds == sorted(thresholds, reverse=True)

    def test_bids_are_descending(self):
        """Higher thresholds should map to higher bids."""
        bids = [b for _, b in BID_TIERS]
        assert bids == sorted(bids, reverse=True)
