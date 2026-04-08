"""Tests for multi-marketplace support (commit 2deb412).

Covers marketplace-aware changes across all modified modules:
- config: MARKETPLACES dict, get_marketplace(), Config.MARKETPLACE
- autocomplete: URL template, mine_autocomplete(marketplace=), _query_autocomplete(mp)
- product_scraper: URL template, ProductScraper(marketplace=)
- trending: discover_trending_keywords(marketplace=), _query_google_suggest(hl=)
- keyword_engine: mine_keywords(marketplace=), ReverseASIN(marketplace=)
- competitor_engine: CompetitorEngine(marketplace=) forwarding
- cli: marketplace_option on all commands
"""

import logging

import pytest
from unittest.mock import patch, MagicMock, call

from click.testing import CliRunner

from kdp_scout.config import Config, MARKETPLACES, get_marketplace
from kdp_scout.collectors.bsr_model import estimate_daily_sales, estimate_monthly_revenue


# ── config.py ────────────────────────────────────────────────────────


class TestMarketplaceConfig:
    """MARKETPLACES dict and get_marketplace() helper."""

    def test_all_marketplaces_have_required_keys(self):
        required = {'domain', 'mid', 'google_hl', 'bsr_model', 'bestsellers'}
        for code, mp in MARKETPLACES.items():
            missing = required - set(mp.keys())
            assert not missing, f"Marketplace '{code}' missing keys: {missing}"

    def test_all_domains_start_with_www(self):
        for code, mp in MARKETPLACES.items():
            assert mp['domain'].startswith('www.amazon.'), (
                f"Marketplace '{code}' has unexpected domain: {mp['domain']}"
            )

    def test_us_is_default(self):
        with patch.object(Config, 'MARKETPLACE', 'us'):
            assert Config.MARKETPLACE.lower() in MARKETPLACES

    def test_get_marketplace_defaults_to_config(self):
        with patch.object(Config, 'MARKETPLACE', 'us'):
            mp = get_marketplace(None)
            assert mp == MARKETPLACES['us']

    def test_get_marketplace_case_insensitive(self):
        assert get_marketplace('US') == get_marketplace('us')
        assert get_marketplace('De') == get_marketplace('de')

    def test_get_marketplace_returns_correct_domain(self):
        assert get_marketplace('de')['domain'] == 'www.amazon.de'
        assert get_marketplace('uk')['domain'] == 'www.amazon.co.uk'
        assert get_marketplace('fr')['domain'] == 'www.amazon.fr'

    def test_get_marketplace_invalid_raises(self):
        with pytest.raises(ValueError, match='Unknown marketplace "zz"'):
            get_marketplace('zz')

    def test_get_marketplace_error_lists_supported(self):
        with pytest.raises(ValueError, match='Supported:'):
            get_marketplace('xx')

    def test_marketplace_in_config_as_dict(self):
        d = Config.as_dict()
        assert 'MARKETPLACE' in d

    def test_all_bsr_models_exist_in_bsr_model_module(self):
        """Every marketplace bsr_model must be a key in bsr_model.MODELS."""
        from kdp_scout.collectors.bsr_model import MODELS
        for code, mp in MARKETPLACES.items():
            model_name = mp['bsr_model']
            assert model_name in MODELS, (
                f"Marketplace '{code}' references bsr_model '{model_name}' "
                f"which doesn't exist in MODELS"
            )

    def test_valid_code_returns_bsr_model(self):
        mp = get_marketplace('uk')
        assert mp['bsr_model'] == 'uk_kindle'
        assert 'domain' in mp


# ── collectors/autocomplete.py ───────────────────────────────────────


