"""Keyword mining and scoring engine.

Coordinates autocomplete mining, deduplication, database storage,
and keyword scoring based on multiple signals.
"""

import logging
from datetime import datetime

from kdp_scout.db import KeywordRepository, init_db
from kdp_scout.collectors.autocomplete import mine_autocomplete

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

    def score_all_keywords(self) -> int:
        """Score all active keywords in the database.

        Returns:
            Count of keywords scored.
        """
        keyword_ids = self._repo.get_all_keyword_ids(active_only=True)
        count = 0

        for keyword_id in keyword_ids:
            score = self.score_keyword(keyword_id)
            self._repo.update_score(keyword_id, score)
            count += 1

        logger.info(f'Scored {count} keywords')
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
