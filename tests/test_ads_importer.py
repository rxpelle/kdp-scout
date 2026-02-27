"""Tests for Amazon Ads CSV importer parsing functions."""

import pytest
from kdp_scout.collectors.ads_importer import AdsImporter, COLUMN_ALIASES


@pytest.fixture
def importer():
    """Create an AdsImporter without database initialization."""
    # We only test the pure parsing methods, not the DB-dependent ones
    obj = object.__new__(AdsImporter)
    return obj


class TestParseInt:
    def test_simple_integer(self, importer):
        assert importer._parse_int('123') == 123

    def test_with_commas(self, importer):
        assert importer._parse_int('1,234') == 1234

    def test_with_spaces(self, importer):
        assert importer._parse_int('  123  ') == 123

    def test_dash_returns_none(self, importer):
        assert importer._parse_int('-') is None

    def test_empty_returns_none(self, importer):
        assert importer._parse_int('') is None

    def test_none_returns_none(self, importer):
        assert importer._parse_int(None) is None

    def test_float_string_truncates(self, importer):
        assert importer._parse_int('12.5') == 12

    def test_invalid_string_returns_none(self, importer):
        assert importer._parse_int('abc') is None

    def test_large_number(self, importer):
        assert importer._parse_int('1,234,567') == 1234567

    def test_zero(self, importer):
        assert importer._parse_int('0') == 0


class TestParsePercentage:
    def test_with_percent_sign(self, importer):
        assert importer._parse_percentage('12.5%') == pytest.approx(0.125)

    def test_decimal_form(self, importer):
        assert importer._parse_percentage('0.125') == pytest.approx(0.125)

    def test_whole_number_percentage(self, importer):
        # Value > 1 is treated as a percentage
        assert importer._parse_percentage('12.5') == pytest.approx(0.125)

    def test_fifty_percent(self, importer):
        assert importer._parse_percentage('50%') == pytest.approx(0.5)

    def test_half_as_decimal(self, importer):
        assert importer._parse_percentage('0.5') == pytest.approx(0.5)

    def test_hundred_percent(self, importer):
        assert importer._parse_percentage('100%') == pytest.approx(1.0)

    def test_dash_returns_none(self, importer):
        assert importer._parse_percentage('-') is None

    def test_empty_returns_none(self, importer):
        assert importer._parse_percentage('') is None

    def test_none_returns_none(self, importer):
        assert importer._parse_percentage(None) is None

    def test_invalid_returns_none(self, importer):
        assert importer._parse_percentage('abc') is None

    def test_zero_percent(self, importer):
        assert importer._parse_percentage('0%') == 0.0


class TestParseCurrency:
    def test_with_dollar_sign(self, importer):
        assert importer._parse_currency('$12.50') == pytest.approx(12.50)

    def test_without_dollar_sign(self, importer):
        assert importer._parse_currency('12.50') == pytest.approx(12.50)

    def test_with_commas(self, importer):
        assert importer._parse_currency('$1,234.56') == pytest.approx(1234.56)

    def test_dash_returns_none(self, importer):
        assert importer._parse_currency('-') is None

    def test_empty_returns_none(self, importer):
        assert importer._parse_currency('') is None

    def test_none_returns_none(self, importer):
        assert importer._parse_currency(None) is None

    def test_invalid_returns_none(self, importer):
        assert importer._parse_currency('abc') is None

    def test_zero(self, importer):
        assert importer._parse_currency('$0.00') == pytest.approx(0.0)

    def test_whole_dollar(self, importer):
        assert importer._parse_currency('$5') == pytest.approx(5.0)


class TestLooksLikeHeader:
    def test_valid_header(self, importer):
        cols = ['campaign name', 'search term', 'impressions', 'clicks']
        assert importer._looks_like_header(cols) is True

    def test_minimal_valid_header(self, importer):
        # Needs at least 3 known columns
        cols = ['search term', 'impressions', 'clicks']
        assert importer._looks_like_header(cols) is True

    def test_two_columns_not_enough(self, importer):
        cols = ['search term', 'impressions']
        assert importer._looks_like_header(cols) is False

    def test_no_known_columns(self, importer):
        cols = ['col1', 'col2', 'col3']
        assert importer._looks_like_header(cols) is False

    def test_empty_list(self, importer):
        assert importer._looks_like_header([]) is False

    def test_alias_variations(self, importer):
        cols = ['customer search term', 'impr', 'ctr', 'spend']
        assert importer._looks_like_header(cols) is True


class TestMapColumns:
    def test_exact_match(self, importer):
        cols = ['campaign name', 'search term', 'impressions']
        result = importer._map_columns(cols)
        assert result['campaign_name'] == 'campaign name'
        assert result['search_term'] == 'search term'
        assert result['impressions'] == 'impressions'

    def test_alias_match(self, importer):
        cols = ['campaign', 'customer search term', 'impr']
        result = importer._map_columns(cols)
        assert result['campaign_name'] == 'campaign'
        assert result['search_term'] == 'customer search term'
        assert result['impressions'] == 'impr'

    def test_missing_columns_not_in_map(self, importer):
        cols = ['search term']
        result = importer._map_columns(cols)
        assert 'search_term' in result
        assert 'campaign_name' not in result

    def test_case_insensitive(self, importer):
        # _map_columns lowercases before matching
        cols = ['Campaign Name', 'Search Term', 'Impressions']
        result = importer._map_columns(cols)
        assert 'campaign_name' in result
        assert 'search_term' in result
        assert 'impressions' in result


class TestColumnAliases:
    def test_all_canonical_names_have_aliases(self):
        expected = {
            'campaign_name', 'ad_group', 'search_term', 'match_type',
            'impressions', 'clicks', 'ctr', 'cpc', 'spend', 'sales',
            'acos', 'orders', 'units',
        }
        assert set(COLUMN_ALIASES.keys()) == expected

    def test_all_aliases_are_lowercase(self):
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                assert alias == alias.lower(), (
                    f'{canonical} alias "{alias}" is not lowercase'
                )
