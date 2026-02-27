"""Keyword mining, scoring, and reverse ASIN engine.

Coordinates autocomplete mining, deduplication, database storage,
keyword scoring based on multiple signals, and reverse ASIN lookups
via search result probing or DataForSEO API.
"""

import logging
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
from kdp_scout.config import Config

logger = logging.getLogger(__name__)


def mine_keywords(seed, depth=1, department='kindle', progress_callback=None):
    """Mine keywords from autocomplete and store results.

    Orchestrates the full mining pipeline:
    1. Query Amazon autocomplete API with seed + expansions
    2. Deduplicate against existing keywords in database
    3. Store new keywords and metrics

    Args:
        seed: Seed keyword to mine (e.g., "historical fiction").
        depth: Mining depth (1 = seed + a-z, 2 = recursive expansion).
        department: Amazon department ('kindle', 'books', 'all').
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
        f'department={department}'
    )

    # Mine from autocomplete
    raw_results = mine_autocomplete(
        seed,
        department=department,
        depth=depth,
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

    Scoring combines autocomplete presence, competition level,
    BSR data, and real ads performance data into a composite score.
    """

    def __init__(self):
        """Initialize with database access."""
        init_db()
        self._repo = KeywordRepository()

    def close(self):
        """Close database connection."""
        self._repo.close()

    def score_keyword(self, keyword_id: int) -> float:
        """Compute composite score for a keyword combining all available signals.

        Score components:
        - Autocomplete presence: up to 100 points (pos 1 = 100, pos 10 = 10)
        - Low competition: up to 30 points
        - High demand (BSR): up to 25 points
        - Real ads impressions: up to 20 points
        - Real ads orders: up to 30 points

        Args:
            keyword_id: Database ID of the keyword.

        Returns:
            Composite score (0-205 theoretical max).
        """
        kw = self._repo.get_keyword_with_metrics(keyword_id)
        if kw is None:
            return 0.0

        score = 0.0

        # Autocomplete presence (searched frequently)
        autocomplete_position = kw['autocomplete_position']
        if autocomplete_position is not None and autocomplete_position > 0:
            score += max(0, 11 - autocomplete_position) * 10  # pos 1=100, pos 10=10

        # Low competition (easier to rank)
        competition_count = kw['competition_count']
        if competition_count is not None:
            if competition_count < 50000:
                score += 30
            elif competition_count < 200000:
                score += 15

        # Top results have good BSR (high demand)
        avg_bsr = kw['avg_bsr_top_results']
        if avg_bsr is not None:
            if avg_bsr < 100000:
                score += 25
            elif avg_bsr < 500000:
                score += 10

        # Real ads data (highest quality signal)
        impressions = kw['impressions']
        if impressions is not None and impressions > 100:
            score += 20
        elif impressions is not None and impressions > 0:
            score += 5

        orders = kw['orders']
        if orders is not None and orders > 0:
            score += 30
            # Bonus for multiple orders
            if orders >= 5:
                score += 10
            if orders >= 10:
                score += 10

        return score

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

    SEARCH_URL = 'https://www.amazon.com/s'

    def __init__(self):
        """Initialize with database access and rate limiter."""
        init_db()
        self._kw_repo = KeywordRepository()
        self._book_repo = BookRepository()
        self._ranking_repo = KeywordRankingRepository()

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
            response = fetch(
                self.SEARCH_URL,
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
