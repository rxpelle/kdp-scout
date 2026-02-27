"""Tests for BSR-to-sales estimation model."""

import pytest
from kdp_scout.collectors.bsr_model import (
    estimate_daily_sales,
    estimate_monthly_revenue,
    sales_velocity_label,
    MODELS,
)


class TestEstimateDailySales:
    """Tests for the power-law BSR-to-sales model."""

    def test_bsr_1_high_sales(self):
        """BSR #1 should estimate ~1000+ sales/day."""
        sales = estimate_daily_sales(1)
        assert sales > 500  # should be very high

    def test_bsr_100_high_sales(self):
        """BSR #100 should estimate high daily sales."""
        sales = estimate_daily_sales(100)
        assert 500 < sales < 10000

    def test_bsr_1000(self):
        sales = estimate_daily_sales(1000)
        assert 100 < sales < 2000

    def test_bsr_100000_moderate_sales(self):
        """BSR #100,000 should estimate moderate daily sales."""
        sales = estimate_daily_sales(100000)
        assert 1 < sales < 50

    def test_bsr_500000_low_sales(self):
        sales = estimate_daily_sales(500000)
        assert 0.1 < sales < 10

    def test_higher_bsr_means_fewer_sales(self):
        """Higher BSR number = worse rank = fewer sales."""
        sales_100 = estimate_daily_sales(100)
        sales_1000 = estimate_daily_sales(1000)
        sales_10000 = estimate_daily_sales(10000)
        assert sales_100 > sales_1000 > sales_10000

    def test_none_bsr_returns_zero(self):
        assert estimate_daily_sales(None) == 0.0

    def test_zero_bsr_returns_zero(self):
        assert estimate_daily_sales(0) == 0.0

    def test_negative_bsr_returns_zero(self):
        assert estimate_daily_sales(-5) == 0.0

    def test_returns_float(self):
        result = estimate_daily_sales(1000)
        assert isinstance(result, float)

    def test_result_rounded_to_2_decimals(self):
        result = estimate_daily_sales(1234)
        assert result == round(result, 2)

    def test_us_paperback_marketplace(self):
        kindle = estimate_daily_sales(1000, 'us_kindle')
        paperback = estimate_daily_sales(1000, 'us_paperback')
        assert kindle != paperback
        assert paperback > 0

    def test_uk_kindle_marketplace(self):
        result = estimate_daily_sales(1000, 'uk_kindle')
        assert result > 0

    def test_audiobook_marketplace(self):
        result = estimate_daily_sales(1000, 'us_audiobook')
        assert result > 0

    def test_unknown_marketplace_falls_back_to_us_kindle(self):
        unknown = estimate_daily_sales(1000, 'mars_kindle')
        us_kindle = estimate_daily_sales(1000, 'us_kindle')
        assert unknown == us_kindle

    def test_all_models_have_required_params(self):
        for name, model in MODELS.items():
            assert 'k' in model, f'{name} missing k parameter'
            assert 'a' in model, f'{name} missing a parameter'
            assert model['k'] > 0
            assert 0 < model['a'] < 2


class TestEstimateMonthlyRevenue:
    """Tests for monthly revenue estimation."""

    def test_basic_revenue_calculation(self):
        """Revenue should be positive for valid inputs."""
        revenue = estimate_monthly_revenue(1000, 4.99)
        assert revenue > 0

    def test_high_royalty_tier(self):
        """$2.99-$9.99 gets 70% royalty."""
        rev_2_99 = estimate_monthly_revenue(1000, 2.99)
        rev_2_98 = estimate_monthly_revenue(1000, 2.98)
        # $2.99 gets 70% royalty, $2.98 gets 35% — so $2.99 earns more
        # despite lower price
        assert rev_2_99 > rev_2_98

    def test_low_royalty_tier_below(self):
        """Prices below $2.99 get 35% royalty."""
        revenue = estimate_monthly_revenue(1000, 0.99)
        assert revenue > 0

    def test_low_royalty_tier_above(self):
        """Prices above $9.99 get 35% royalty."""
        rev_9_99 = estimate_monthly_revenue(1000, 9.99)
        rev_10_00 = estimate_monthly_revenue(1000, 10.00)
        # $9.99 gets 70% vs $10.00 gets 35%
        assert rev_9_99 > rev_10_00

    def test_royalty_boundary_2_99(self):
        revenue = estimate_monthly_revenue(1000, 2.99)
        daily = estimate_daily_sales(1000)
        expected = round(daily * 30 * 2.99 * 0.70, 2)
        assert revenue == expected

    def test_royalty_boundary_9_99(self):
        revenue = estimate_monthly_revenue(1000, 9.99)
        daily = estimate_daily_sales(1000)
        expected = round(daily * 30 * 9.99 * 0.70, 2)
        assert revenue == expected

    def test_none_bsr_returns_zero(self):
        assert estimate_monthly_revenue(None, 4.99) == 0.0

    def test_none_price_returns_zero(self):
        assert estimate_monthly_revenue(1000, None) == 0.0

    def test_zero_price_returns_zero(self):
        assert estimate_monthly_revenue(1000, 0) == 0.0

    def test_negative_price_returns_zero(self):
        assert estimate_monthly_revenue(1000, -5.99) == 0.0

    def test_zero_bsr_returns_zero(self):
        assert estimate_monthly_revenue(0, 4.99) == 0.0


class TestSalesVelocityLabel:
    """Tests for sales velocity labeling."""

    def test_excellent(self):
        assert sales_velocity_label(50) == 'Excellent'
        assert sales_velocity_label(100) == 'Excellent'
        assert sales_velocity_label(1000) == 'Excellent'

    def test_strong(self):
        assert sales_velocity_label(10) == 'Strong'
        assert sales_velocity_label(49.9) == 'Strong'

    def test_moderate(self):
        assert sales_velocity_label(3) == 'Moderate'
        assert sales_velocity_label(9.9) == 'Moderate'

    def test_low(self):
        assert sales_velocity_label(0.5) == 'Low'
        assert sales_velocity_label(2.9) == 'Low'

    def test_minimal(self):
        assert sales_velocity_label(0.1) == 'Minimal'
        assert sales_velocity_label(0) == 'Minimal'
        assert sales_velocity_label(-1) == 'Minimal'

    def test_exact_boundaries(self):
        assert sales_velocity_label(50) == 'Excellent'
        assert sales_velocity_label(10) == 'Strong'
        assert sales_velocity_label(3) == 'Moderate'
        assert sales_velocity_label(0.5) == 'Low'
        assert sales_velocity_label(0.49) == 'Minimal'
