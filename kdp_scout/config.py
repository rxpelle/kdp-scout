"""Configuration management for KDP Scout.

Loads settings from .env file with sensible defaults for all options.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv


# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / '.env')


class Config:
    """Central configuration for KDP Scout."""

    # Database
    DB_PATH = os.getenv('DB_PATH', 'data/kdp_scout.db')

    # API Keys
    DATAFORSEO_API_KEY = os.getenv('DATAFORSEO_API_KEY', '')

    # Proxy
    PROXY_URL = os.getenv('PROXY_URL', '')

    # Rate limits (seconds between requests)
    AUTOCOMPLETE_RATE_LIMIT = float(os.getenv('AUTOCOMPLETE_RATE_LIMIT', '0.5'))
    PRODUCT_SCRAPE_RATE_LIMIT = float(os.getenv('PRODUCT_SCRAPE_RATE_LIMIT', '2.0'))
    DATAFORSEO_RATE_LIMIT = 1.0  # 1 request per second for API

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # User agents for rotation
    USER_AGENTS = [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    ]

    # Amazon autocomplete departments
    DEPARTMENTS = {
        'kindle': 'digital-text',
        'books': 'stripbooks',
        'all': 'aps',
    }

    @classmethod
    def get_db_path(cls):
        """Return absolute path to the database file."""
        db_path = Path(cls.DB_PATH)
        if not db_path.is_absolute():
            db_path = _project_root / db_path
        return str(db_path)

    @classmethod
    def setup_logging(cls):
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, cls.LOG_LEVEL.upper(), logging.INFO),
            format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    @classmethod
    def as_dict(cls):
        """Return configuration as a dictionary for display."""
        return {
            'DB_PATH': cls.get_db_path(),
            'DATAFORSEO_API_KEY': '***' if cls.DATAFORSEO_API_KEY else '(not set)',
            'PROXY_URL': cls.PROXY_URL or '(not set)',
            'AUTOCOMPLETE_RATE_LIMIT': f'{cls.AUTOCOMPLETE_RATE_LIMIT}s',
            'PRODUCT_SCRAPE_RATE_LIMIT': f'{cls.PRODUCT_SCRAPE_RATE_LIMIT}s',
            'LOG_LEVEL': cls.LOG_LEVEL,
            'USER_AGENTS': f'{len(cls.USER_AGENTS)} configured',
        }