class TestAutocompleteMarketplace:
    """Autocomplete API uses correct marketplace URL and mid."""

    def test_url_template_uses_marketplace_domain(self):
        from kdp_scout.collectors.autocomplete import AUTOCOMPLETE_URL_TEMPLATE
        mp = get_marketplace('de')
        url = AUTOCOMPLETE_URL_TEMPLATE.format(
            domain=mp['domain'].replace('www.', '')
        )
        assert url == 'https://completion.amazon.de/api/2017/suggestions'

    def test_url_template_us(self):
        from kdp_scout.collectors.autocomplete import AUTOCOMPLETE_URL_TEMPLATE
        mp = get_marketplace('us')
        url = AUTOCOMPLETE_URL_TEMPLATE.format(
            domain=mp['domain'].replace('www.', '')
        )
        assert url == 'https://completion.amazon.com/api/2017/suggestions'

    def test_url_template_uk(self):
        from kdp_scout.collectors.autocomplete import AUTOCOMPLETE_URL_TEMPLATE
        mp = get_marketplace('uk')
        url = AUTOCOMPLETE_URL_TEMPLATE.format(
            domain=mp['domain'].replace('www.', '')
        )
        assert url == 'https://completion.amazon.co.uk/api/2017/suggestions'

    @patch('kdp_scout.collectors.autocomplete.fetch')
    @patch('kdp_scout.collectors.autocomplete.rate_registry')
    def test_query_autocomplete_uses_marketplace_mid(self, mock_rate, mock_fetch):
        from kdp_scout.collectors.autocomplete import _query_autocomplete
        mp = get_marketplace('de')

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'suggestions': []}
        mock_fetch.return_value = mock_response

        _query_autocomplete('test', 'digital-text', mp)

        _, kwargs = mock_fetch.call_args
        assert kwargs['params']['mid'] == 'A1PA6795UKMFR9'

    @patch('kdp_scout.collectors.autocomplete.fetch')
    @patch('kdp_scout.collectors.autocomplete.rate_registry')
    def test_query_autocomplete_uses_marketplace_url(self, mock_rate, mock_fetch):
        from kdp_scout.collectors.autocomplete import _query_autocomplete
        mp = get_marketplace('uk')

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'suggestions': []}
        mock_fetch.return_value = mock_response

        _query_autocomplete('test', 'digital-text', mp)

        called_url = mock_fetch.call_args[0][0]
        assert 'completion.amazon.co.uk' in called_url

    @patch('kdp_scout.collectors.autocomplete._query_autocomplete')
    @patch('kdp_scout.collectors.autocomplete.rate_registry')
    def test_mine_autocomplete_passes_marketplace(self, mock_rate, mock_query):
        from kdp_scout.collectors.autocomplete import mine_autocomplete

        mock_query.return_value = []
        mine_autocomplete('test', marketplace='de', depth=1)

        # Every call to _query_autocomplete should receive the DE marketplace dict
        for c in mock_query.call_args_list:
            mp_arg = c[0][2]  # third positional arg is mp
            assert mp_arg['domain'] == 'www.amazon.de'
            assert mp_arg['mid'] == 'A1PA6795UKMFR9'


# ── collectors/product_scraper.py ────────────────────────────────────


class TestProductScraperMarketplace:
    """ProductScraper constructs URLs from marketplace domain."""

    def test_url_template(self):
        from kdp_scout.collectors.product_scraper import PRODUCT_URL_TEMPLATE
        url = PRODUCT_URL_TEMPLATE.format(domain='www.amazon.de', asin='B001234')
        assert url == 'https://www.amazon.de/dp/B001234'

    @patch('kdp_scout.collectors.product_scraper.rate_registry')
    def test_scraper_stores_marketplace(self, mock_rate):
        from kdp_scout.collectors.product_scraper import ProductScraper
        scraper = ProductScraper(marketplace='uk')
        assert scraper._mp['domain'] == 'www.amazon.co.uk'

    @patch('kdp_scout.collectors.product_scraper.rate_registry')
    def test_scraper_defaults_to_config_marketplace(self, mock_rate):
        from kdp_scout.collectors.product_scraper import ProductScraper
        scraper = ProductScraper()
        expected_domain = MARKETPLACES[Config.MARKETPLACE.lower()]['domain']
        assert scraper._mp['domain'] == expected_domain

    @patch('kdp_scout.collectors.product_scraper.fetch')
    @patch('kdp_scout.collectors.product_scraper.rate_registry')
    def test_scrape_product_uses_marketplace_domain(self, mock_rate, mock_fetch):
        from kdp_scout.collectors.product_scraper import ProductScraper

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><body></body></html>'
        mock_fetch.return_value = mock_response

        scraper = ProductScraper(marketplace='de')
        scraper.scrape_product('B001234ABC')

        called_url = mock_fetch.call_args[0][0]
        assert 'www.amazon.de/dp/B001234ABC' in called_url


