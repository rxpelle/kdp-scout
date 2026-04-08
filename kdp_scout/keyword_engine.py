"""Keyword mining, scoring, and reverse ASIN engine.

Coordinates autocomplete mining, deduplication, database storage,
keyword scoring based on multiple signals, and reverse ASIN lookups
via search result probing or DataForSEO API.
"""

import logging
import math
import re
import signal
import time
from datetime import datetime, date

from bs4 import BeautifulSoup

from kdp_scout.db import (
    KeywordRepository, BookRepository, KeywordRankingRepository, init_db,
)
from kdp_scout.collectors.autocomplete import mine_autocomplete
from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config, get_marketplace

logger = logging.getLogger(__name__)

# ── Scoring weights and normalizers ──────────────────────────────────

DEFAULT_WEIGHTS = {
    'autocomplete': 0.20,
    'competition': 0.15,
    'bsr_demand': 0.10,
    'ads_impressions': 0.10,
    'ads_orders': 0.15,
    'ads_profitability': 0.10,
    'search_volume': 0.05,
    'commercial_value': 0.05,
    'click_through_rate': 0.05,
    'own_ranking': 0.05,
}


def normalize_autocomplete(position):
    """Normalize autocomplete position to 0-1.

    Position 1 = 1.0, position 10 = 0.1, position 11+ = 0.0.

    Args:
        position: 1-based autocomplete position, or None.

    Returns:
        Float in [0, 1].
    """
    if position is None or position <= 0:
        return 0.0
    return max(0.0, (11 - position) / 10)


def normalize_competition(count):
    """Normalize competition count to 0-1 (low competition = high score).

    Uses inverse formula: 1 / (1 + count / 50000).

    Args:
        count: Number of competing results, or None.

    Returns:
        Float in [0, 1].
    """
    if count is None or count < 0:
        return 0.0
    return 1.0 / (1.0 + count / 50000.0)


def normalize_bsr(bsr):
    """Normalize BSR to 0-1 using log scale.

    BSR 1 = 1.0, BSR 1M = 0.0.

    Args:
        bsr: Best Sellers Rank (average of top results), or None.

    Returns:
        Float in [0, 1].
    """
    if bsr is None or bsr <= 0:
        return 0.0
    return max(0.0, 1.0 - math.log10(bsr) / 6.0)


def normalize_impressions(impressions):
    """Normalize impressions to 0-1 using log scale.

    100K impressions = 1.0.

    Args:
        impressions: Number of ad impressions, or None.

    Returns:
        Float in [0, 1].
    """
    if impressions is None or impressions <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, impressions)) / 5.0)


def normalize_orders(orders):
    """Normalize orders to 0-1 using log scale.

    1000 orders = 1.0.

    Args:
        orders: Number of orders, or None.

    Returns:
        Float in [0, 1].
    """
    if orders is None or orders <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, orders)) / 3.0)


def normalize_ctr(clicks, impressions):
    """Normalize click-through rate to 0-1.

    5% CTR = 1.0. Computed as clicks / impressions.

    Args:
        clicks: Number of clicks, or None.
        impressions: Number of impressions, or None.

    Returns:
        Float in [0, 1].
    """
    if (clicks is None or impressions is None
            or clicks < 0 or impressions <= 0):
        return 0.0
    ctr = clicks / impressions
    return min(1.0, ctr / 0.05)


def normalize_acos(acos):
    """Normalize ACOS (profitability) to 0-1.

    0% ACOS = 1.0, 100% ACOS = 0.0. ACOS is expected as a decimal
    (e.g. 0.35 for 35%).

    Args:
        acos: Advertising cost of sales as decimal, or None.

    Returns:
        Float in [0, 1].
    """
    if acos is None:
        return 0.0
    # Convert from decimal to percentage for the formula
    acos_pct = acos * 100.0
    return max(0.0, 1.0 - acos_pct / 100.0)


def normalize_search_volume(volume):
    """Normalize search volume to 0-1 using log scale.

    100K volume = 1.0.

    Args:
        volume: Estimated search volume, or None.

    Returns:
        Float in [0, 1].
    """
    if volume is None or volume <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, volume)) / 5.0)


