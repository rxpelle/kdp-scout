"""DataForSEO API integration for reverse ASIN and keyword research.

Provides access to DataForSEO's Amazon-specific endpoints:
- Ranked keywords (reverse ASIN)
- Bulk search volume
- Related keywords
- Product competitors

Uses HTTP Basic Auth with login (email) and API key (password).
All methods gracefully return empty results when API credentials
are not configured, with an info-level log message.
"""

import base64
import json
import logging
from datetime import date

from kdp_scout.config import Config
from kdp_scout.rate_limiter import registry as rate_registry

logger = logging.getLogger(__name__)


class DataForSEOCollector:
    """DataForSEO API wrapper for Amazon keyword research endpoints.

    Tracks estimated API spend per session. All methods return empty
    results with a logged info message when API credentials are not set.
    """

    # Approximate costs per DataForSEO documentation
    COST_PER_TASK = 0.01
    COST_PER_KEYWORD = 0.0001

    def __init__(self, config=None):
        """Initialize with configuration.

        Args:
            config: Config class (defaults to global Config).
        """
        self._config = config or Config
        self._login = self._config.DATAFORSEO_LOGIN
        self._api_key = self._config.DATAFORSEO_API_KEY
        self.base_url = 'https://api.dataforseo.com/v3'
        self.spend_tracker = 0.0

        # Set up rate limiter
        rate_registry.get_limiter(
            'dataforseo', rate=self._config.DATAFORSEO_RATE_LIMIT
        )

    def is_available(self):
        """Check if API credentials are configured.

        Returns:
            True if both login and API key are set.
        """
        return bool(self._login and self._api_key)

    def _get_auth_header(self):
        """Build HTTP Basic Auth header value.

        Returns:
            Dict with Authorization header.
        """
        credentials = f'{self._login}:{self._api_key}'
        encoded = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {encoded}'}

    def _post(self, endpoint, payload):
        """Make an authenticated POST request to DataForSEO API.

        Args:
            endpoint: API endpoint path (e.g., '/dataforseo_labs/amazon/ranked_keywords/live').
            payload: List of task dicts to send as JSON body.

        Returns:
            Parsed JSON response dict, or None on error.
        """
        import requests

        if not self.is_available():
            logger.info(
                'DataForSEO API not configured. '
                'Set DATAFORSEO_LOGIN and DATAFORSEO_API_KEY in .env.'
            )
            return None

        # Respect rate limiting
        rate_registry.acquire('dataforseo')

        url = f'{self.base_url}{endpoint}'
        headers = {
            **self._get_auth_header(),
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=30
            )

            if response.status_code == 401:
                logger.error('DataForSEO authentication failed (401). Check credentials.')
                return None

            if response.status_code != 200:
                logger.error(
                    f'DataForSEO API returned {response.status_code}: '
                    f'{response.text[:200]}'
                )
                return None

            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f'Invalid JSON from DataForSEO: {e}')
                return None

            # Check for API-level errors
            status_code = data.get('status_code')
            if status_code and status_code != 20000:
                logger.error(
                    f'DataForSEO error {status_code}: '
                    f'{data.get("status_message", "Unknown error")}'
                )
                return None

            return data

        except requests.RequestException as e:
            logger.error(f'DataForSEO request failed: {e}')
            return None

    def reverse_asin(self, asin, location_code=2840):
        """Get ranked keywords for an ASIN via DataForSEO.

        Uses the Amazon Ranked Keywords endpoint to find what keywords
        a product ranks for in Amazon search results.

        Args:
            asin: The Amazon ASIN to look up.
            location_code: Geographic location code (2840 = US).

        Returns:
            List of dicts: [{'keyword': str, 'position': int, 'search_volume': int}]
            Returns empty list if API is unavailable or on error.
        """
        if not self.is_available():
            logger.info('DataForSEO not available for reverse ASIN lookup.')
            return []

        payload = [{
            'asin': asin.upper().strip(),
            'language_code': 'en',
            'location_code': location_code,
        }]

        data = self._post(
            '/dataforseo_labs/amazon/ranked_keywords/live', payload
        )

        if data is None:
            return []

        results = []
        try:
            tasks = data.get('tasks', [])
            for task in tasks:
                task_result = task.get('result', [])
                for result_item in task_result:
                    items = result_item.get('items', [])
                    # Track spend
                    item_count = len(items)
                    self.spend_tracker += (
                        self.COST_PER_TASK + item_count * self.COST_PER_KEYWORD
                    )

                    for item in items:
                        keyword_data = item.get('keyword_data', {})
                        ranked_serp = item.get('ranked_serp_element', {})

                        keyword = keyword_data.get('keyword', '')
                        position = ranked_serp.get('serp_item', {}).get(
                            'rank_absolute', 0
                        )
                        search_volume = keyword_data.get('search_volume', 0)

                        if keyword:
                            results.append({
                                'keyword': keyword.lower().strip(),
                                'position': position,
                                'search_volume': search_volume or 0,
                            })

        except (KeyError, TypeError, IndexError) as e:
            logger.error(f'Error parsing DataForSEO reverse ASIN response: {e}')

        logger.info(
            f'DataForSEO reverse ASIN for {asin}: {len(results)} keywords found '
            f'(estimated cost: ${self.spend_tracker:.4f})'
        )
        return results

    def bulk_search_volume(self, keywords, location_code=2840):
        """Get search volume estimates for a list of keywords.

        Args:
            keywords: List of keyword strings (max 1000 per request).
            location_code: Geographic location code (2840 = US).

        Returns:
            Dict mapping keyword -> volume (int).
            Returns empty dict if API is unavailable.
        """
        if not self.is_available():
            logger.info('DataForSEO not available for search volume lookup.')
            return {}

        if not keywords:
            return {}

        # DataForSEO has a limit per request; batch if needed
        batch_size = 1000
        all_volumes = {}

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i:i + batch_size]

            payload = [{
                'keywords': batch,
                'language_code': 'en',
                'location_code': location_code,
            }]

            data = self._post(
                '/dataforseo_labs/amazon/bulk_search_volume/live', payload
            )

            if data is None:
                continue

            try:
                tasks = data.get('tasks', [])
                for task in tasks:
                    task_result = task.get('result', [])
                    for result_item in task_result:
                        items = result_item.get('items', [])
                        self.spend_tracker += (
                            self.COST_PER_TASK + len(items) * self.COST_PER_KEYWORD
                        )

                        for item in items:
                            kw = item.get('keyword', '').lower().strip()
                            vol = item.get('search_volume', 0)
                            if kw:
                                all_volumes[kw] = vol or 0

            except (KeyError, TypeError, IndexError) as e:
                logger.error(f'Error parsing DataForSEO search volume response: {e}')

        logger.info(
            f'DataForSEO search volume: {len(all_volumes)} keywords '
            f'(estimated cost: ${self.spend_tracker:.4f})'
        )
        return all_volumes

    def related_keywords(self, keyword, location_code=2840):
        """Get semantically related keywords.

        Args:
            keyword: Seed keyword string.
            location_code: Geographic location code (2840 = US).

        Returns:
            List of related keyword strings.
            Returns empty list if API is unavailable.
        """
        if not self.is_available():
            logger.info('DataForSEO not available for related keywords.')
            return []

        payload = [{
            'keyword': keyword,
            'language_code': 'en',
            'location_code': location_code,
        }]

        data = self._post(
            '/dataforseo_labs/amazon/related_keywords/live', payload
        )

        if data is None:
            return []

        results = []
        try:
            tasks = data.get('tasks', [])
            for task in tasks:
                task_result = task.get('result', [])
                for result_item in task_result:
                    items = result_item.get('items', [])
                    self.spend_tracker += (
                        self.COST_PER_TASK + len(items) * self.COST_PER_KEYWORD
                    )

                    for item in items:
                        keyword_data = item.get('keyword_data', {})
                        kw = keyword_data.get('keyword', '').lower().strip()
                        if kw:
                            results.append(kw)

        except (KeyError, TypeError, IndexError) as e:
            logger.error(f'Error parsing DataForSEO related keywords response: {e}')

        logger.info(
            f'DataForSEO related keywords for "{keyword}": {len(results)} found'
        )
        return results

    def product_competitors(self, asin, location_code=2840):
        """Get competing products for an ASIN.

        Args:
            asin: The Amazon ASIN to find competitors for.
            location_code: Geographic location code (2840 = US).

        Returns:
            List of dicts: [{'asin': str, 'title': str, 'common_keywords': int}]
            Returns empty list if API is unavailable.
        """
        if not self.is_available():
            logger.info('DataForSEO not available for product competitors.')
            return []

        payload = [{
            'asin': asin.upper().strip(),
            'language_code': 'en',
            'location_code': location_code,
        }]

        data = self._post(
            '/dataforseo_labs/amazon/product_competitors/live', payload
        )

        if data is None:
            return []

        results = []
        try:
            tasks = data.get('tasks', [])
            for task in tasks:
                task_result = task.get('result', [])
                for result_item in task_result:
                    items = result_item.get('items', [])
                    self.spend_tracker += (
                        self.COST_PER_TASK + len(items) * self.COST_PER_KEYWORD
                    )

                    for item in items:
                        comp_asin = item.get('asin', '')
                        title = item.get('title', '')
                        common = item.get('avg_position', 0)
                        intersections = item.get('intersections', 0)

                        if comp_asin:
                            results.append({
                                'asin': comp_asin.upper().strip(),
                                'title': title,
                                'common_keywords': intersections or 0,
                            })

        except (KeyError, TypeError, IndexError) as e:
            logger.error(f'Error parsing DataForSEO product competitors response: {e}')

        logger.info(
            f'DataForSEO competitors for {asin}: {len(results)} found'
        )
        return results

    def get_estimated_spend(self):
        """Return estimated API spend this session.

        Returns:
            Float dollar amount.
        """
        return self.spend_tracker