# ── collectors/trending.py ───────────────────────────────────────────


class TestTrendingMarketplace:
    """discover_trending_keywords and _query_google_suggest use marketplace hl."""

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_google_suggest_uses_hl_parameter(self, mock_rate, mock_fetch):
        from kdp_scout.collectors.trending import _query_google_suggest

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ['query', ['suggestion 1']]
        mock_fetch.return_value = mock_response

        _query_google_suggest('test query', hl='de')

        _, kwargs = mock_fetch.call_args
        assert kwargs['params']['hl'] == 'de'

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_google_suggest_defaults_to_en(self, mock_rate, mock_fetch):
        from kdp_scout.collectors.trending import _query_google_suggest

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ['query', ['suggestion 1']]
        mock_fetch.return_value = mock_response

        _query_google_suggest('test query')

        _, kwargs = mock_fetch.call_args
        assert kwargs['params']['hl'] == 'en'

    @patch('kdp_scout.collectors.trending._query_google_suggest')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_discover_trending_passes_marketplace_hl(self, mock_rate, mock_google):
        from kdp_scout.collectors.trending import discover_trending_keywords

        mock_google.return_value = []
        discover_trending_keywords(marketplace='de')

        # All calls should pass hl='de' (German marketplace)
        for c in mock_google.call_args_list:
            assert c[1].get('hl') == 'de' or c[0][1] == 'de'

    @patch('kdp_scout.collectors.trending._query_google_suggest')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_discover_trending_fr_uses_fr_hl(self, mock_rate, mock_google):
        from kdp_scout.collectors.trending import discover_trending_keywords

        mock_google.return_value = []
        discover_trending_keywords(marketplace='fr')

        for c in mock_google.call_args_list:
            assert c[1].get('hl') == 'fr' or c[0][1] == 'fr'

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_scrape_bestsellers_uses_marketplace_url(self, mock_rate, mock_fetch):
        """Bestseller scrape should use the marketplace-specific URL."""
        from kdp_scout.collectors.trending import scrape_bestseller_keywords

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><body></body></html>'
        mock_fetch.return_value = mock_response

        scrape_bestseller_keywords(list_type='kindle', marketplace='uk')

        called_url = mock_fetch.call_args[0][0]
        assert 'amazon.co.uk' in called_url


class TestTrendingBestsellerFallback:
    """scrape_bestseller_keywords falls back to US URL for missing list types."""

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_missing_list_type_falls_back_to_us_default(
        self, mock_rate, mock_fetch, caplog,
    ):
        """FR marketplace lacks kindle_free; should warn and fall back to US URL."""
        from kdp_scout.collectors.trending import scrape_bestseller_keywords, BESTSELLER_URLS

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><body></body></html>'
        mock_fetch.return_value = mock_response

        with caplog.at_level(logging.WARNING):
            scrape_bestseller_keywords(list_type='kindle_free', marketplace='fr')

        assert any('not configured for marketplace' in r.message for r in caplog.records)
        assert any('www.amazon.fr' in r.message for r in caplog.records)
        assert any('falling back' in r.message for r in caplog.records)

        called_url = mock_fetch.call_args[0][0]
        assert called_url == BESTSELLER_URLS['kindle_free']

    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_completely_unknown_list_type_returns_empty(self, mock_rate, caplog):
        """A list type not in any map should log an error and return []."""
        from kdp_scout.collectors.trending import scrape_bestseller_keywords

        with caplog.at_level(logging.ERROR):
            result = scrape_bestseller_keywords(
                list_type='nonexistent_type', marketplace='us',
            )

        assert result == []
        assert any('Unknown bestseller list type' in r.message for r in caplog.records)
        assert any('www.amazon.com' in r.message for r in caplog.records)

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_known_list_type_uses_marketplace_url(self, mock_rate, mock_fetch):
        """When the marketplace has the list type, use its URL directly."""
        from kdp_scout.collectors.trending import scrape_bestseller_keywords

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><body></body></html>'
        mock_fetch.return_value = mock_response

        scrape_bestseller_keywords(list_type='kindle', marketplace='de')

        called_url = mock_fetch.call_args[0][0]
        assert 'amazon.de' in called_url

    @patch('kdp_scout.collectors.trending.fetch')
    @patch('kdp_scout.collectors.trending.rate_registry')
    def test_it_marketplace_kindle_free_falls_back(self, mock_rate, mock_fetch, caplog):
        """IT marketplace also lacks kindle_free; verify fallback works."""
        from kdp_scout.collectors.trending import scrape_bestseller_keywords, BESTSELLER_URLS

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<html><body></body></html>'
        mock_fetch.return_value = mock_response

        with caplog.at_level(logging.WARNING):
            scrape_bestseller_keywords(list_type='kindle_free', marketplace='it')

        assert any('falling back' in r.message for r in caplog.records)
        called_url = mock_fetch.call_args[0][0]
        assert called_url == BESTSELLER_URLS['kindle_free']