def normalize_suggested_bid(bid):
    """Normalize suggested bid to 0-1.

    $3+ bid = 1.0 (higher bid = more commercial value).

    Args:
        bid: Suggested CPC bid in dollars, or None.

    Returns:
        Float in [0, 1].
    """
    if bid is None or bid <= 0:
        return 0.0
    return min(1.0, bid / 3.0)


def normalize_own_ranking(rank):
    """Normalize own book ranking to 0-1.

    Rank 1 = 1.0, rank 50 = ~0.0. If no rank, returns 0.

    Args:
        rank: 1-based rank position, or None.

    Returns:
        Float in [0, 1].
    """
    if rank is None or rank <= 0:
        return 0.0
    return max(0.0, (50.0 - rank) / 49.0)


def mine_keywords(seed, depth=1, department='kindle', marketplace=None,
                  progress_callback=None):
    """Mine keywords from autocomplete and store results.

    Orchestrates the full mining pipeline:
    1. Query Amazon autocomplete API with seed + expansions
    2. Deduplicate against existing keywords in database
    3. Store new keywords and metrics

    Args:
        seed: Seed keyword to mine (e.g., "historical fiction").
        depth: Mining depth (1 = seed + a-z, 2 = recursive expansion).
        department: Amazon department ('kindle', 'books', 'all').
        marketplace: Two-letter country code ('us', 'de', etc.).
        progress_callback: Optional callable(completed, total) for progress.

    Returns:
        Dict with mining results:
            - new_count: Number of new keywords discovered
            - existing_count: Number of keywords already in database
            - total_mined: Total unique keywords from autocomplete
            - keywords: List of (keyword, position, is_new) tuples
    """
    # Ensure database exists
    init_db()

    logger.info(
        f'Starting keyword mining: seed="{seed}", depth={depth}, '
        f'department={department}, marketplace={marketplace or Config.MARKETPLACE}'
    )

    # Mine from autocomplete
    raw_results = mine_autocomplete(
        seed,
        department=department,
        depth=depth,
        marketplace=marketplace,
        progress_callback=progress_callback,
    )

    # Store results and track new vs existing
    repo = KeywordRepository()
    try:
        new_count = 0
        existing_count = 0
        keywords = []

        for keyword, position in raw_results:
            keyword_id, is_new = repo.upsert_keyword(
                keyword,
                source='autocomplete',
                category=seed,
            )

            # Store autocomplete position metric
            repo.add_metric(keyword_id, autocomplete_position=position)

            if is_new:
                new_count += 1
            else:
                existing_count += 1

            keywords.append((keyword, position, is_new))

        logger.info(
            f'Mining complete: {new_count} new, {existing_count} existing, '
            f'{len(keywords)} total'
        )

        return {
            'new_count': new_count,
            'existing_count': existing_count,
            'total_mined': len(keywords),
            'keywords': keywords,
            'seed': seed,
            'depth': depth,
            'department': department,
        }

    finally:
        repo.close()


