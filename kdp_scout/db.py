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
    """Initialize the database schema, indexes, and run migrations."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDEX_SQL)

        # Migration: add score column to keywords if not present
        _migrate_add_score_column(conn)

        conn.commit()
        logger.info(f'Database initialized at {Config.get_db_path()}')
    finally:
        conn.close()


def _migrate_add_score_column(conn):
    """Add score column to keywords table if it doesn't exist."""
    cursor = conn.execute("PRAGMA table_info(keywords)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'score' not in columns:
        conn.execute('ALTER TABLE keywords ADD COLUMN score REAL DEFAULT 0')
        logger.info('Migration: added score column to keywords table')


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

        If a snapshot already exists for today, non-None fields are merged
        (existing values are preserved unless new values are provided).

        Args:
            keyword_id: ID of the keyword.
            autocomplete_position: Position in autocomplete results.
            **kwargs: Additional metric fields (impressions, clicks, orders, etc.).
        """
        today = date.today().isoformat()

        # Check if we already have a snapshot for today
        existing = self._conn.execute(
            'SELECT * FROM keyword_metrics WHERE keyword_id = ? AND snapshot_date = ?',
            (keyword_id, today),
        ).fetchone()

        if existing:
            # Merge: update only fields that are provided and not None
            updates = []
            params = []

            if autocomplete_position is not None:
                updates.append('autocomplete_position = ?')
                params.append(autocomplete_position)

            merge_fields = [
                'estimated_volume', 'volume_source', 'competition_count',
                'avg_bsr_top_results', 'suggested_bid', 'impressions',
                'clicks', 'orders',
            ]
            for field in merge_fields:
                val = kwargs.get(field)
                if val is not None:
                    updates.append(f'{field} = ?')
                    params.append(val)

            if updates:
                params.append(existing['id'])
                self._conn.execute(
                    f'UPDATE keyword_metrics SET {", ".join(updates)} WHERE id = ?',
                    params,
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

    def get_keywords_with_latest_metrics(self, limit=20, min_score=0,
                                         order_by='score'):
        """Get keywords with their most recent metrics.

        Args:
            limit: Maximum number of results.
            min_score: Minimum keyword score to include.
            order_by: Sort order - 'score', 'autocomplete', or 'impressions'.

        Returns:
            List of sqlite3.Row objects with keyword and metric fields.
        """
        if order_by == 'score':
            order_clause = """
                ORDER BY k.score DESC,
                    CASE WHEN km.autocomplete_position IS NOT NULL THEN 0 ELSE 1 END,
                    km.autocomplete_position ASC
            """
        elif order_by == 'impressions':
            order_clause = """
                ORDER BY km.impressions DESC NULLS LAST,
                    k.score DESC
            """
        else:
            order_clause = """
                ORDER BY
                    CASE WHEN km.autocomplete_position IS NOT NULL THEN 0 ELSE 1 END,
                    km.autocomplete_position ASC,
                    k.last_updated DESC
            """

        query = f"""
            SELECT k.id, k.keyword, k.source, k.first_seen, k.category, k.score,
                   km.autocomplete_position, km.snapshot_date,
                   km.estimated_volume, km.competition_count,
                   km.avg_bsr_top_results, km.impressions, km.clicks, km.orders
            FROM keywords k
            LEFT JOIN keyword_metrics km ON k.id = km.keyword_id
                AND km.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM keyword_metrics
                    WHERE keyword_id = k.id
                )
            WHERE k.is_active = 1 AND k.score >= ?
            {order_clause}
            LIMIT ?
        """
        return self._conn.execute(query, (min_score, limit)).fetchall()

    def get_keyword_with_metrics(self, keyword_id):
        """Get a single keyword with its latest metrics.

        Args:
            keyword_id: ID of the keyword.

        Returns:
            sqlite3.Row or None.
        """
        query = """
            SELECT k.id, k.keyword, k.source, k.first_seen, k.category, k.score,
                   km.autocomplete_position, km.snapshot_date,
                   km.estimated_volume, km.competition_count,
                   km.avg_bsr_top_results, km.impressions, km.clicks, km.orders
            FROM keywords k
            LEFT JOIN keyword_metrics km ON k.id = km.keyword_id
                AND km.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM keyword_metrics
                    WHERE keyword_id = k.id
                )
            WHERE k.id = ?
        """
        return self._conn.execute(query, (keyword_id,)).fetchone()

    def update_score(self, keyword_id, score):
        """Update the score for a keyword.

        Args:
            keyword_id: ID of the keyword.
            score: The computed score value.
        """
        self._conn.execute(
            'UPDATE keywords SET score = ? WHERE id = ?',
            (score, keyword_id),
        )
        self._conn.commit()

    def get_all_keyword_ids(self, active_only=True):
        """Get all keyword IDs.

        Args:
            active_only: If True, only return active keywords.

        Returns:
            List of integer IDs.
        """
        query = 'SELECT id FROM keywords'
        if active_only:
            query += ' WHERE is_active = 1'
        rows = self._conn.execute(query).fetchall()
        return [row['id'] for row in rows]

    def get_keyword_metrics_history(self, keyword_id, days=30):
        """Get metric snapshots for a keyword within a date range.

        Args:
            keyword_id: ID of the keyword.
            days: Number of days to look back.

        Returns:
            List of sqlite3.Row objects ordered by date ascending.
        """
        query = """
            SELECT * FROM keyword_metrics
            WHERE keyword_id = ?
              AND snapshot_date >= date('now', ?)
            ORDER BY snapshot_date ASC
        """
        return self._conn.execute(
            query, (keyword_id, f'-{days} days')
        ).fetchall()


class BookRepository:
    """Data access for books and book_snapshots tables."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def find_by_asin(self, asin):
        """Find a book record by its ASIN.

        Args:
            asin: Amazon Standard Identification Number.

        Returns:
            sqlite3.Row or None.
        """
        cursor = self._conn.execute(
            'SELECT * FROM books WHERE asin = ?',
            (asin.upper().strip(),),
        )
        return cursor.fetchone()

    def upsert_book(self, asin, title=None, author=None, is_own=False, notes=None):
        """Insert a book or update its metadata.

        Args:
            asin: Amazon ASIN.
            title: Book title.
            author: Author name.
            is_own: Whether this is the user's own book.
            notes: Optional notes.

        Returns:
            Tuple of (book_id, is_new) where is_new is True if inserted.
        """
        asin = asin.upper().strip()
        now = datetime.now().isoformat()

        existing = self.find_by_asin(asin)
        if existing:
            # Update fields if new values provided
            updates = []
            params = []
            if title is not None:
                updates.append('title = ?')
                params.append(title)
            if author is not None:
                updates.append('author = ?')
                params.append(author)
            if is_own:
                updates.append('is_own = ?')
                params.append(1)
            if notes is not None:
                updates.append('notes = ?')
                params.append(notes)

            if updates:
                params.append(existing['id'])
                self._conn.execute(
                    f'UPDATE books SET {", ".join(updates)} WHERE id = ?',
                    params,
                )
                self._conn.commit()

            return existing['id'], False

        cursor = self._conn.execute(
            'INSERT INTO books (asin, title, author, is_own, added_date, notes) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (asin, title, author, 1 if is_own else 0, now, notes),
        )
        self._conn.commit()
        return cursor.lastrowid, True

    def remove_book(self, asin):
        """Remove a book and its snapshots from tracking.

        Args:
            asin: Amazon ASIN.

        Returns:
            True if the book was found and removed, False otherwise.
        """
        asin = asin.upper().strip()
        existing = self.find_by_asin(asin)
        if not existing:
            return False

        book_id = existing['id']
        self._conn.execute(
            'DELETE FROM book_snapshots WHERE book_id = ?', (book_id,)
        )
        self._conn.execute(
            'DELETE FROM books WHERE id = ?', (book_id,)
        )
        self._conn.commit()
        return True

    def get_all_books(self):
        """Get all tracked books.

        Returns:
            List of sqlite3.Row objects.
        """
        return self._conn.execute(
            'SELECT * FROM books ORDER BY is_own DESC, title ASC'
        ).fetchall()

    def add_snapshot(self, book_id, bsr_overall=None, bsr_category=None,
                     price_kindle=None, price_paperback=None,
                     review_count=None, avg_rating=None, page_count=None,
                     estimated_daily_sales=None, estimated_monthly_revenue=None):
        """Add a snapshot for a tracked book.

        If a snapshot already exists for today, it is updated.

        Args:
            book_id: ID of the book.
            bsr_overall: Overall Best Sellers Rank.
            bsr_category: JSON string of category ranks.
            price_kindle: Kindle price.
            price_paperback: Paperback price.
            review_count: Number of reviews.
            avg_rating: Average star rating.
            page_count: Number of pages.
            estimated_daily_sales: Estimated daily unit sales.
            estimated_monthly_revenue: Estimated monthly revenue.

        Returns:
            The snapshot ID.
        """
        today = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT id FROM book_snapshots WHERE book_id = ? AND snapshot_date = ?',
            (book_id, today),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE book_snapshots SET '
                'bsr_overall = ?, bsr_category = ?, '
                'price_kindle = ?, price_paperback = ?, '
                'review_count = ?, avg_rating = ?, page_count = ?, '
                'estimated_daily_sales = ?, estimated_monthly_revenue = ? '
                'WHERE id = ?',
                (
                    bsr_overall, bsr_category,
                    price_kindle, price_paperback,
                    review_count, avg_rating, page_count,
                    estimated_daily_sales, estimated_monthly_revenue,
                    existing['id'],
                ),
            )
            self._conn.commit()
            return existing['id']

        cursor = self._conn.execute(
            'INSERT INTO book_snapshots '
            '(book_id, snapshot_date, bsr_overall, bsr_category, '
            'price_kindle, price_paperback, review_count, avg_rating, '
            'page_count, estimated_daily_sales, estimated_monthly_revenue) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                book_id, today, bsr_overall, bsr_category,
                price_kindle, price_paperback,
                review_count, avg_rating, page_count,
                estimated_daily_sales, estimated_monthly_revenue,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_latest_snapshot(self, book_id):
        """Get the most recent snapshot for a book.

        Args:
            book_id: ID of the book.

        Returns:
            sqlite3.Row or None.
        """
        return self._conn.execute(
            'SELECT * FROM book_snapshots WHERE book_id = ? '
            'ORDER BY snapshot_date DESC LIMIT 1',
            (book_id,),
        ).fetchone()

    def get_previous_snapshot(self, book_id):
        """Get the second most recent snapshot for a book (for comparison).

        Args:
            book_id: ID of the book.

        Returns:
            sqlite3.Row or None.
        """
        return self._conn.execute(
            'SELECT * FROM book_snapshots WHERE book_id = ? '
            'ORDER BY snapshot_date DESC LIMIT 1 OFFSET 1',
            (book_id,),
        ).fetchone()

    def get_books_with_latest_snapshot(self):
        """Get all tracked books with their latest snapshot data.

        Returns:
            List of dicts with book and snapshot fields merged.
        """
        query = """
            SELECT b.*, bs.bsr_overall, bs.bsr_category,
                   bs.price_kindle, bs.price_paperback,
                   bs.review_count, bs.avg_rating, bs.page_count,
                   bs.estimated_daily_sales, bs.estimated_monthly_revenue,
                   bs.snapshot_date as last_snapshot_date
            FROM books b
            LEFT JOIN book_snapshots bs ON b.id = bs.book_id
                AND bs.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM book_snapshots
                    WHERE book_id = b.id
                )
            ORDER BY b.is_own DESC, bs.bsr_overall ASC
        """
        return self._conn.execute(query).fetchall()


class AdsRepository:
    """Data access for ads_search_terms table."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def add_search_term(self, campaign_name=None, ad_group=None,
                        search_term=None, keyword_match_type=None,
                        impressions=None, clicks=None, ctr=None,
                        spend=None, sales=None, acos=None, orders=None,
                        report_date=None, imported_at=None):
        """Add an ads search term record.

        Args:
            campaign_name: Campaign name from the report.
            ad_group: Ad group name.
            search_term: The customer search term.
            keyword_match_type: Match type (broad, phrase, exact).
            impressions: Number of impressions.
            clicks: Number of clicks.
            ctr: Click-through rate as decimal.
            spend: Total spend in dollars.
            sales: Total sales in dollars.
            acos: Advertising cost of sales as decimal.
            orders: Number of orders.
            report_date: Date of the report data.
            imported_at: Timestamp of import.

        Returns:
            The inserted row ID.
        """
        cursor = self._conn.execute(
            'INSERT INTO ads_search_terms '
            '(campaign_name, ad_group, search_term, keyword_match_type, '
            'impressions, clicks, ctr, spend, sales, acos, orders, '
            'report_date, imported_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                campaign_name, ad_group, search_term, keyword_match_type,
                impressions, clicks, ctr, spend, sales, acos, orders,
                report_date, imported_at,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_all_search_terms(self, campaign_filter=None):
        """Get all search terms, optionally filtered by campaign.

        Args:
            campaign_filter: Optional campaign name substring to filter by.

        Returns:
            List of sqlite3.Row objects.
        """
        if campaign_filter:
            return self._conn.execute(
                'SELECT * FROM ads_search_terms '
                'WHERE campaign_name LIKE ? '
                'ORDER BY orders DESC, impressions DESC',
                (f'%{campaign_filter}%',),
            ).fetchall()
        return self._conn.execute(
            'SELECT * FROM ads_search_terms '
            'ORDER BY orders DESC, impressions DESC'
        ).fetchall()

    def get_aggregated_search_terms(self):
        """Get search terms aggregated across all report dates.

        Returns:
            List of sqlite3.Row objects with summed metrics per search term.
        """
        return self._conn.execute(
            'SELECT search_term, '
            '  SUM(impressions) as total_impressions, '
            '  SUM(clicks) as total_clicks, '
            '  SUM(spend) as total_spend, '
            '  SUM(sales) as total_sales, '
            '  SUM(orders) as total_orders, '
            '  CASE WHEN SUM(sales) > 0 '
            '    THEN SUM(spend) / SUM(sales) '
            '    ELSE NULL END as avg_acos, '
            '  CASE WHEN SUM(impressions) > 0 '
            '    THEN CAST(SUM(clicks) AS REAL) / SUM(impressions) '
            '    ELSE NULL END as avg_ctr '
            'FROM ads_search_terms '
            'GROUP BY search_term '
            'ORDER BY total_orders DESC, total_impressions DESC'
        ).fetchall()

    def get_search_term_count(self):
        """Get the total number of search term records."""
        row = self._conn.execute(
            'SELECT COUNT(*) as cnt FROM ads_search_terms'
        ).fetchone()
        return row['cnt']

    def get_opportunity_keywords(self):
        """Get keywords with impressions but no orders (opportunity keywords).

        These are search terms where your ads appeared but didn't convert,
        indicating potential keyword gaps or optimization opportunities.

        Returns:
            List of sqlite3.Row objects.
        """
        return self._conn.execute(
            'SELECT search_term, '
            '  SUM(impressions) as total_impressions, '
            '  SUM(clicks) as total_clicks, '
            '  SUM(spend) as total_spend, '
            '  SUM(orders) as total_orders '
            'FROM ads_search_terms '
            'GROUP BY search_term '
            'HAVING SUM(impressions) > 0 AND (SUM(orders) IS NULL OR SUM(orders) = 0) '
            'ORDER BY total_impressions DESC'
        ).fetchall()


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
