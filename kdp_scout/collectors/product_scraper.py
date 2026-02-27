"""Amazon product page scraper for competitor analysis.

Scrapes Amazon book product pages to extract BSR, pricing, reviews,
categories, page count, and other metadata. Handles multiple page
layouts that Amazon serves and detects CAPTCHA/soft-block pages.
"""

import re
import json
import logging

from bs4 import BeautifulSoup

from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

PRODUCT_URL = 'https://www.amazon.com/dp/{asin}'


class CaptchaDetected(Exception):
    """Raised when Amazon serves a CAPTCHA or soft-block page."""
    pass


class ProductScraper:
    """Scrapes Amazon product pages for book metadata.

    Uses the shared HTTP client with rate limiting and user-agent rotation.
    Handles multiple Amazon page layouts by trying multiple selectors
    for each data field.
    """

    def __init__(self):
        """Initialize the scraper and register the rate limiter."""
        rate_registry.get_limiter('product_page', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)

    def scrape_product(self, asin):
        """Scrape an Amazon product page for book data.

        Args:
            asin: Amazon Standard Identification Number.

        Returns:
            Dict with product data fields:
                - title: str or None
                - author: str or None
                - bsr_overall: int or None
                - bsr_categories: dict (category_name -> rank) or {}
                - price_kindle: float or None
                - price_paperback: float or None
                - review_count: int or None
                - avg_rating: float or None
                - page_count: int or None
                - categories: list of category path strings
                - publication_date: str or None
                - description: str or None

        Raises:
            CaptchaDetected: If Amazon serves a CAPTCHA page.
            requests.RequestException: On network failure after retries.
        """
        # Respect rate limiting
        rate_registry.acquire('product_page')

        url = PRODUCT_URL.format(asin=asin)
        logger.info(f'Scraping product page: {url}')

        response = fetch(url, headers=get_browser_headers())

        if response.status_code != 200:
            logger.warning(f'Product page returned {response.status_code} for ASIN {asin}')
            return None

        html = response.text

        # Detect CAPTCHA / soft-block pages
        self._check_for_captcha(html)

        soup = BeautifulSoup(html, 'html.parser')

        data = {
            'asin': asin,
            'title': self._parse_title(soup),
            'author': self._parse_author(soup),
            'bsr_overall': None,
            'bsr_categories': {},
            'price_kindle': self._parse_kindle_price(soup),
            'price_paperback': self._parse_paperback_price(soup),
            'review_count': self._parse_review_count(soup),
            'avg_rating': self._parse_avg_rating(soup),
            'page_count': self._parse_page_count(soup),
            'categories': self._parse_categories(soup),
            'publication_date': self._parse_publication_date(soup),
            'description': self._parse_description(soup),
        }

        # Parse BSR (sets both bsr_overall and bsr_categories)
        bsr_overall, bsr_categories = self._parse_bsr(soup)
        data['bsr_overall'] = bsr_overall
        data['bsr_categories'] = bsr_categories

        logger.info(
            f'Scraped ASIN {asin}: title="{data["title"]}", '
            f'BSR={data["bsr_overall"]}, '
            f'reviews={data["review_count"]}, '
            f'rating={data["avg_rating"]}'
        )

        return data

    def _check_for_captcha(self, html):
        """Check if the page is a CAPTCHA or soft-block response.

        Args:
            html: Raw HTML string.

        Raises:
            CaptchaDetected: If CAPTCHA markers are found.
        """
        captcha_markers = [
            'Enter the characters you see below',
            'Sorry, we just need to make sure you\'re not a robot',
            'api-services-support@amazon.com',
            'Type the characters you see in this image',
            '/errors/validateCaptcha',
        ]
        html_lower = html.lower()
        for marker in captcha_markers:
            if marker.lower() in html_lower:
                logger.warning('CAPTCHA detected on Amazon product page')
                raise CaptchaDetected(
                    'Amazon is requesting CAPTCHA verification. '
                    'Try again later or use a proxy.'
                )

    def _parse_title(self, soup):
        """Extract the book title."""
        # Kindle / ebook title
        for selector in ['#ebooksProductTitle', '#productTitle']:
            el = soup.select_one(selector)
            if el:
                return el.get_text(strip=True)

        # Fallback: meta tag
        meta = soup.find('meta', attrs={'name': 'title'})
        if meta and meta.get('content'):
            return meta['content'].strip()

        return None

    def _parse_author(self, soup):
        """Extract the author name."""
        # Try byline info area
        byline = soup.select_one('#bylineInfo')
        if byline:
            # Look for author link
            author_link = byline.select_one('.author a, a.contributorNameID')
            if author_link:
                return author_link.get_text(strip=True)
            # Fallback: get all text from byline
            text = byline.get_text(strip=True)
            # Clean up common prefixes
            text = re.sub(r'^by\s+', '', text, flags=re.IGNORECASE)
            if text:
                return text.split('(')[0].strip()

        # Try .author class
        author_el = soup.select_one('.author a')
        if author_el:
            return author_el.get_text(strip=True)

        return None

    def _parse_bsr(self, soup):
        """Extract BSR overall and category rankings.

        Returns:
            Tuple of (bsr_overall, bsr_categories) where bsr_categories
            is a dict of category_name -> rank.
        """
        bsr_overall = None
        bsr_categories = {}

        # Method 1: Product details table
        details = soup.select_one('#productDetails_detailBullets_sections1')
        if details:
            bsr_overall, bsr_categories = self._parse_bsr_from_table(details)

        # Method 2: Detail bullets wrapper
        if bsr_overall is None:
            bullets = soup.select_one('#detailBulletsWrapper_feature_div')
            if bullets:
                bsr_overall, bsr_categories = self._parse_bsr_from_bullets(bullets)

        # Method 3: Product details section (alternate layout)
        if bsr_overall is None:
            detail_section = soup.select_one('#detailBullets_feature_div')
            if detail_section:
                bsr_overall, bsr_categories = self._parse_bsr_from_bullets(detail_section)

        # Method 4: Search all text for BSR pattern
        if bsr_overall is None:
            bsr_overall, bsr_categories = self._parse_bsr_from_text(soup)

        return bsr_overall, bsr_categories

    def _parse_bsr_from_table(self, table):
        """Parse BSR from a product details table element."""
        bsr_overall = None
        bsr_categories = {}

        for row in table.select('tr'):
            header = row.select_one('th')
            if header and 'best sellers rank' in header.get_text().lower():
                value_td = row.select_one('td')
                if value_td:
                    text = value_td.get_text()
                    bsr_overall, bsr_categories = self._extract_bsr_numbers(text)
                break

        return bsr_overall, bsr_categories

    def _parse_bsr_from_bullets(self, container):
        """Parse BSR from a bullet-list style layout."""
        bsr_overall = None
        bsr_categories = {}

        text = container.get_text()
        # Find the BSR section
        bsr_match = re.search(
            r'Best\s*Sellers?\s*Rank[:\s]*(.*?)(?=Customer\s*Reviews|$)',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if bsr_match:
            bsr_text = bsr_match.group(1)
            bsr_overall, bsr_categories = self._extract_bsr_numbers(bsr_text)

        return bsr_overall, bsr_categories

    def _parse_bsr_from_text(self, soup):
        """Fallback: search entire page text for BSR patterns."""
        bsr_overall = None
        bsr_categories = {}

        text = soup.get_text()
        # Look for "#1,234 in Kindle Store" pattern
        overall_match = re.search(
            r'#([\d,]+)\s+in\s+(?:Amazon\s+)?(?:Kindle\s+Store|Books)',
            text,
            re.IGNORECASE,
        )
        if overall_match:
            bsr_overall = int(overall_match.group(1).replace(',', ''))

        # Look for category ranks: "#123 in Category Name"
        cat_matches = re.finditer(
            r'#([\d,]+)\s+in\s+([A-Z][^(#\n]+?)(?:\s*\(|$|\n)',
            text,
        )
        for match in cat_matches:
            rank = int(match.group(1).replace(',', ''))
            category = match.group(2).strip()
            if category.lower() not in ('kindle store', 'books'):
                bsr_categories[category] = rank

        return bsr_overall, bsr_categories

    def _extract_bsr_numbers(self, text):
        """Extract BSR numbers from a text block containing rank info.

        Args:
            text: Text containing BSR info like "#1,234 in Kindle Store"

        Returns:
            Tuple of (overall_rank, category_dict).
        """
        bsr_overall = None
        bsr_categories = {}

        # Find all "#number in Category" patterns
        matches = re.finditer(
            r'#([\d,]+)\s+in\s+([^(#\n]+?)(?:\s*\(|$|\n|#)',
            text,
        )

        for match in matches:
            rank = int(match.group(1).replace(',', ''))
            category = match.group(2).strip()

            # The first/lowest rank in "Kindle Store" or "Books" is the overall rank
            if category.lower() in ('kindle store', 'books', 'amazon books'):
                if bsr_overall is None or rank < bsr_overall:
                    bsr_overall = rank
            else:
                bsr_categories[category] = rank

        return bsr_overall, bsr_categories

    def _parse_kindle_price(self, soup):
        """Extract the Kindle price."""
        # Try multiple price selectors
        for selector in [
            '#kindle-price',
            '.kindle-price .a-size-base',
            '#price',
            '.kindle-price',
            '#digital-list-price .a-color-price',
            'span.kindle-price span',
        ]:
            el = soup.select_one(selector)
            if el:
                price = self._extract_price(el.get_text())
                if price is not None:
                    return price

        # Try finding price in the format switcher
        format_sections = soup.select('.swatchElement')
        for section in format_sections:
            text = section.get_text().lower()
            if 'kindle' in text:
                price = self._extract_price(text)
                if price is not None:
                    return price

        return None

    def _parse_paperback_price(self, soup):
        """Extract the paperback price."""
        # Try format switcher
        format_sections = soup.select('.swatchElement')
        for section in format_sections:
            text = section.get_text().lower()
            if 'paperback' in text:
                price = self._extract_price(text)
                if price is not None:
                    return price

        # Try alternate layout
        for selector in [
            '#paperback_meta_binding_price',
            '#a-autoid-3-announce .a-color-price',
        ]:
            el = soup.select_one(selector)
            if el:
                price = self._extract_price(el.get_text())
                if price is not None:
                    return price

        return None

    def _parse_review_count(self, soup):
        """Extract the total review count."""
        # Standard review count element
        el = soup.select_one('#acrCustomerReviewText')
        if el:
            text = el.get_text()
            match = re.search(r'([\d,]+)', text)
            if match:
                return int(match.group(1).replace(',', ''))

        # Alternate: rating count span
        el = soup.select_one('#acrCustomerReviewLink span')
        if el:
            text = el.get_text()
            match = re.search(r'([\d,]+)', text)
            if match:
                return int(match.group(1).replace(',', ''))

        return None

    def _parse_avg_rating(self, soup):
        """Extract the average star rating."""
        # Standard rating popover
        el = soup.select_one('#acrPopover')
        if el:
            title = el.get('title', '')
            match = re.search(r'([\d.]+)', title)
            if match:
                return float(match.group(1))

        # Alternate: rating text
        el = soup.select_one('.a-icon-star .a-icon-alt')
        if el:
            match = re.search(r'([\d.]+)', el.get_text())
            if match:
                return float(match.group(1))

        # Alternate: rating in the cr section
        el = soup.select_one('#averageCustomerReviews .a-icon-alt')
        if el:
            match = re.search(r'([\d.]+)', el.get_text())
            if match:
                return float(match.group(1))

        return None

    def _parse_page_count(self, soup):
        """Extract the page count from product details."""
        # Look in product detail bullets
        text = soup.get_text()

        # Pattern: "123 pages" or "Print length: 123 pages"
        match = re.search(
            r'(?:Print\s+[Ll]ength|Pages)[:\s]*([\d,]+)\s*pages?',
            text,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1).replace(',', ''))

        # Alternate pattern: just "NNN pages"
        match = re.search(r'(\d+)\s+pages?', text, re.IGNORECASE)
        if match:
            count = int(match.group(1))
            # Sanity check: page count should be reasonable
            if 10 <= count <= 5000:
                return count

        return None

    def _parse_categories(self, soup):
        """Extract category paths from breadcrumbs or BSR section."""
        categories = []

        # Method 1: Breadcrumb navigation
        breadcrumb = soup.select('#wayfinding-breadcrumbs_feature_div a')
        if breadcrumb:
            path = ' > '.join(a.get_text(strip=True) for a in breadcrumb)
            if path:
                categories.append(path)

        # Method 2: Categories from BSR section
        bsr_categories = {}
        _, bsr_categories = self._parse_bsr(soup)
        for cat_name in bsr_categories:
            if cat_name not in categories:
                categories.append(cat_name)

        return categories

    def _parse_publication_date(self, soup):
        """Extract the publication date."""
        text = soup.get_text()

        # Pattern: "Publication date: January 1, 2024"
        match = re.search(
            r'Publication\s+[Dd]ate[:\s]*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})',
            text,
        )
        if match:
            return match.group(1).strip()

        # Pattern: "Publisher: ... (January 1, 2024)"
        match = re.search(
            r'Publisher[:\s].*?\(([A-Z][a-z]+\s+\d{1,2},\s*\d{4})\)',
            text,
        )
        if match:
            return match.group(1).strip()

        return None

    def _parse_description(self, soup):
        """Extract the book description."""
        # Kindle description iframe content
        desc = soup.select_one('#bookDescription_feature_div .a-expander-content')
        if desc:
            return desc.get_text(strip=True)

        # Alternate selectors
        for selector in [
            '#bookDescription_feature_div',
            '#productDescription',
            '#book_description_expander',
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text

        return None

    def _extract_price(self, text):
        """Extract a dollar price from text.

        Args:
            text: Text possibly containing a price like "$9.99".

        Returns:
            Float price or None if no price found or price is zero.
        """
        match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
        if match:
            try:
                price = float(match.group(1).replace(',', ''))
                # Treat $0.00 as no price (often "free with KU" artifacts)
                return price if price > 0 else None
            except ValueError:
                return None
        return None