# ── keyword_engine.py ────────────────────────────────────────────────


class TestKeywordEngineMarketplace:
    """mine_keywords and ReverseASIN pass marketplace through."""

    @patch('kdp_scout.keyword_engine.KeywordRepository')
    @patch('kdp_scout.keyword_engine.init_db')
    @patch('kdp_scout.keyword_engine.mine_autocomplete')
    def test_mine_keywords_forwards_marketplace(
        self, mock_autocomplete, mock_init_db, mock_repo_cls,
    ):
        mock_autocomplete.return_value = []
        mock_repo = MagicMock()
        mock_repo.upsert_keyword.return_value = (1, True)
        mock_repo_cls.return_value = mock_repo

        from kdp_scout.keyword_engine import mine_keywords
        mine_keywords('test seed', marketplace='de')

        mock_autocomplete.assert_called_once()
        _, kwargs = mock_autocomplete.call_args
        assert kwargs['marketplace'] == 'de'

    @patch('kdp_scout.keyword_engine.KeywordRepository')
    @patch('kdp_scout.keyword_engine.init_db')
    @patch('kdp_scout.keyword_engine.mine_autocomplete')
    def test_mine_keywords_default_marketplace_is_none(
        self, mock_autocomplete, mock_init_db, mock_repo_cls,
    ):
        mock_autocomplete.return_value = []
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        from kdp_scout.keyword_engine import mine_keywords
        mine_keywords('test seed')

        _, kwargs = mock_autocomplete.call_args
        assert kwargs['marketplace'] is None

    @patch('kdp_scout.keyword_engine.rate_registry')
    @patch('kdp_scout.keyword_engine.KeywordRankingRepository')
    @patch('kdp_scout.keyword_engine.BookRepository')
    @patch('kdp_scout.keyword_engine.KeywordRepository')
    @patch('kdp_scout.keyword_engine.init_db')
    def test_reverse_asin_stores_marketplace(
        self, mock_init_db, mock_kw_repo, mock_book_repo,
        mock_ranking_repo, mock_rate,
    ):
        from kdp_scout.keyword_engine import ReverseASIN
        engine = ReverseASIN(marketplace='uk')
        assert engine._mp['domain'] == 'www.amazon.co.uk'

    @patch('kdp_scout.keyword_engine.rate_registry')
    @patch('kdp_scout.keyword_engine.KeywordRankingRepository')
    @patch('kdp_scout.keyword_engine.BookRepository')
    @patch('kdp_scout.keyword_engine.KeywordRepository')
    @patch('kdp_scout.keyword_engine.init_db')
    def test_reverse_asin_search_url_template(
        self, mock_init_db, mock_kw_repo, mock_book_repo,
        mock_ranking_repo, mock_rate,
    ):
        from kdp_scout.keyword_engine import ReverseASIN
        engine = ReverseASIN(marketplace='de')
        url = engine.SEARCH_URL_TEMPLATE.format(domain=engine._mp['domain'])
        assert url == 'https://www.amazon.de/s'


# ── competitor_engine.py ─────────────────────────────────────────────


class TestCompetitorEngineForwarding:
    """CompetitorEngine forwards marketplace to ProductScraper."""

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def test_forwards_marketplace_to_scraper(
        self, mock_repo_cls, mock_init_db, mock_scraper_cls,
    ):
        from kdp_scout.competitor_engine import CompetitorEngine
        CompetitorEngine(marketplace='fr')
        mock_scraper_cls.assert_called_once_with(marketplace='fr')

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def test_forwards_none_marketplace_to_scraper(
        self, mock_repo_cls, mock_init_db, mock_scraper_cls,
    ):
        from kdp_scout.competitor_engine import CompetitorEngine
        CompetitorEngine()
        mock_scraper_cls.assert_called_once_with(marketplace=None)


