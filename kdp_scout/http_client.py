"""Shared HTTP client with retry logic, user-agent rotation, and proxy support.

Provides a configured requests.Session with exponential backoff on
429 (Too Many Requests) and 503 (Service Unavailable) responses.
"""

import random
import logging
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests

from kdp_scout.config import Config

logger = logging.getLogger(__name__)


def create_session(proxy_url=None):
    """Create a configured requests.Session with retry logic.

    Args:
        proxy_url: Optional proxy URL to route requests through.

    Returns:
        Configured requests.Session instance.
    """
    session = requests.Session()

    # Configure retry strategy with exponential backoff
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # 1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET', 'POST'],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    # Set proxy if configured
    if proxy_url or Config.PROXY_URL:
        url = proxy_url or Config.PROXY_URL
        session.proxies = {
            'http': url,
            'https': url,
        }
        logger.info(f'HTTP client using proxy: {url[:30]}...')

    # Set a default timeout
    session.timeout = 15

    return session


def get_random_user_agent():
    """Return a random user agent string from the configured list."""
    return random.choice(Config.USER_AGENTS)


def get_headers():
    """Return request headers with a rotated user agent."""
    return {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json, text/html, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
    }


# Shared session instance (lazy initialization)
_session = None


def get_session():
    """Get the shared HTTP session, creating it if needed."""
    global _session
    if _session is None:
        _session = create_session()
    return _session


def fetch(url, params=None, headers=None):
    """Make a GET request with retry logic and user-agent rotation.

    Args:
        url: URL to fetch.
        params: Optional query parameters.
        headers: Optional headers (merged with defaults).

    Returns:
        requests.Response object.

    Raises:
        requests.RequestException: On request failure after retries.
    """
    session = get_session()
    request_headers = get_headers()
    if headers:
        request_headers.update(headers)

    logger.debug(f'GET {url} params={params}')

    response = session.get(url, params=params, headers=request_headers, timeout=15)

    logger.debug(f'Response: {response.status_code} ({len(response.content)} bytes)')

    if response.status_code == 429:
        logger.warning(f'Rate limited (429) on {url}')
    elif response.status_code >= 400:
        logger.warning(f'HTTP {response.status_code} on {url}')

    return response
