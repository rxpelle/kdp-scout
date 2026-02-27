"""Keyword mining orchestration engine.

Coordinates autocomplete mining, deduplication, and database storage.
Serves as the main entry point for the `mine` CLI command.
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