class TestCompetitorEngineBsrModel:
    """Engine._store_snapshot uses the marketplace's bsr_model."""

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def _make_engine(self, marketplace, mock_repo_cls, mock_init_db, mock_scraper_cls):
        from kdp_scout.competitor_engine import CompetitorEngine
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo
        engine = CompetitorEngine(marketplace=marketplace)
        return engine, mock_repo

    def test_us_marketplace_stores_us_kindle_model(self):
        engine, _ = self._make_engine('us')
        assert engine._marketplace['bsr_model'] == 'us_kindle'

    def test_uk_marketplace_stores_uk_kindle_model(self):
        engine, _ = self._make_engine('uk')
        assert engine._marketplace['bsr_model'] == 'uk_kindle'

    def test_de_marketplace_stores_us_kindle_model(self):
        engine, _ = self._make_engine('de')
        assert engine._marketplace['bsr_model'] == 'us_kindle'

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def test_store_snapshot_uses_marketplace_bsr_model(
        self, mock_repo_cls, mock_init_db, mock_scraper_cls,
    ):
        from kdp_scout.competitor_engine import CompetitorEngine

        mock_repo = MagicMock()
        mock_repo.add_snapshot.return_value = 42
        mock_repo_cls.return_value = mock_repo

        engine = CompetitorEngine(marketplace='uk')

        scraped = {
            'bsr_overall': 5000,
            'price_kindle': 4.99,
            'price_paperback': 12.99,
            'review_count': 100,
            'avg_rating': 4.5,
            'page_count': 200,
        }

        with patch(
            'kdp_scout.competitor_engine.estimate_daily_sales',
            wraps=estimate_daily_sales,
        ) as mock_daily, patch(
            'kdp_scout.competitor_engine.estimate_monthly_revenue',
            wraps=estimate_monthly_revenue,
        ) as mock_revenue:
            engine._store_snapshot(1, scraped)
            mock_daily.assert_called_once_with(5000, 'uk_kindle')
            mock_revenue.assert_called_once_with(5000, 4.99, 'uk_kindle')

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def test_store_snapshot_no_bsr_skips_estimation(
        self, mock_repo_cls, mock_init_db, mock_scraper_cls,
    ):
        from kdp_scout.competitor_engine import CompetitorEngine

        mock_repo = MagicMock()
        mock_repo.add_snapshot.return_value = 1
        mock_repo_cls.return_value = mock_repo

        engine = CompetitorEngine(marketplace='uk')
        scraped = {'price_kindle': 4.99}

        result = engine._store_snapshot(1, scraped)
        assert result['estimated_daily_sales'] is None
        assert result['estimated_monthly_revenue'] is None

    @patch('kdp_scout.competitor_engine.ProductScraper')
    @patch('kdp_scout.competitor_engine.init_db')
    @patch('kdp_scout.competitor_engine.BookRepository')
    def test_uk_vs_us_sales_estimates_differ(
        self, mock_repo_cls, mock_init_db, mock_scraper_cls,
    ):
        """UK and US engines produce different sales estimates for the same BSR."""
        from kdp_scout.competitor_engine import CompetitorEngine

        mock_repo = MagicMock()
        mock_repo.add_snapshot.return_value = 1
        mock_repo_cls.return_value = mock_repo

        scraped = {'bsr_overall': 1000, 'price_kindle': 4.99}

        engine_us = CompetitorEngine(marketplace='us')
        snap_us = engine_us._store_snapshot(1, scraped)

        engine_uk = CompetitorEngine(marketplace='uk')
        snap_uk = engine_uk._store_snapshot(1, scraped)

        assert snap_us['estimated_daily_sales'] != snap_uk['estimated_daily_sales']


# ── cli.py ───────────────────────────────────────────────────────────