class KeywordScorer:
    """Scores keywords based on multiple signals.

    Uses weighted normalized scoring across 10 signal dimensions.
    Each signal is normalized to 0-1, multiplied by its weight,
    and the final score is scaled to 0-100.
    """

    def __init__(self, weights=None):
        """Initialize with database access.

        Args:
            weights: Optional dict overriding DEFAULT_WEIGHTS.
        """
        init_db()
        self._repo = KeywordRepository()
        self._weights = weights or DEFAULT_WEIGHTS

    def close(self):
        """Close database connection."""
        self._repo.close()

    def score_keyword(self, keyword_id: int) -> float:
        """Compute composite score for a keyword combining all available signals.

        Returns a score on a 0-100 scale using weighted normalized signals.

        Args:
            keyword_id: Database ID of the keyword.

        Returns:
            Composite score (0-100).
        """
        return self.score_keyword_detailed(keyword_id)['total']

    def score_keyword_detailed(self, keyword_id: int) -> dict:
        """Compute detailed score breakdown for a keyword.

        Returns a dict with total score and per-component breakdown
        showing raw values, normalized scores, weights, and weighted
        contributions.

        Args:
            keyword_id: Database ID of the keyword.

        Returns:
            Dict with 'total' (float 0-100) and 'components' (dict of
            component breakdowns).
        """
        kw = self._repo.get_keyword_with_metrics(keyword_id)
        if kw is None:
            return self._empty_result()

        # Gather raw values from metrics
        autocomplete_pos = kw['autocomplete_position']
        competition_count = kw['competition_count']
        avg_bsr = kw['avg_bsr_top_results']
        impressions = kw['impressions']
        clicks = kw['clicks']
        orders = kw['orders']
        estimated_volume = kw['estimated_volume']
        suggested_bid = kw['suggested_bid']

        # Fall back to ads_search_terms if keyword_metrics lacks ads data
        if not impressions and not clicks and not orders:
            ads_data = self._repo.get_ads_data_for_keyword(kw['keyword'])
            if ads_data:
                impressions = ads_data['impressions']
                clicks = ads_data['clicks']
                orders = ads_data['orders']

        # Cross-reference: ACOS from ads_search_terms
        acos = self._repo.get_ads_acos_for_keyword(kw['keyword'])

        # Cross-reference: own book ranking
        own_rank = self._repo.get_own_ranking_for_keyword(keyword_id)

        # Normalize each signal
        components = {}

        # Autocomplete
        norm = normalize_autocomplete(autocomplete_pos)
        components['autocomplete'] = {
            'score': norm,
            'weight': self._weights['autocomplete'],
            'weighted': norm * self._weights['autocomplete'] * 100,
            'raw': autocomplete_pos,
            'description': (f'Position {autocomplete_pos}'
                           if autocomplete_pos else 'Not in autocomplete'),
        }

        # Competition
        norm = normalize_competition(competition_count)
        components['competition'] = {
            'score': norm,
            'weight': self._weights['competition'],
            'weighted': norm * self._weights['competition'] * 100,
            'raw': competition_count,
            'description': (f'{competition_count:,} results'
                           if competition_count is not None else 'No data'),
        }

        # BSR demand
        norm = normalize_bsr(avg_bsr)
        components['bsr_demand'] = {
            'score': norm,
            'weight': self._weights['bsr_demand'],
            'weighted': norm * self._weights['bsr_demand'] * 100,
            'raw': avg_bsr,
            'description': (f'Avg BSR {avg_bsr:,.0f}'
                           if avg_bsr is not None else 'No data'),
        }

        # Ads impressions
        norm = normalize_impressions(impressions)
        components['ads_impressions'] = {
            'score': norm,
            'weight': self._weights['ads_impressions'],
            'weighted': norm * self._weights['ads_impressions'] * 100,
            'raw': impressions,
            'description': (f'{impressions:,} impressions'
                           if impressions is not None else 'No data'),
        }

        # Ads orders
        norm = normalize_orders(orders)
        components['ads_orders'] = {
            'score': norm,
            'weight': self._weights['ads_orders'],
            'weighted': norm * self._weights['ads_orders'] * 100,
            'raw': orders,
            'description': (f'{orders:,} orders'
                           if orders is not None else 'No data'),
        }

        # Ads profitability (ACOS)
        norm = normalize_acos(acos)
        components['ads_profitability'] = {
            'score': norm,
            'weight': self._weights['ads_profitability'],
            'weighted': norm * self._weights['ads_profitability'] * 100,
            'raw': acos,
            'description': (f'{acos * 100:.1f}% ACOS'
                           if acos is not None else 'No data'),
        }

        # Search volume
        norm = normalize_search_volume(estimated_volume)
        components['search_volume'] = {
            'score': norm,
            'weight': self._weights['search_volume'],
            'weighted': norm * self._weights['search_volume'] * 100,
            'raw': estimated_volume,
            'description': (f'{estimated_volume:,} est. volume'
                           if estimated_volume is not None else 'No data'),
        }

        # Commercial value (suggested bid)
        norm = normalize_suggested_bid(suggested_bid)
        components['commercial_value'] = {
            'score': norm,
            'weight': self._weights['commercial_value'],
            'weighted': norm * self._weights['commercial_value'] * 100,
            'raw': suggested_bid,
            'description': (f'${suggested_bid:.2f} suggested bid'
                           if suggested_bid is not None else 'No data'),
        }

        # Click-through rate
        norm = normalize_ctr(clicks, impressions)
        components['click_through_rate'] = {
            'score': norm,
            'weight': self._weights['click_through_rate'],
            'weighted': norm * self._weights['click_through_rate'] * 100,
            'raw': (clicks / impressions if clicks and impressions
                    and impressions > 0 else None),
            'description': (f'{clicks / impressions * 100:.2f}% CTR'
                           if clicks and impressions and impressions > 0
                           else 'No data'),
        }

        # Own ranking
        norm = normalize_own_ranking(own_rank)
        components['own_ranking'] = {
            'score': norm,
            'weight': self._weights['own_ranking'],
            'weighted': norm * self._weights['own_ranking'] * 100,
            'raw': own_rank,
            'description': (f'Rank #{own_rank}'
                           if own_rank is not None else 'Not ranked'),
        }

        # Total = sum of weighted components
        total = sum(c['weighted'] for c in components.values())

        return {
            'total': round(total, 1),
            'components': components,
        }

    def _empty_result(self):
        """Return an empty score result for missing keywords."""
        components = {}
        for name, weight in self._weights.items():
            components[name] = {
                'score': 0.0,
                'weight': weight,
                'weighted': 0.0,
                'raw': None,
                'description': 'No data',
            }
        return {'total': 0.0, 'components': components}

    def score_all_keywords(self, recalculate=False) -> int:
        """Score active keywords in the database.

        Args:
            recalculate: If True, rescore all keywords. If False (default),
                only score keywords that don't have a score yet.

        Returns:
            Count of keywords scored.
        """
        if recalculate:
            keyword_ids = self._repo.get_all_keyword_ids(active_only=True)
        else:
            keyword_ids = self._repo.get_unscored_keyword_ids()

        count = 0

        for keyword_id in keyword_ids:
            score = self.score_keyword(keyword_id)
            self._repo.update_score(keyword_id, score)
            count += 1

        logger.info(f'Scored {count} keywords (recalculate={recalculate})')
        return count

    def get_top_keywords(self, limit=50, min_score=0) -> list:
        """Get keywords ranked by score.

        Args:
            limit: Maximum number of keywords to return.
            min_score: Minimum score threshold.

        Returns:
            List of sqlite3.Row objects with keyword data and metrics.
        """
        return self._repo.get_keywords_with_latest_metrics(
            limit=limit,
            min_score=min_score,
            order_by='score',
        )


