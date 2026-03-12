"""Trending keyword discovery for Amazon KDP.

Discovers top/trending keywords without needing a seed phrase by:
1. Scraping Amazon Kindle bestseller pages for titles and categories
2. Using Google suggest with book-related query patterns
3. Mining a curated list of major KDP categories via autocomplete
"""

import logging
import re
import string

from bs4 import BeautifulSoup

from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config, get_marketplace

logger = logging.getLogger(__name__)

# Default Amazon Kindle bestseller pages (US fallback, overridden by marketplace)
BESTSELLER_URLS = {
    'kindle': 'https://www.amazon.com/gp/bestsellers/digital-text/',
    'kindle_free': 'https://www.amazon.com/gp/bestsellers/digital-text/154606011/',
    'kindle_new': 'https://www.amazon.com/gp/new-releases/digital-text/',
    'kindle_movers': 'https://www.amazon.com/gp/movers-and-shakers/digital-text/',
}

# Major KDP book categories to auto-mine
KDP_CATEGORY_SEEDS = [
    'romance',
    'thriller',
    'mystery',
    'science fiction',
    'fantasy',
    'historical fiction',
    'horror',
    'contemporary fiction',
    'literary fiction',
    'young adult',
    'children books',
    'self help',
    'personal development',
    'business',
    'entrepreneurship',
    'memoir',
    'biography',
    'true crime',
    'cookbook',
    'health and fitness',
    'weight loss',
    'meditation',
    'mindfulness',
    'parenting',
    'relationship',
    'money management',
    'investing',
    'real estate',
    'coloring book',
    'activity book',
    'journal',
    'planner',
    'workbook',
    'puzzle book',
    'word search',
    'sudoku',
    'poetry',
    'short stories',
    'graphic novel',
    'manga',
    'dystopian',
    'urban fantasy',
    'paranormal romance',
    'cozy mystery',
    'psychological thriller',
    'military science fiction',
    'space opera',
    'dark romance',
    'reverse harem',
    'litrpg',
]

# Google suggest query patterns for discovering trending book topics
TRENDING_PATTERNS = [
    'best {category} books 2025',
    'best {category} books 2026',
    '{category} books like',
    'new {category} books',
    'top {category} kindle',
    '{category} kindle unlimited',
    '{category} book recommendations',
]

# Base categories for trending pattern expansion
TRENDING_BASE_CATEGORIES = [
    'romance', 'thriller', 'mystery', 'fantasy', 'sci fi',
    'horror', 'self help', 'historical fiction', 'young adult',
    'true crime', 'memoir', 'business',
]


