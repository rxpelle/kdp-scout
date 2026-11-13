"""Tests for the Scavio API product source.

The responses are trimmed copies of real API answers (2026-11-13) for
Project Hail Mary, hardcover 0593135202 and Kindle B08FHBV4ZX.
requests.post is mocked, so these tests never open a socket.
"""

import copy
import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from kdp_scout.collectors.product_scraper import ProductScraper
from kdp_scout.collectors.scavio import PRODUCT_ENDPOINT, ScavioProductCollector
from kdp_scout.competitor_engine import CompetitorEngine
from kdp_scout.config import Config


HARDCOVER = {
    'data': {
        'asin': '0593135202',
        'title': 'Project Hail Mary: A Novel',
        'brand': 'Andy Weir     \n       \t\t\t(Author) \n       \t             Format: Hardcover',
        'price': 19.29,
        'list_price': 32,
        'currency': 'USD',
        'rating': 4.7,
        'reviews_count': 287264,
        'best_sellers_rank': [
            {'category': 'Books', 'rank': 1844},
            {'category': 'Hard Science Fiction', 'rank': 1},
            {'category': 'Humorous Science Fiction', 'rank': 2},
            {'category': 'Science Fiction Adventures', 'rank': 4},
        ],
        'categories': [
            {'name': 'Books', 'node': '283155'},
            {'name': 'Literature & Fiction', 'node': '17'},
            {'name': 'Action & Adventure', 'node': '720360'},
            {'name': 'Mystery, Thriller & Suspense', 'node': '10178'},
        ],
        'description': 'From the Publisher',
        'url': 'https://www.amazon.com/dp/0593135202',
    },
}

KINDLE = {
    'data': {
        'asin': 'B08FHBV4ZX',
        'title': 'Project Hail Mary: A Novel',
        'brand': 'Andy Weir     \n       \t\t\t(Author) \n       \t             Format: Kindle Edition',
        'price': None,
        'list_price': None,
        'currency': 'USD',
        'rating': 4.7,
        'reviews_count': 287264,
        'best_sellers_rank': [
            {'category': 'Kindle Store', 'rank': 717},
            {'category': 'Hard Science Fiction', 'rank': 1},
            {'category': 'Hard Science Fiction', 'rank': 2},
            {'category': 'Science Fiction Adventures', 'rank': 4},
        ],
        'categories': [
            {'name': 'Kindle Store', 'node': '133140011'},
            {'name': 'Kindle eBooks', 'node': '154606011'},
        ],
        'url': 'https://www.amazon.com/dp/B08FHBV4ZX',
    },
}

SCRAPER_FIELDS = {
    'asin', 'title', 'author', 'bsr_overall', 'bsr_categories', 'price_kindle',
    'price_paperback', 'review_count', 'avg_rating', 'page_count', 'categories',
    'publication_date', 'description',
}


def _response(status_code=200, payload=None, text=''):
    response = MagicMock(status_code=status_code, text=text)
    response.json.return_value = payload
    return response


@pytest.fixture
def scavio_key(monkeypatch):
    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', 'test-scavio-key')


def test_hardcover_maps_to_scraper_fields(scavio_key):
    with patch('requests.post', return_value=_response(payload=HARDCOVER)):
        data = ScavioProductCollector(marketplace='us').scrape_product('0593135202')

    assert set(data) == SCRAPER_FIELDS
    assert data['asin'] == '0593135202'
    assert data['title'] == 'Project Hail Mary: A Novel'
    assert data['author'] == 'Andy Weir'
    assert data['bsr_overall'] == 1844
    assert data['bsr_categories'] == {
        'Hard Science Fiction': 1,
        'Humorous Science Fiction': 2,
        'Science Fiction Adventures': 4,
    }
    assert data['review_count'] == 287264
    assert data['avg_rating'] == 4.7
    assert data['categories'][0] == (
        'Books > Literature & Fiction > Action & Adventure > Mystery, Thriller & Suspense'
    )
    assert data['categories'][1:] == [
        'Hard Science Fiction', 'Humorous Science Fiction', 'Science Fiction Adventures',
    ]
    # a hardcover price is neither the Kindle nor the paperback price
    assert data['price_kindle'] is None
    assert data['price_paperback'] is None
    assert data['page_count'] is None
    assert data['publication_date'] is None
    assert data['description'] is None


def test_kindle_bsr_comes_from_the_kindle_store(scavio_key):
    with patch('requests.post', return_value=_response(payload=KINDLE)):
        data = ScavioProductCollector(marketplace='us').scrape_product('B08FHBV4ZX')

    assert data['bsr_overall'] == 717
    assert data['author'] == 'Andy Weir'
    # the API returned no price for this Kindle edition
    assert data['price_kindle'] is None
    assert data['categories'][0] == 'Kindle Store > Kindle eBooks'