class TestCLIMarketplaceOption:
    """All marketplace-enabled CLI commands accept -m/--marketplace."""

    def _get_main(self):
        from kdp_scout.cli import main
        return main

    def test_mine_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['mine', '--help'])
        assert '--marketplace' in result.output
        assert '-m' in result.output

    def test_track_add_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['track', 'add', '--help'])
        assert '--marketplace' in result.output

    def test_track_snapshot_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['track', 'snapshot', '--help'])
        assert '--marketplace' in result.output

    def test_reverse_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['reverse', '--help'])
        assert '--marketplace' in result.output

    def test_discover_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['discover', '--help'])
        assert '--marketplace' in result.output

    def test_trending_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['trending', '--help'])
        assert '--marketplace' in result.output

    def test_mine_categories_has_marketplace_option(self):
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['mine-categories', '--help'])
        assert '--marketplace' in result.output

    def test_marketplace_choices_match_config(self):
        """CLI marketplace choices must match MARKETPLACES keys."""
        from kdp_scout.cli import _marketplace_codes
        assert set(_marketplace_codes) == set(MARKETPLACES.keys())

    def test_mine_rejects_invalid_marketplace(self):
        """Click.Choice should reject unsupported marketplace codes."""
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['mine', '-m', 'zz', 'test'])
        assert result.exit_code != 0
        assert 'Invalid value' in result.output or 'invalid choice' in result.output.lower()

    @patch('kdp_scout.keyword_engine.mine_keywords')
    @patch('kdp_scout.keyword_engine.init_db')
    def test_mine_passes_marketplace_to_engine(self, mock_init_db, mock_mine):
        """mine -m de should forward 'de' to mine_keywords."""
        mock_mine.return_value = {
            'new_count': 0,
            'existing_count': 0,
            'total_mined': 0,
            'keywords': [],
        }
        runner = CliRunner()
        result = runner.invoke(self._get_main(), ['mine', '-m', 'de', 'test'])

        # Check that the panel shows DE marketplace
        assert 'amazon.de' in result.output.lower() or 'de' in result.output.lower()

    @patch('kdp_scout.competitor_engine.CompetitorEngine')
    def test_track_add_passes_marketplace(self, mock_engine_cls):
        """track add -m uk should create CompetitorEngine(marketplace='uk')."""
        mock_engine = MagicMock()
        mock_engine.add_book.return_value = {
            'book_id': 1, 'asin': 'B001234ABC', 'title': 'Test',
            'author': 'Author', 'is_own': False, 'is_new': True,
            'scraped': {'title': 'Test'}, 'snapshot': {
                'bsr_overall': 1000, 'estimated_daily_sales': 10,
                'estimated_monthly_revenue': 100,
                'review_count': 50, 'avg_rating': 4.5,
                'price_kindle': 4.99, 'price_paperback': 12.99,
            },
        }
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        runner.invoke(self._get_main(), ['track', 'add', '-m', 'uk', 'B001234ABC'])

        mock_engine_cls.assert_called_once_with(marketplace='uk')

    @patch('kdp_scout.competitor_engine.CompetitorEngine')
    def test_track_snapshot_passes_marketplace(self, mock_engine_cls):
        """track snapshot -m de should create CompetitorEngine(marketplace='de')."""
        mock_engine = MagicMock()
        mock_engine.list_books.return_value = []
        mock_engine_cls.return_value = mock_engine

        runner = CliRunner()
        runner.invoke(self._get_main(), ['track', 'snapshot', '-m', 'de'])

        mock_engine_cls.assert_called_once_with(marketplace='de')


class TestCLIMarketplaceErrorHandling:
    """CLI commands show clean errors for invalid marketplace in environment."""

    def test_mine_invalid_marketplace_env(self):
        from kdp_scout.cli import main
        runner = CliRunner()

        with patch.object(
            __import__('kdp_scout.config', fromlist=['Config']).Config,
            'MARKETPLACE', 'zz',
        ):
            result = runner.invoke(main, ['mine', 'test seed'])

        assert result.exit_code != 0
        assert 'Unknown marketplace' in result.output or 'Error' in result.output

    def test_trending_invalid_marketplace_env(self):
        from kdp_scout.cli import main
        runner = CliRunner()

        with patch.object(
            __import__('kdp_scout.config', fromlist=['Config']).Config,
            'MARKETPLACE', 'zz',
        ):
            result = runner.invoke(main, ['trending'])

        assert result.exit_code != 0
        assert 'Unknown marketplace' in result.output or 'Error' in result.output

    def test_mine_valid_marketplace_no_error(self):
        from kdp_scout.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ['mine', '--help'])
        assert result.exit_code == 0