def scrape_bestseller_keywords(list_type='kindle', marketplace=None,
                               progress_callback=None):
    """Scrape Amazon Kindle bestseller pages for keyword ideas.

    Extracts book titles and categories from bestseller listings,
    then distills them into keyword phrases.

    Args:
        list_type: One of 'kindle', 'kindle_free', 'kindle_new', 'kindle_movers'.
        marketplace: Two-letter country code ('us', 'de', etc.).
        progress_callback: Optional callable(completed, total) for progress.

    Returns:
        List of (keyword, source_info) tuples.
    """
    rate_registry.get_limiter('product_scrape', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)

    mp = get_marketplace(marketplace)
    mp_urls = mp.get('bestsellers', BESTSELLER_URLS)
    mp_identifier = mp.get('domain') or marketplace or 'unknown'
    url = mp_urls.get(list_type)
    if not url:
        fallback_url = BESTSELLER_URLS.get(list_type)
        if fallback_url:
            logger.warning(
                f'Bestseller list type "{list_type}" not configured for marketplace '
                f'"{mp_identifier}"; falling back to default URL.'
            )
            url = fallback_url
        else:
            logger.error(
                f'Unknown bestseller list type "{list_type}" for marketplace '
                f'"{mp_identifier}"'
            )
            return []

    rate_registry.acquire('product_scrape')

    try:
        response = fetch(url, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error fetching bestseller page: {e}')
        return []

    if response.status_code != 200:
        logger.warning(f'Bestseller page returned {response.status_code}')
        return []

    html = response.text

    # Check for CAPTCHA
    if _is_captcha(html):
        logger.warning('CAPTCHA detected on bestseller page')
        return []

    soup = BeautifulSoup(html, 'html.parser')
    keywords = {}

    # Extract from book titles
    title_keywords = _extract_title_keywords(soup)
    for kw, info in title_keywords:
        if kw not in keywords:
            keywords[kw] = info

    # Extract category/genre names from breadcrumbs and category links
    cat_keywords = _extract_category_keywords(soup)
    for kw, info in cat_keywords:
        if kw not in keywords:
            keywords[kw] = info

    results = list(keywords.items())

    if progress_callback:
        progress_callback(1, 1)

    logger.info(f'Bestseller scrape ({list_type}): {len(results)} keywords extracted')
    return results


def discover_trending_keywords(marketplace=None, progress_callback=None):
    """Discover trending book keywords via Google suggest.

    Uses book-related query patterns with Google's autocomplete API
    to find currently trending topics and genres.

    Args:
        marketplace: Two-letter country code for language hint.
        progress_callback: Optional callable(completed, total) for progress.

    Returns:
        List of (keyword, position) tuples, deduplicated and sorted.
    """
    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)

    mp = get_marketplace(marketplace)
    all_results = {}
    queries = []

    for category in TRENDING_BASE_CATEGORIES:
        for pattern in TRENDING_PATTERNS:
            queries.append(pattern.format(category=category))

    total = len(queries)
    completed = 0

    for query in queries:
        suggestions = _query_google_suggest(query, hl=mp['google_hl'])
        for kw, pos in suggestions:
            # Clean up the keyword for KDP relevance
            cleaned = _clean_book_keyword(kw)
            if cleaned and len(cleaned) >= 3:
                if cleaned not in all_results or pos < all_results[cleaned]:
                    all_results[cleaned] = pos

        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))
    logger.info(f'Trending discovery: {len(results)} keywords found')
    return results


def get_category_seeds():
    """Return the built-in list of KDP category seed keywords.

    Returns:
        List of category seed strings.
    """
    return list(KDP_CATEGORY_SEEDS)


def _extract_title_keywords(soup):
    """Extract keyword phrases from bestseller book titles.

    Looks for common genre/topic words in titles and extracts
    relevant multi-word phrases.

    Args:
        soup: BeautifulSoup parsed HTML of bestseller page.

    Returns:
        List of (keyword, source_info) tuples.
    """
    results = []

    # Find product title links - Amazon uses various selectors
    title_selectors = [
        'div.p13n-sc-truncate',
        'div._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y',
        'span.zg-text-center-align a span',
        'a.a-link-normal span.a-size-base',
        'div[id^="p13n-asin-index-"] span.a-size-small',
    ]

    titles = []
    for selector in title_selectors:
        elements = soup.select(selector)
        if elements:
            for el in elements:
                text = el.get_text(strip=True)
                if text and len(text) > 5:
                    titles.append(text)
            break

    # Also try finding all product links with titles
    if not titles:
        for link in soup.find_all('a', class_='a-link-normal'):
            span = link.find('span')
            if span:
                text = span.get_text(strip=True)
                if text and 10 < len(text) < 200:
                    titles.append(text)

    for title in titles[:50]:  # Limit to top 50
        # Extract genre/topic phrases from title
        phrases = _extract_phrases_from_title(title)
        for phrase in phrases:
            results.append((phrase, f'bestseller title: {title[:50]}'))

    return results