def test_price_goes_to_the_asins_own_format(scavio_key):
    kindle = copy.deepcopy(KINDLE)
    kindle['data']['price'] = 9.99
    paperback = copy.deepcopy(HARDCOVER)
    paperback['data']['brand'] = 'Jane Doe (Author), John Roe (Illustrator) Format: Paperback'
    paperback['data']['price'] = 12.5

    collector = ScavioProductCollector(marketplace='us')
    with patch('requests.post', side_effect=[_response(payload=kindle), _response(payload=paperback)]):
        kindle_data = collector.scrape_product('B08FHBV4ZX')
        paperback_data = collector.scrape_product('0593135202')

    assert kindle_data['price_kindle'] == 9.99
    assert kindle_data['price_paperback'] is None
    assert paperback_data['price_paperback'] == 12.5
    assert paperback_data['price_kindle'] is None
    assert paperback_data['author'] == 'Jane Doe, John Roe'


def test_request_sends_asin_country_and_bearer_key(scavio_key):
    with patch('requests.post', return_value=_response(payload=HARDCOVER)) as post:
        ScavioProductCollector(marketplace='uk').scrape_product('0593135202')

    post.assert_called_once()
    assert post.call_args.args[0] == PRODUCT_ENDPOINT
    assert post.call_args.kwargs['json'] == {'query': '0593135202', 'country': 'gb'}
    assert post.call_args.kwargs['headers'] == {'Authorization': 'Bearer test-scavio-key'}
    assert post.call_args.kwargs['timeout'] == 60


def test_every_marketplace_has_a_country(scavio_key):
    from kdp_scout.config import MARKETPLACES
    from kdp_scout.collectors.scavio import COUNTRIES

    assert set(MARKETPLACES) <= set(COUNTRIES)


@pytest.mark.parametrize('status, reason', [
    (401, 'API key rejected'),
    (402, 'no credits left'),
    (429, 'rate limited'),
    (500, 'request failed'),
])
def test_api_errors_return_none_without_retry(scavio_key, caplog, status, reason):
    response = _response(status_code=status, text='{"error":"nope"}')
    with patch('requests.post', return_value=response) as post, \
            caplog.at_level(logging.ERROR, logger='kdp_scout.collectors.scavio'):
        data = ScavioProductCollector(marketplace='us').scrape_product('0593135202')

    assert data is None
    post.assert_called_once()
    assert reason in caplog.text
    assert 'test-scavio-key' not in caplog.text


def test_network_error_returns_none(scavio_key):
    with patch('requests.post', side_effect=requests.ConnectionError('down')) as post:
        data = ScavioProductCollector(marketplace='us').scrape_product('0593135202')

    assert data is None
    post.assert_called_once()


def test_missing_key_sends_no_request(monkeypatch, caplog):
    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', '')
    collector = ScavioProductCollector(marketplace='us')

    with patch('requests.post') as post, \
            caplog.at_level(logging.ERROR, logger='kdp_scout.collectors.scavio'):
        data = collector.scrape_product('0593135202')

    assert not collector.is_available()
    assert data is None
    post.assert_not_called()
    assert 'SCAVIO_API_KEY' in caplog.text


def test_response_without_product_returns_none(scavio_key):
    with patch('requests.post', return_value=_response(payload={'data': None})):
        assert ScavioProductCollector(marketplace='us').scrape_product('0593135202') is None


def test_collect_wraps_scrape_product(scavio_key):
    with patch('requests.post', return_value=_response(payload=HARDCOVER)):
        rows = ScavioProductCollector(marketplace='us').collect('0593135202')

    assert len(rows) == 1
    assert rows[0]['bsr_overall'] == 1844


def test_competitor_engine_uses_the_scraper_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DB_PATH', str(tmp_path / 'kdp_scout.db'))
    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scraper')

    engine = CompetitorEngine(marketplace='us')
    try:
        assert isinstance(engine._scraper, ProductScraper)
    finally:
        engine.close()


def test_competitor_engine_stores_a_scavio_snapshot(tmp_path, monkeypatch, scavio_key):
    monkeypatch.setattr(Config, 'DB_PATH', str(tmp_path / 'kdp_scout.db'))
    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scavio')

    engine = CompetitorEngine(marketplace='us')
    try:
        assert isinstance(engine._scraper, ScavioProductCollector)
        with patch('requests.post', return_value=_response(payload=HARDCOVER)) as post:
            result = engine.add_book('0593135202')
    finally:
        engine.close()

    post.assert_called_once()
    assert result['title'] == 'Project Hail Mary: A Novel'
    assert result['snapshot']['bsr_overall'] == 1844
