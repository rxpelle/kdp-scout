"""Scavio API product source for competitor tracking.

An optional alternative to ProductScraper: reads the Amazon product from the
Scavio API (https://scavio.dev) instead of loading the product page, so
snapshots keep working when Amazon serves a CAPTCHA or a 403. Selected with
PRODUCT_SOURCE=scavio and needs SCAVIO_API_KEY.

Each product lookup is one API request (1 credit). Requests are not retried.
"""

import logging
import re

import requests

from kdp_scout.collectors.base import BaseCollector
from kdp_scout.config import Config, get_marketplace

logger = logging.getLogger(__name__)

PRODUCT_ENDPOINT = 'https://api.scavio.dev/api/v1/amazon/product'
REQUEST_TIMEOUT = 60

# KDP Scout marketplace code -> Scavio country code
COUNTRIES = {
    'us': 'us',
    'uk': 'gb',
    'de': 'de',
    'fr': 'fr',
    'es': 'es',
    'it': 'it',
    'ca': 'ca',
    'au': 'au',
}

# Store-wide rankings; the lowest of these is the overall BSR, as in ProductScraper
OVERALL_BSR_CATEGORIES = ('kindle store', 'books', 'amazon books')

ERROR_REASONS = {
    401: 'API key rejected, check SCAVIO_API_KEY',
    402: 'no credits left on the Scavio account',
    429: 'rate limited, try again later',
}


class ScavioProductCollector(BaseCollector):
    """Reads Amazon book data from the Scavio API.

    scrape_product() returns the same dict as ProductScraper.scrape_product(),
    so CompetitorEngine can use either one.
    """

    name = 'scavio'

    def __init__(self, marketplace=None, config=None):
        """Initialize for a marketplace.

        Args:
            marketplace: Two-letter country code ('us', 'de', etc.).
            config: Config class (defaults to global Config).
        """
        self._config = config or Config
        self._api_key = self._config.SCAVIO_API_KEY
        self._mp_code = (marketplace or self._config.MARKETPLACE).lower()
        # validates the code the same way ProductScraper does
        get_marketplace(self._mp_code)

    def is_available(self):
        """Check if the API key is configured.

        Returns:
            True if SCAVIO_API_KEY is set.
        """
        return bool(self._api_key)

    def collect(self, query, **kwargs):
        """Collect product data for an ASIN.

        Args:
            query: Amazon ASIN.

        Returns:
            List with one product dict, or an empty list.
        """
        data = self.scrape_product(query)
        return [data] if data else []

    def scrape_product(self, asin):
        """Read an Amazon product through the Scavio API.

        Args:
            asin: Amazon Standard Identification Number.

        Returns:
            Dict with the ProductScraper fields, or None on any error.
            page_count, publication_date and description are always None:
            the API does not return them.
        """
        if not self.is_available():
            logger.error(
                'PRODUCT_SOURCE is scavio but SCAVIO_API_KEY is not set in .env.'
            )
            return None

        country = COUNTRIES.get(self._mp_code)
        if country is None:
            logger.error(f'Scavio has no Amazon marketplace for "{self._mp_code}"')
            return None

        logger.info(f'Reading ASIN {asin} from the Scavio API ({country})')

        try:
            response = requests.post(
                PRODUCT_ENDPOINT,
                json={'query': asin, 'country': country},
                headers={'Authorization': f'Bearer {self._api_key}'},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.error(f'Scavio request failed for ASIN {asin}: {e}')
            return None

        if response.status_code != 200:
            reason = ERROR_REASONS.get(response.status_code, 'request failed')
            logger.error(
                f'Scavio API returned {response.status_code} for ASIN {asin}: '
                f'{reason} ({response.text[:200]})'
            )
            return None

        try:
            product = response.json().get('data') or {}
        except ValueError:
            logger.error(f'Scavio API returned invalid JSON for ASIN {asin}')
            return None

        if not product:
            logger.warning(f'Scavio API returned no product for ASIN {asin}')
            return None

        return self._to_scraper_fields(asin, product)

    def _to_scraper_fields(self, asin, product):
        """Map a Scavio product onto the ProductScraper dict.

        Args:
            asin: The requested ASIN.
            product: The API response's data object.

        Returns:
            Dict with the ProductScraper fields.
        """
        author, book_format = _parse_byline(product.get('brand'))
        price = product.get('price')

        bsr_overall, bsr_categories = _parse_bsr(product.get('best_sellers_rank'))

        data = {
            'asin': asin,
            'title': product.get('title'),
            'author': author,
            'bsr_overall': bsr_overall,
            'bsr_categories': bsr_categories,
            # the price belongs to the format of this ASIN only
            'price_kindle': price if book_format and 'kindle' in book_format else None,
            'price_paperback': price if book_format and 'paperback' in book_format else None,
            'review_count': product.get('reviews_count'),
            'avg_rating': product.get('rating'),
            'page_count': None,
            'categories': _parse_categories(product.get('categories'), bsr_categories),
            'publication_date': None,
            'description': None,
        }

        logger.info(
            f'Read ASIN {asin}: title="{data["title"]}", '
            f'BSR={data["bsr_overall"]}, '
            f'reviews={data["review_count"]}, '
            f'rating={data["avg_rating"]}'
        )

        return data


def _parse_byline(brand):
    """Split the byline into author and format.

    The byline looks like "Andy Weir (Author) Format: Kindle Edition".

    Args:
        brand: The product's brand string.

    Returns:
        Tuple of (author or None, lowercase format or None).
    """
    if not brand:
        return None, None

    text = ' '.join(brand.split())

    book_format = None
    format_match = re.search(r'Format:\s*(.+)$', text)
    if format_match:
        book_format = format_match.group(1).strip().lower()
        text = text[:format_match.start()].strip()

    author = re.sub(r'\s*\((Author|Editor|Illustrator|Narrator|Translator)\)', '', text)
    author = author.strip(' ,') or None

    return author, book_format


def _parse_bsr(ranks):
    """Split best_sellers_rank into the overall rank and category ranks.

    Args:
        ranks: List of {category, rank} dicts.

    Returns:
        Tuple of (bsr_overall, bsr_categories).
    """
    bsr_overall = None
    bsr_categories = {}

    for entry in ranks or []:
        category = (entry.get('category') or '').strip()
        rank = entry.get('rank')
        if not category or not isinstance(rank, int):
            continue

        if category.lower() in OVERALL_BSR_CATEGORIES:
            if bsr_overall is None or rank < bsr_overall:
                bsr_overall = rank
        else:
            bsr_categories[category] = rank

    return bsr_overall, bsr_categories


def _parse_categories(breadcrumb, bsr_categories):
    """Build the category list the way ProductScraper does.

    Args:
        breadcrumb: List of {name, url, node} dicts.
        bsr_categories: Dict of category name -> rank.

    Returns:
        List of category strings: the breadcrumb path, then BSR categories.
    """
    categories = []

    path = ' > '.join(c.get('name') for c in breadcrumb or [] if c.get('name'))
    if path:
        categories.append(path)

    for name in bsr_categories:
        if name not in categories:
            categories.append(name)

    return categories