class ReverseASIN:
    """Reverse ASIN lookup via search probing or DataForSEO API.

    Finds which keywords a given ASIN ranks for in Amazon search results.
    The free probe method searches Amazon for each known keyword and checks
    if the target ASIN appears in the results. DataForSEO provides the same
    data via paid API if credentials are configured.
    """

    # Sponsored result markers in Amazon search HTML
    SPONSORED_MARKERS = [
        'AdHolder',
        'sp-sponsored-result',
        'puis-sponsored-label',
        's-sponsored-label',
        'a-spacing-micro s-sponsored-label',
    ]

    SEARCH_URL_TEMPLATE = 'https://{domain}/s'

    def __init__(self, marketplace=None):
        """Initialize with database access and rate limiter."""
        init_db()
        self._kw_repo = KeywordRepository()
        self._book_repo = BookRepository()
        self._ranking_repo = KeywordRankingRepository()
        self._mp = get_marketplace(marketplace)

        # Initialize rate limiter for search probing
        rate_registry.get_limiter(
            'search_probe', rate=Config.SEARCH_PROBE_RATE_LIMIT
        )

        # Interrupt flag for graceful Ctrl+C handling
        self._interrupted = False

    def close(self):
        """Close database connections."""
        self._kw_repo.close()
        self._book_repo.close()
        self._ranking_repo.close()

    def reverse_asin_probe(self, asin, top_n=None, method='auto',
                           progress_callback=None):
        """Find keywords that a given ASIN ranks for.

        Method 'probe': For each keyword in the database, search Amazon
        and check if the target ASIN appears in the results.

        Method 'dataforseo': Use DataForSEO API (if configured).

        Method 'auto': Use DataForSEO if available, otherwise probe.

        Args:
            asin: The Amazon ASIN to reverse lookup.
            top_n: Only check top N keywords (by score, or all if None).
            method: 'probe', 'dataforseo', or 'auto'.
            progress_callback: Optional callable(completed, total, found, keyword).

        Returns:
            List of dicts: [{'keyword': str, 'position': int,
                            'snapshot_date': str, 'source': str}]
        """
        asin = asin.upper().strip()

        # Ensure the book is in our database
        book = self._book_repo.find_by_asin(asin)
        if not book:
            # Add as a tracked book (not own)
            book_id, _ = self._book_repo.upsert_book(asin=asin)
        else:
            book_id = book['id']

        # Determine method
        if method == 'auto':
            from kdp_scout.collectors.dataforseo import DataForSEOCollector
            dfs = DataForSEOCollector()
            if dfs.is_available():
                method = 'dataforseo'
            else:
                method = 'probe'

        if method == 'dataforseo':
            return self._reverse_via_dataforseo(asin, book_id)
        else:
            return self._reverse_via_probe(
                asin, book_id, top_n=top_n,
                progress_callback=progress_callback,
            )

    def _reverse_via_dataforseo(self, asin, book_id):
        """Reverse ASIN using DataForSEO API.

        Args:
            asin: The ASIN to look up.
            book_id: Database ID of the book.

        Returns:
            List of ranking result dicts.
        """
        from kdp_scout.collectors.dataforseo import DataForSEOCollector

        dfs = DataForSEOCollector()
        raw_results = dfs.reverse_asin(asin)

        today = date.today().isoformat()
        results = []

        for item in raw_results:
            keyword = item['keyword']
            position = item['position']

            # Ensure keyword is in our database
            keyword_id, _ = self._kw_repo.upsert_keyword(
                keyword, source='dataforseo'
            )

            # Store the ranking
            self._ranking_repo.add_ranking(
                keyword_id=keyword_id,
                book_id=book_id,
                position=position,
                source='dataforseo',
                snapshot_date=today,
            )

            results.append({
                'keyword': keyword,
                'position': position,
                'snapshot_date': today,
                'source': 'dataforseo',
                'search_volume': item.get('search_volume', 0),
            })

        logger.info(
            f'DataForSEO reverse ASIN for {asin}: '
            f'{len(results)} rankings found '
            f'(spend: ${dfs.get_estimated_spend():.4f})'
        )
        return results

    def _reverse_via_probe(self, asin, book_id, top_n=None,
                           progress_callback=None):
        """Reverse ASIN via Amazon search probing.

        Searches Amazon for each known keyword and checks if the target
        ASIN appears in the search results page.

        Args:
            asin: The ASIN to look up.
            book_id: Database ID of the book.
            top_n: Only check top N keywords (by score).
            progress_callback: Optional callable(completed, total, found, keyword).

        Returns:
            List of ranking result dicts.
        """
        # Get keywords to probe
        if top_n:
            keywords = self._kw_repo.get_keywords_with_latest_metrics(
                limit=top_n, min_score=0, order_by='score',
            )
        else:
            keywords = self._kw_repo.get_all_keywords(active_only=True)

        if not keywords:
            logger.warning('No keywords in database to probe.')
            return []

        total = len(keywords)
        today = date.today().isoformat()
        results = []
        completed = 0
        self._interrupted = False

        # Set up graceful interrupt handler
        original_handler = signal.getsignal(signal.SIGINT)

        def interrupt_handler(signum, frame):
            self._interrupted = True
            logger.info('Interrupt received, saving partial results...')

        signal.signal(signal.SIGINT, interrupt_handler)

        try:
            for kw_row in keywords:
                if self._interrupted:
                    logger.info(
                        f'Interrupted after {completed}/{total} keywords. '
                        f'Partial results saved.'
                    )
                    break

                keyword = kw_row['keyword']
                keyword_id = kw_row['id']

                # Probe Amazon search
                position = self._probe_search(keyword, asin)

                if position is not None:
                    # Found! Store the ranking
                    self._ranking_repo.add_ranking(
                        keyword_id=keyword_id,
                        book_id=book_id,
                        position=position,
                        source='probe',
                        snapshot_date=today,
                    )
                    results.append({
                        'keyword': keyword,
                        'position': position,
                        'snapshot_date': today,
                        'source': 'probe',
                    })

                completed += 1
                if progress_callback:
                    progress_callback(completed, total, len(results), keyword)

        finally:
            # Restore original signal handler
            signal.signal(signal.SIGINT, original_handler)

        logger.info(
            f'Search probe reverse ASIN for {asin}: '
            f'{len(results)} rankings found out of {completed} keywords checked'
        )
        return results

    def _probe_search(self, keyword, target_asin):
        """Search Amazon for a keyword and check if the target ASIN appears.

        Args:
            keyword: The search term to query.
            target_asin: The ASIN to look for in results.

        Returns:
            1-based position if found, None if not found.
        """
        # Respect rate limiting
        rate_registry.acquire('search_probe')

        params = {
            'k': keyword,
            'i': 'digital-text',  # Kindle store
        }

        try:
            url = self.SEARCH_URL_TEMPLATE.format(domain=self._mp['domain'])
            response = fetch(
                url,
                params=params,
                headers=get_browser_headers(),
            )

            if response.status_code != 200:
                logger.debug(
                    f'Search returned {response.status_code} for "{keyword}"'
                )
                return None

            html = response.text

            # Check for CAPTCHA
            if self._is_captcha(html):
                logger.warning(
                    f'CAPTCHA detected during search probe for "{keyword}". '
                    'Backing off 30 seconds...'
                )
                time.sleep(30)
                return None

            return self._find_asin_in_results(html, target_asin)

        except Exception as e:
            logger.error(f'Error probing search for "{keyword}": {e}')
            return None

    def _is_captcha(self, html):
        """Check if the page is a CAPTCHA response.

        Args:
            html: Raw HTML string.

        Returns:
            True if CAPTCHA markers are found.
        """
        captcha_markers = [
            'Enter the characters you see below',
            'Sorry, we just need to make sure you\'re not a robot',
            '/errors/validateCaptcha',
            'Type the characters you see in this image',
        ]
        html_lower = html.lower()
        return any(marker.lower() in html_lower for marker in captcha_markers)

    def _find_asin_in_results(self, html, target_asin):
        """Parse Amazon search results HTML and find the target ASIN position.

        Filters out sponsored results. Returns the 1-based organic position.

        Args:
            html: Raw HTML of Amazon search results page.
            target_asin: The ASIN to look for.

        Returns:
            1-based position if found, None if not found.
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Find all result divs with data-asin attributes
        result_divs = soup.find_all(
            'div', attrs={'data-asin': True}
        )

        organic_position = 0

        for div in result_divs:
            asin = div.get('data-asin', '').strip().upper()
            if not asin:
                continue

            # Check if this is a sponsored result
            if self._is_sponsored(div):
                continue

            organic_position += 1

            if asin == target_asin:
                return organic_position

        return None

    def _is_sponsored(self, div):
        """Check if a search result div is a sponsored/ad result.

        Uses multiple heuristics since Amazon changes these frequently.

        Args:
            div: BeautifulSoup Tag for a search result div.

        Returns:
            True if the result appears to be sponsored.
        """
        # Check for known sponsored class names
        div_classes = ' '.join(div.get('class', []))
        div_html = str(div)

        for marker in self.SPONSORED_MARKERS:
            if marker in div_classes or marker in div_html:
                return True

        # Check for "Sponsored" text in small labels
        sponsored_labels = div.find_all(
            string=re.compile(r'\bSponsored\b', re.IGNORECASE)
        )
        if sponsored_labels:
            return True

        return False
