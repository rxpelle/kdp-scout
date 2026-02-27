"""Competitor analysis engine.

Coordinates book tracking, BSR snapshots, and competitor comparisons.
Serves as the main entry point for the `track` CLI command group.
"""

import json
import logging

from kdp_scout.db import BookRepository, init_db
from kdp_scout.collectors.product_scraper import ProductScraper, CaptchaDetected
from kdp_scout.collectors.bsr_model import estimate_daily_sales, estimate_monthly_revenue

logger = logging.getLogger(__name__)


class CompetitorEngine:
    """Manages book tracking, snapshots, and competitor comparisons."""

    def __init__(self):
        """Initialize the engine with database and scraper."""
        init_db()
        self._repo = BookRepository()
        self._scraper = ProductScraper()

    def close(self):
        """Close database connection."""
        self._repo.close()

    def add_book(self, asin, name=None, is_own=False):
        """Add a book to tracking. Scrapes initial data and stores in DB.

        Args:
            asin: Amazon ASIN.
            name: Optional display name override.
            is_own: Whether this is the user's own book.

        Returns:
            Dict with book data and snapshot info, or None on scrape failure.

        Raises:
            CaptchaDetected: If Amazon serves a CAPTCHA page.
        """
        asin = asin.upper().strip()
        logger.info(f'Adding book to tracking: {asin}')

        # Scrape product page
        try:
            scraped = self._scraper.scrape_product(asin)
        except CaptchaDetected:
            raise
        except Exception as e:
            logger.error(f'Failed to scrape ASIN {asin}: {e}')
            scraped = None

        # Determine title and author
        title = name
        author = None
        if scraped:
            title = name or scraped.get('title')
            author = scraped.get('author')

        # Insert/update the book record
        book_id, is_new = self._repo.upsert_book(
            asin=asin,
            title=title,
            author=author,
            is_own=is_own,
        )

        result = {
            'book_id': book_id,
            'asin': asin,
            'title': title,
            'author': author,
            'is_own': is_own,
            'is_new': is_new,
            'scraped': scraped,
            'snapshot': None,
        }

        # Take initial snapshot if scrape succeeded
        if scraped:
            snapshot = self._store_snapshot(book_id, scraped)
            result['snapshot'] = snapshot

        return result

    def remove_book(self, asin):
        """Remove a book from tracking.

        Args:
            asin: Amazon ASIN.

        Returns:
            True if the book was found and removed, False otherwise.
        """
        asin = asin.upper().strip()
        removed = self._repo.remove_book(asin)
        if removed:
            logger.info(f'Removed book from tracking: {asin}')
        else:
            logger.warning(f'Book not found for removal: {asin}')
        return removed

    def list_books(self):
        """List all tracked books with latest snapshot data.

        Returns:
            List of sqlite3.Row objects with book and snapshot fields.
        """
        return self._repo.get_books_with_latest_snapshot()

    def take_snapshot(self, asin=None):
        """Take BSR/price/review snapshot of tracked books.

        If asin is None, snapshots ALL tracked books. Handles errors
        gracefully -- if one book fails, continues with the rest.

        Args:
            asin: Optional ASIN to snapshot. None = all tracked books.

        Returns:
            List of dicts with snapshot results for each book.
        """
        if asin:
            books = [self._repo.find_by_asin(asin.upper().strip())]
            if books[0] is None:
                logger.warning(f'Book not found: {asin}')
                return []
        else:
            books = self._repo.get_all_books()

        results = []
        for book in books:
            book_asin = book['asin']
            book_id = book['id']

            # Get previous snapshot for comparison
            prev_snapshot = self._repo.get_latest_snapshot(book_id)

            try:
                scraped = self._scraper.scrape_product(book_asin)
                if scraped is None:
                    results.append({
                        'asin': book_asin,
                        'title': book['title'],
                        'success': False,
                        'error': 'Scrape returned no data',
                    })
                    continue

                # Update book metadata if we got better data
                if scraped.get('title') and not book['title']:
                    self._repo.upsert_book(
                        asin=book_asin,
                        title=scraped['title'],
                        author=scraped.get('author'),
                    )

                snapshot = self._store_snapshot(book_id, scraped)

                # Calculate changes from previous snapshot
                changes = {}
                if prev_snapshot:
                    changes = self._calculate_changes(prev_snapshot, snapshot)

                results.append({
                    'asin': book_asin,
                    'title': book['title'] or scraped.get('title', 'Unknown'),
                    'success': True,
                    'snapshot': snapshot,
                    'changes': changes,
                })

            except CaptchaDetected as e:
                logger.warning(f'CAPTCHA detected while snapshotting {book_asin}')
                results.append({
                    'asin': book_asin,
                    'title': book['title'],
                    'success': False,
                    'error': str(e),
                })
            except Exception as e:
                logger.error(f'Error snapshotting {book_asin}: {e}')
                results.append({
                    'asin': book_asin,
                    'title': book['title'],
                    'success': False,
                    'error': str(e),
                })

        return results

    def compare_books(self, asins=None):
        """Compare metrics across tracked books.

        Args:
            asins: Optional list of ASINs to compare. None = all tracked books.

        Returns:
            List of sqlite3.Row objects with book and snapshot data.
        """
        all_books = self._repo.get_books_with_latest_snapshot()

        if asins:
            asin_set = {a.upper().strip() for a in asins}
            return [b for b in all_books if b['asin'] in asin_set]

        return all_books

    def _store_snapshot(self, book_id, scraped):
        """Store a snapshot from scraped data.

        Args:
            book_id: Database ID of the book.
            scraped: Dict from ProductScraper.scrape_product().

        Returns:
            Dict with the stored snapshot data.
        """
        bsr = scraped.get('bsr_overall')
        price_kindle = scraped.get('price_kindle')
        price_paperback = scraped.get('price_paperback')

        # Estimate sales from BSR
        daily_sales = None
        monthly_revenue = None
        if bsr:
            daily_sales = estimate_daily_sales(bsr, 'us_kindle')
            price_for_revenue = price_kindle or price_paperback
            if price_for_revenue:
                monthly_revenue = estimate_monthly_revenue(
                    bsr, price_for_revenue, 'us_kindle'
                )

        # Serialize category BSR as JSON
        bsr_category_json = None
        if scraped.get('bsr_categories'):
            bsr_category_json = json.dumps(scraped['bsr_categories'])

        snapshot_id = self._repo.add_snapshot(
            book_id=book_id,
            bsr_overall=bsr,
            bsr_category=bsr_category_json,
            price_kindle=price_kindle,
            price_paperback=price_paperback,
            review_count=scraped.get('review_count'),
            avg_rating=scraped.get('avg_rating'),
            page_count=scraped.get('page_count'),
            estimated_daily_sales=daily_sales,
            estimated_monthly_revenue=monthly_revenue,
        )

        return {
            'snapshot_id': snapshot_id,
            'bsr_overall': bsr,
            'bsr_categories': scraped.get('bsr_categories', {}),
            'price_kindle': price_kindle,
            'price_paperback': price_paperback,
            'review_count': scraped.get('review_count'),
            'avg_rating': scraped.get('avg_rating'),
            'page_count': scraped.get('page_count'),
            'estimated_daily_sales': daily_sales,
            'estimated_monthly_revenue': monthly_revenue,
        }

    def _calculate_changes(self, prev, current):
        """Calculate changes between two snapshots.

        Args:
            prev: Previous snapshot (sqlite3.Row).
            current: Current snapshot (dict).

        Returns:
            Dict of field_name -> (old_value, new_value, direction).
        """
        changes = {}

        comparisons = [
            ('bsr_overall', 'BSR', True),        # lower is better
            ('review_count', 'Reviews', False),   # higher is better
            ('avg_rating', 'Rating', False),      # higher is better
            ('price_kindle', 'Kindle Price', None),  # neutral
        ]

        for field, label, lower_is_better in comparisons:
            old_val = prev[field] if prev[field] is not None else None
            new_val = current.get(field)

            if old_val is not None and new_val is not None and old_val != new_val:
                if new_val < old_val:
                    direction = 'improved' if lower_is_better else 'declined'
                elif new_val > old_val:
                    direction = 'declined' if lower_is_better else 'improved'
                else:
                    direction = 'unchanged'

                changes[label] = {
                    'old': old_val,
                    'new': new_val,
                    'direction': direction,
                }

        return changes