def _extract_phrases_from_title(title):
    """Extract relevant keyword phrases from a book title.

    Args:
        title: Book title string.

    Returns:
        List of keyword phrase strings.
    """
    # Clean the title
    title = title.lower().strip()

    # Remove common noise words and punctuation
    title = re.sub(r'[:()\[\]{}|#*]', ' ', title)
    title = re.sub(r'\b(a|an|the|of|in|on|at|to|for|and|or|but|is|are|was|were|be|been|have|has|had|do|does|did|will|would|could|should|may|might|can|shall|must|need|dare|ought|used|am|with|by|from|into|through|during|before|after|above|below|between|out|off|over|under|again|further|then|once|here|there|when|where|why|how|all|each|every|both|few|more|most|other|some|such|no|not|only|own|same|so|than|too|very)\b', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()

    # Remove edition/volume markers
    title = re.sub(r'\b(book|volume|edition|series|novel|part)\s*\d*\b', '', title)
    title = re.sub(r'\s+', ' ', title).strip()

    phrases = []

    # Get 2-3 word combinations
    words = title.split()
    if len(words) >= 2:
        for i in range(len(words) - 1):
            bigram = f'{words[i]} {words[i+1]}'
            if len(bigram) >= 5 and not bigram.isdigit():
                phrases.append(bigram)

        for i in range(len(words) - 2):
            trigram = f'{words[i]} {words[i+1]} {words[i+2]}'
            if len(trigram) >= 8:
                phrases.append(trigram)

    return phrases


def _extract_category_keywords(soup):
    """Extract category and genre keywords from the page.

    Args:
        soup: BeautifulSoup parsed HTML.

    Returns:
        List of (keyword, source_info) tuples.
    """
    results = []

    # Find category links in the sidebar/breadcrumbs
    cat_selectors = [
        'ul#zg_browseRoot a',
        'div._p13n-zg-nav-tree-all_style_zg-browse-group__88fbz a',
        'span.zg_selected',
        'div.zg_browseRoot a',
    ]

    for selector in cat_selectors:
        elements = soup.select(selector)
        for el in elements:
            text = el.get_text(strip=True).lower()
            # Filter out non-category text
            if (text and 3 <= len(text) <= 50
                    and text not in ('any department', 'kindle store', 'kindle ebooks')
                    and not text.startswith('see top')):
                results.append((text, 'bestseller category'))

    return results


def _query_google_suggest(query, hl='en'):
    """Query Google's autocomplete for book-related suggestions.

    Args:
        query: Search query string.
        hl: Language hint for Google (e.g., 'en', 'de').

    Returns:
        List of (keyword, position) tuples.
    """
    rate_registry.acquire('autocomplete')

    url = 'https://suggestqueries.google.com/complete/search'
    params = {
        'client': 'firefox',
        'q': query,
        'hl': hl,
    }

    try:
        response = fetch(url, params=params)
        if response.status_code != 200:
            return []

        data = response.json()
        if not isinstance(data, list) or len(data) < 2:
            return []

        suggestions = data[1]
        results = []
        for i, suggestion in enumerate(suggestions):
            keyword = suggestion.strip().lower()
            if keyword and keyword != query.lower():
                results.append((keyword, i + 1))

        logger.debug(f'Google suggest "{query}" -> {len(results)} results')
        return results

    except Exception as e:
        logger.debug(f'Google suggest failed for "{query}": {e}')
        return []


def _clean_book_keyword(keyword):
    """Clean a Google suggest result into a KDP-relevant keyword.

    Removes "best", "books", year numbers, and other noise to
    extract the core topic/genre phrase.

    Args:
        keyword: Raw keyword string.

    Returns:
        Cleaned keyword string, or empty string if not useful.
    """
    kw = keyword.lower().strip()

    # Remove common prefixes
    for prefix in ['best ', 'top ', 'new ', 'most popular ']:
        if kw.startswith(prefix):
            kw = kw[len(prefix):]

    # Remove year references
    kw = re.sub(r'\b20\d{2}\b', '', kw)

    # Remove common suffixes
    for suffix in [' books', ' kindle', ' kindle unlimited', ' book',
                   ' recommendations', ' to read', ' on amazon',
                   ' for adults', ' for beginners']:
        if kw.endswith(suffix):
            kw = kw[:-len(suffix)]

    kw = re.sub(r'\s+', ' ', kw).strip()

    # Skip if too short or just noise
    if len(kw) < 3:
        return ''

    return kw


def _is_captcha(html):
    """Check if the page is a CAPTCHA response."""
    captcha_markers = [
        'Enter the characters you see below',
        "Sorry, we just need to make sure you're not a robot",
        '/errors/validateCaptcha',
        'Type the characters you see in this image',
    ]
    html_lower = html.lower()
    return any(marker.lower() in html_lower for marker in captcha_markers)
