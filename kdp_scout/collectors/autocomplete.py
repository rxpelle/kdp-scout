"""Amazon autocomplete API keyword miner.

Mines keywords from Amazon's autocomplete/suggestions endpoint by
querying a seed keyword and optionally expanding with a-z suffix variations.

The autocomplete API returns the top suggestions Amazon shows in its
search bar as users type, which directly reflects actual search behavior.
"""

import json
import logging
import string

import requests

from kdp_scout.http_client import fetch
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

AUTOCOMPLETE_URL = 'https://completion.amazon.com/api/2017/suggestions'

# Department alias mapping
DEPARTMENT_ALIASES = {
    'kindle': 'digital-text',
    'books': 'stripbooks',
    'all': 'aps',
}


def mine_autocomplete(seed, department='kindle', depth=1, progress_callback=None):
    """Mine keywords from Amazon's autocomplete API.

    Queries the seed keyword directly, then expands with a-z suffix
    variations. At depth 2, each result is further expanded with a-z.

    Args:
        seed: The seed keyword to mine (e.g., "historical fiction").
        department: Amazon department ('kindle', 'books', or 'all').
        depth: Mining depth. 1 = seed + a-z (27 queries).
               2 = depth 1 + expand each result with a-z.
        progress_callback: Optional callable(completed, total) for progress updates.

    Returns:
        List of (keyword, position) tuples, deduplicated and sorted.
    """
    # Initialize rate limiter if not already done
    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)

    alias = DEPARTMENT_ALIASES.get(department, department)
    all_results = {}  # keyword -> best position

    # Phase 1: Query seed keyword directly + a-z expansions
    prefixes = [seed] + [f'{seed} {c}' for c in string.ascii_lowercase]
    total_queries = len(prefixes)

    if depth >= 2:
        # Estimate total: we don't know yet how many results we'll get,
        # but we can update as we go
        pass

    completed = 0

    for prefix in prefixes:
        suggestions = _query_autocomplete(prefix, alias)
        for kw, pos in suggestions:
            if kw not in all_results or pos < all_results[kw]:
                all_results[kw] = pos

        completed += 1
        if progress_callback:
            progress_callback(completed, total_queries)

    # Phase 2: Depth 2 expansion
    if depth >= 2:
        depth1_keywords = list(all_results.keys())
        expansion_prefixes = []
        for kw in depth1_keywords:
            for c in string.ascii_lowercase:
                expansion_prefixes.append(f'{kw} {c}')

        total_queries = completed + len(expansion_prefixes)

        for prefix in expansion_prefixes:
            suggestions = _query_autocomplete(prefix, alias)
            for kw, pos in suggestions:
                if kw not in all_results or pos < all_results[kw]:
                    all_results[kw] = pos

            completed += 1
            if progress_callback:
                progress_callback(completed, total_queries)

    # Sort by position, then alphabetically
    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))

    logger.info(
        f'Autocomplete mining for "{seed}" (depth={depth}, dept={department}): '
        f'{len(results)} keywords found'
    )

    return results


def _query_autocomplete(prefix, alias):
    """Query the Amazon autocomplete API for a single prefix.

    Args:
        prefix: Search prefix string.
        alias: Amazon department alias.

    Returns:
        List of (keyword, position) tuples.
    """
    # Respect rate limiting
    rate_registry.acquire('autocomplete')

    params = {
        'mid': 'ATVPDKIKX0DER',
        'alias': alias,
        'prefix': prefix,
    }

    try:
        response = fetch(AUTOCOMPLETE_URL, params=params)
    except (requests.Timeout, requests.ConnectionError) as e:
        logger.error(f'Network error querying autocomplete for "{prefix}": {e}')
        return []
    except requests.RequestException as e:
        logger.error(f'Request error querying autocomplete for "{prefix}": {e}')
        return []

    try:
        if response.status_code != 200:
            logger.warning(
                f'Autocomplete returned {response.status_code} for "{prefix}"'
            )
            return []

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f'Invalid JSON from autocomplete for "{prefix}": {e}')
            return []

        suggestions = data.get('suggestions', [])

        results = []
        for i, suggestion in enumerate(suggestions):
            keyword = suggestion.get('value', '').strip().lower()
            if keyword:
                results.append((keyword, i + 1))

        logger.debug(f'"{prefix}" -> {len(results)} suggestions')
        return results

    except Exception as e:
        logger.error(f'Error processing autocomplete for "{prefix}": {e}')
        return []
