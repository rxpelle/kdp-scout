"""Output formatters for KDP Scout.

Provides consistent formatting across table, CSV, and JSON output
modes for keywords, books, and ranking data. All report commands
can use these formatters for uniform output.
"""

import csv
import io
import json
import sys
import logging

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()


class OutputFormatter:
    """Formats data in table, CSV, or JSON output modes.

    Provides a consistent interface for rendering keywords, books,
    and rankings data in the user's preferred format.
    """

    def __init__(self, output_format='table'):
        """Initialize the formatter.

        Args:
            output_format: Output mode - 'table', 'csv', or 'json'.
        """
        if output_format not in ('table', 'csv', 'json'):
            raise ValueError(
                f'Unknown format "{output_format}". '
                f'Must be one of: table, csv, json'
            )
        self.format = output_format

    def format_keywords(self, keywords, title='Keywords'):
        """Format keyword data in the specified format.

        Args:
            keywords: List of sqlite3.Row or dict objects with keyword data.
                      Expected keys: keyword, score, autocomplete_position,
                      impressions, clicks, orders, source.
            title: Title for the table output.

        Returns:
            Formatted string (CSV/JSON) or None (table is printed directly).
        """
        if self.format == 'json':
            return self._keywords_json(keywords)
        elif self.format == 'csv':
            return self._keywords_csv(keywords)
        else:
            self._keywords_table(keywords, title)
            return None

    def format_books(self, books, title='Tracked Books'):
        """Format book data in the specified format.

        Args:
            books: List of sqlite3.Row or dict objects with book data.
                   Expected keys: asin, title, author, is_own, bsr_overall,
                   price_kindle, review_count, avg_rating,
                   estimated_daily_sales, estimated_monthly_revenue.
            title: Title for the table output.

        Returns:
            Formatted string (CSV/JSON) or None (table is printed directly).
        """
        if self.format == 'json':
            return self._books_json(books)
        elif self.format == 'csv':
            return self._books_csv(books)
        else:
            self._books_table(books, title)
            return None

    def format_rankings(self, rankings, title='Keyword Rankings'):
        """Format ranking data in the specified format.

        Args:
            rankings: List of dicts with ranking data.
                      Expected keys: keyword, book_asin, rank_position,
                      snapshot_date, source.
            title: Title for the table output.

        Returns:
            Formatted string (CSV/JSON) or None (table is printed directly).
        """
        if self.format == 'json':
            return self._rankings_json(rankings)
        elif self.format == 'csv':
            return self._rankings_csv(rankings)
        else:
            self._rankings_table(rankings, title)
            return None

    # ── Keyword formatters ────────────────────────────────────────

    def _keywords_json(self, keywords):
        """Render keywords as JSON."""
        data = []
        for i, kw in enumerate(keywords, 1):
            data.append({
                'rank': i,
                'keyword': _get(kw, 'keyword'),
                'score': _get(kw, 'score') or 0,
                'autocomplete_position': _get(kw, 'autocomplete_position'),
                'impressions': _get(kw, 'impressions'),
                'clicks': _get(kw, 'clicks'),
                'orders': _get(kw, 'orders'),
                'source': _get(kw, 'source'),
            })
        output = json.dumps(data, indent=2)
        print(output)
        return output

    def _keywords_csv(self, keywords):
        """Render keywords as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Rank', 'Keyword', 'Score', 'Autocomplete Position',
            'Impressions', 'Clicks', 'Orders', 'Source',
        ])
        for i, kw in enumerate(keywords, 1):
            writer.writerow([
                i,
                _get(kw, 'keyword'),
                _get(kw, 'score') or 0,
                _get(kw, 'autocomplete_position') or '',
                _get(kw, 'impressions') or '',
                _get(kw, 'clicks') or '',
                _get(kw, 'orders') or '',
                _get(kw, 'source') or '',
            ])
        content = output.getvalue()
        print(content, end='')
        return content

    def _keywords_table(self, keywords, title):
        """Render keywords as a rich table."""
        table = Table(title=title, show_lines=False)
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold', min_width=20, no_wrap=False)
        table.add_column('Score', justify='right', width=7, style='bold cyan')
        table.add_column('AC Pos', justify='center', width=7)
        table.add_column('Impressions', justify='right', width=12)
        table.add_column('Clicks', justify='right', width=8)
        table.add_column('Orders', justify='right', width=8)
        table.add_column('Source', justify='center', width=14)

        for i, kw in enumerate(keywords, 1):
            score_val = _get(kw, 'score') or 0
            score_str = f'{score_val:.0f}'

            if score_val >= 100:
                score_str = f'[bold green]{score_str}[/bold green]'
            elif score_val >= 75:
                score_str = f'[green]{score_str}[/green]'
            elif score_val >= 50:
                score_str = f'[yellow]{score_str}[/yellow]'
            elif score_val >= 25:
                score_str = f'[dim]{score_str}[/dim]'

            pos = _get(kw, 'autocomplete_position')
            imp = _get(kw, 'impressions')
            clicks = _get(kw, 'clicks')
            orders = _get(kw, 'orders')

            table.add_row(
                str(i),
                _get(kw, 'keyword') or '',
                score_str,
                str(pos) if pos else '-',
                f'{imp:,}' if imp else '-',
                f'{clicks:,}' if clicks else '-',
                str(orders) if orders else '-',
                _get(kw, 'source') or '-',
            )

        console.print(table)

    # ── Book formatters ───────────────────────────────────────────

    def _books_json(self, books):
        """Render books as JSON."""
        data = []
        for book in books:
            data.append({
                'asin': _get(book, 'asin'),
                'title': _get(book, 'title'),
                'author': _get(book, 'author'),
                'is_own': bool(_get(book, 'is_own')),
                'bsr_overall': _get(book, 'bsr_overall'),
                'price_kindle': _get(book, 'price_kindle'),
                'price_paperback': _get(book, 'price_paperback'),
                'review_count': _get(book, 'review_count'),
                'avg_rating': _get(book, 'avg_rating'),
                'page_count': _get(book, 'page_count'),
                'estimated_daily_sales': _get(book, 'estimated_daily_sales'),
                'estimated_monthly_revenue': _get(book, 'estimated_monthly_revenue'),
            })
        output = json.dumps(data, indent=2)
        print(output)
        return output

    def _books_csv(self, books):
        """Render books as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ASIN', 'Title', 'Author', 'Own Book', 'BSR',
            'Kindle Price', 'Paperback Price', 'Reviews', 'Rating',
            'Pages', 'Daily Sales', 'Monthly Revenue',
        ])
        for book in books:
            writer.writerow([
                _get(book, 'asin'),
                _get(book, 'title') or '',
                _get(book, 'author') or '',
                'Yes' if _get(book, 'is_own') else 'No',
                _get(book, 'bsr_overall') or '',
                _get(book, 'price_kindle') or '',
                _get(book, 'price_paperback') or '',
                _get(book, 'review_count') or '',
                _get(book, 'avg_rating') or '',
                _get(book, 'page_count') or '',
                _get(book, 'estimated_daily_sales') or '',
                _get(book, 'estimated_monthly_revenue') or '',
            ])
        content = output.getvalue()
        print(content, end='')
        return content

    def _books_table(self, books, title):
        """Render books as a rich table."""
        table = Table(title=title, show_lines=True, expand=True)
        table.add_column('ASIN', width=12, no_wrap=True)
        table.add_column('Title', ratio=3, no_wrap=False)
        table.add_column('BSR', justify='right', width=9)
        table.add_column('Price', justify='right', width=7)
        table.add_column('Reviews', justify='right', width=8)
        table.add_column('Rating', justify='center', width=6)
        table.add_column('Sales/Day', justify='right', width=10)
        table.add_column('Rev/Month', justify='right', width=10)

        for book in books:
            is_own = _get(book, 'is_own')
            style = 'bold green' if is_own else ''

            bsr = _get(book, 'bsr_overall')
            price = _get(book, 'price_kindle')
            reviews = _get(book, 'review_count')
            rating = _get(book, 'avg_rating')
            daily = _get(book, 'estimated_daily_sales')
            monthly = _get(book, 'estimated_monthly_revenue')

            book_title = _get(book, 'title') or 'Unknown'
            author = _get(book, 'author') or ''
            display_title = f'{book_title}\nby {author}' if author else book_title
            if is_own:
                display_title = f'[bold]{display_title}[/bold]'

            table.add_row(
                _get(book, 'asin') or '',
                display_title,
                f'{int(bsr):,}' if bsr else '-',
                f'${price:.2f}' if price else '-',
                f'{int(reviews):,}' if reviews else '-',
                f'{rating:.1f}' if rating else '-',
                f'{daily:.1f}' if daily else '-',
                f'${monthly:,.0f}' if monthly else '-',
                style=style,
            )

        console.print(table)

    # ── Rankings formatters ───────────────────────────────────────

    def _rankings_json(self, rankings):
        """Render rankings as JSON."""
        data = []
        for r in rankings:
            data.append({
                'keyword': _get(r, 'keyword'),
                'book_asin': _get(r, 'book_asin'),
                'rank_position': _get(r, 'rank_position'),
                'snapshot_date': _get(r, 'snapshot_date'),
                'source': _get(r, 'source'),
            })
        output = json.dumps(data, indent=2)
        print(output)
        return output

    def _rankings_csv(self, rankings):
        """Render rankings as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Keyword', 'Book ASIN', 'Rank Position',
            'Snapshot Date', 'Source',
        ])
        for r in rankings:
            writer.writerow([
                _get(r, 'keyword') or '',
                _get(r, 'book_asin') or '',
                _get(r, 'rank_position') or '',
                _get(r, 'snapshot_date') or '',
                _get(r, 'source') or '',
            ])
        content = output.getvalue()
        print(content, end='')
        return content

    def _rankings_table(self, rankings, title):
        """Render rankings as a rich table."""
        table = Table(title=title, show_lines=False)
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold', ratio=3)
        table.add_column('Book ASIN', width=12)
        table.add_column('Rank', justify='right', width=6)
        table.add_column('Date', width=10)
        table.add_column('Source', width=12)

        for i, r in enumerate(rankings, 1):
            table.add_row(
                str(i),
                _get(r, 'keyword') or '',
                _get(r, 'book_asin') or '',
                str(_get(r, 'rank_position') or '-'),
                _get(r, 'snapshot_date') or '-',
                _get(r, 'source') or '-',
            )

        console.print(table)


def _get(obj, key):
    """Safely get a value from a dict-like object (dict or sqlite3.Row).

    Args:
        obj: Dict or sqlite3.Row.
        key: Key to look up.

    Returns:
        The value, or None if not found.
    """
    try:
        return obj[key]
    except (KeyError, IndexError, TypeError):
        try:
            return getattr(obj, key, None)
        except Exception:
            return None
