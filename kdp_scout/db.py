"""SQLite database management for KDP Scout.

Handles schema creation, migrations, and provides repository classes
for each entity type.
"""

import os
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path

from kdp_scout.config import Config

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    category TEXT,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS keyword_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    snapshot_date TEXT NOT NULL,
    estimated_volume INTEGER,
    volume_source TEXT,
    competition_count INTEGER,
    autocomplete_position INTEGER,
    avg_bsr_top_results REAL,
    suggested_bid REAL,
    impressions INTEGER,
    clicks INTEGER,
    orders INTEGER,
    UNIQUE(keyword_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL UNIQUE,
    title TEXT,
    author TEXT,
    is_own INTEGER DEFAULT 0,
    added_date TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS book_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    snapshot_date TEXT NOT NULL,
    bsr_overall INTEGER,
    bsr_category TEXT,
    price_kindle REAL,
    price_paperback REAL,
    review_count INTEGER,
    avg_rating REAL,
    page_count INTEGER,
    estimated_daily_sales REAL,
    estimated_monthly_revenue REAL,
    UNIQUE(book_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS keyword_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    book_id INTEGER NOT NULL REFERENCES books(id),
    snapshot_date TEXT NOT NULL,
    rank_position INTEGER,
    source TEXT,
    UNIQUE(keyword_id, book_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS ads_search_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_name TEXT,
    ad_group TEXT,
    search_term TEXT NOT NULL,
    keyword_match_type TEXT,
    impressions INTEGER,
    clicks INTEGER,
    ctr REAL,
    spend REAL,
    sales REAL,
    acos REAL,
    orders INTEGER,
    report_date TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    browse_node_id TEXT UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id),
    path TEXT,
    books_count INTEGER,
    bsr_for_top_1 INTEGER,
    bsr_for_top_20 INTEGER,
    last_scanned TEXT
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_keywords_source ON keywords(source);
CREATE INDEX IF NOT EXISTS idx_keywords_category ON keywords(category);
CREATE INDEX IF NOT EXISTS idx_keywords_active ON keywords(is_active);

CREATE INDEX IF NOT EXISTS idx_keyword_metrics_keyword_id ON keyword_metrics(keyword_id);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_date ON keyword_metrics(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_books_asin ON books(asin);
CREATE INDEX IF NOT EXISTS idx_books_is_own ON books(is_own);

CREATE INDEX IF NOT EXISTS idx_book_snapshots_book_id ON book_snapshots(book_id);
CREATE INDEX IF NOT EXISTS idx_book_snapshots_date ON book_snapshots(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_keyword_rankings_keyword ON keyword_rankings(keyword_id);
CREATE INDEX IF NOT EXISTS idx_keyword_rankings_book ON keyword_rankings(book_id);
CREATE INDEX IF NOT EXISTS idx_keyword_rankings_date ON keyword_rankings(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_ads_search_terms_term ON ads_search_terms(search_term);
CREATE INDEX IF NOT EXISTS idx_ads_search_terms_campaign ON ads_search_terms(campaign_name);
CREATE INDEX IF NOT EXISTS idx_ads_search_terms_date ON ads_search_terms(report_date);

CREATE INDEX IF NOT EXISTS idx_categories_browse_node ON categories(browse_node_id);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
"""


def get_connection():
    """Get a database connection, creating the database if needed.

    Returns:
        sqlite3.Connection with row factory set to sqlite3.Row.
    """
    db_path = Config.get_db_path()

    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')

    return conn


def init_db():
    """Initialize the database schema and indexes."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDEX_SQL)
        conn.commit()
        logger.info(f'Database initialized at {Config.get_db_path()}')
    finally:
        conn.close()


class KeywordRepository:
    """Data access for keywords and keyword_metrics tables."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def find_by_keyword(self, keyword):
        """Find a keyword record by its text.

        Args:
            keyword: The keyword string to search for.

        Returns:
            sqlite3.Row or None.
        """
        cursor = self._conn.execute(
            'SELECT * FROM keywords WHERE keyword = ?',
            (keyword.lower().strip(),),
        )
        return cursor.fetchone()

    def upsert_keyword(self, keyword, source='autocomplete', category=None):
        """Insert a keyword or update its last_updated timestamp.

        Args:
            keyword: The keyword text.
            source: Source of the keyword (e.g., 'autocomplete', 'ads_import').
            category: Optional category classification.

        Returns:
            Tuple of (keyword_id, is_new) where is_new is True if inserted.
        """
        keyword = keyword.lower().strip()
        now = datetime.now().isoformat()

        existing = self.find_by_keyword(keyword)
        if existing:
            self._conn.execute(
                'UPDATE keywords SET last_updated = ? WHERE id = ?',
                (now, existing['id']),
            )
            self._conn.commit()
            return existing['id'], False

        cursor = self._conn.execute(
            'INSERT INTO keywords (keyword, source, category, first_seen, last_updated) '
            'VALUES (?, ?, ?, ?, ?)',
            (keyword, source, category, now, now),
        )
        self._conn.commit()
        return cursor.lastrowid, True

    def add_metric(self, keyword_id, autocomplete_position=None, **kwargs):
        """Add a keyword_metrics snapshot for today.

        Args:
            keyword_id: ID of the keyword.
            autocomplete_position: Position in autocomplete results.
            **kwargs: Additional metric fields.
        """
        today = date.today().isoformat()

        # Check if we already have a snapshot for today
        existing = self._conn.execute(
            'SELECT id FROM keyword_metrics WHERE keyword_id = ? AND snapshot_date = ?',
            (keyword_id, today),
        ).fetchone()

        if existing:
            # Update existing snapshot
            self._conn.execute(
                'UPDATE keyword_metrics SET autocomplete_position = ? WHERE id = ?',
                (autocomplete_position, existing['id']),
            )
        else:
            self._conn.execute(
                'INSERT INTO keyword_metrics '
                '(keyword_id, snapshot_date, autocomplete_position, '
                'estimated_volume, volume_source, competition_count, '
                'avg_bsr_top_results, suggested_bid, impressions, clicks, orders) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    keyword_id,
                    today,
                    autocomplete_position,
                    kwargs.get('estimated_volume'),
                    kwargs.get('volume_source'),
                    kwargs.get('competition_count'),
                    kwargs.get('avg_bsr_top_results'),
                    kwargs.get('suggested_bid'),
                    kwargs.get('impressions'),
                    kwargs.get('clicks'),
                    kwargs.get('orders'),
                ),
            )
        self._conn.commit()

    def get_all_keywords(self, active_only=True):
        """Get all keywords, optionally filtered to active only.

        Args:
            active_only: If True, only return active keywords.

        Returns:
            List of sqlite3.Row objects.
        """
        query = 'SELECT * FROM keywords'
        if active_only:
            query += ' WHERE is_active = 1'
        query += ' ORDER BY last_updated DESC'
        return self._conn.execute(query).fetchall()

    def get_keyword_count(self):
        """Get the total number of keywords in the database."""
        row = self._conn.execute('SELECT COUNT(*) as cnt FROM keywords').fetchone()
        return row['cnt']

    def get_keywords_with_latest_metrics(self, limit=20):
        """Get keywords with their most recent metrics, sorted by autocomplete position.

        Args:
            limit: Maximum number of results.

        Returns:
            List of sqlite3.Row objects with keyword and metric fields.
        """
        query = """
            SELECT k.keyword, k.source, k.first_seen, k.category,
                   km.autocomplete_position, km.snapshot_date,
                   km.estimated_volume, km.competition_count
            FROM keywords k
            LEFT JOIN keyword_metrics km ON k.id = km.keyword_id
                AND km.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM keyword_metrics
                    WHERE keyword_id = k.id
                )
            WHERE k.is_active = 1
            ORDER BY
                CASE WHEN km.autocomplete_position IS NOT NULL THEN 0 ELSE 1 END,
                km.autocomplete_position ASC,
                k.last_updated DESC
            LIMIT ?
        """
        return self._conn.execute(query, (limit,)).fetchall()


class BookRepository:
    """Data access for books and book_snapshots tables.

    Stub for Phase 2 - competitor tracking.
    """

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()


class AdsRepository:
    """Data access for ads_search_terms table.

    Stub for Phase 3 - Amazon Ads data import.
    """

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()


class CategoryRepository:
    """Data access for categories table.

    Stub for Phase 2 - category analysis.
    """

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()
