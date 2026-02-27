"""Report generation for KDP Scout.

Provides Rich-formatted tables and panels for keyword and competitor
analysis output. Used by CLI commands for display.
"""

import logging

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from kdp_scout.db import KeywordRepository, BookRepository, init_db

logger = logging.getLogger(__name__)
console = Console()


class ReportingEngine:
    """Generates formatted reports for keyword and competitor data."""

    def __init__(self):
        """Initialize the reporting engine with database access."""
        init_db()
        self._kw_repo = KeywordRepository()
        self._book_repo = BookRepository()

    def close(self):
        """Close database connections."""
        self._kw_repo.close()
        self._book_repo.close()

    def keyword_summary(self, limit=50):
        """Print a rich table of top keywords by autocomplete position.

        Args:
            limit: Maximum number of keywords to display.
        """
        keywords = self._kw_repo.get_keywords_with_latest_metrics(limit=limit)

        if not keywords:
            console.print('[yellow]No keywords in database. Run "kdp-scout mine" first.[/yellow]')
            return

        table = Table(
            title=f'Top Keywords (by Autocomplete Position)',
            show_lines=False,
        )
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold')
        table.add_column('Position', justify='center', width=10)
        table.add_column('Source', justify='center', width=14)
        table.add_column('Category', width=20)
        table.add_column('First Seen', width=12)

        for i, kw in enumerate(keywords, 1):
            pos = str(kw['autocomplete_position']) if kw['autocomplete_position'] else '-'
            table.add_row(
                str(i),
                kw['keyword'],
                pos,
                kw['source'] or '-',
                kw['category'] or '-',
                (kw['first_seen'] or '')[:10],
            )

        console.print(table)
        console.print(f'\n[dim]Showing {len(keywords)} of {self._kw_repo.get_keyword_count()} total keywords[/dim]')

    def competitor_summary(self):
        """Print a rich table comparing all tracked books."""
        books = self._book_repo.get_books_with_latest_snapshot()

        if not books:
            console.print(
                '[yellow]No books tracked. Use "kdp-scout track add <ASIN>" to start.[/yellow]'
            )
            return

        table = Table(
            title='Competitor Comparison',
            show_lines=True,
            expand=True,
        )
        table.add_column('ASIN', width=12, no_wrap=True)
        table.add_column('Title', ratio=3, no_wrap=False)
        table.add_column('BSR', justify='right', width=9)
        table.add_column('Price', justify='right', width=7)
        table.add_column('Reviews', justify='right', width=8)
        table.add_column('Rating', justify='center', width=6)
        table.add_column('Sales/Day', justify='right', width=10)
        table.add_column('Rev/Month', justify='right', width=10)

        for book in books:
            is_own = book['is_own']
            style = 'bold green' if is_own else ''

            bsr = _fmt_number(book['bsr_overall'])
            price = _fmt_price(book['price_kindle'])
            reviews = _fmt_number(book['review_count'])
            rating = f"{book['avg_rating']:.1f}" if book['avg_rating'] else '-'
            daily_sales = f"{book['estimated_daily_sales']:.1f}" if book['estimated_daily_sales'] else '-'
            monthly_rev = _fmt_price(book['estimated_monthly_revenue'])

            title = book['title'] or 'Unknown'
            author = book['author'] or ''
            display_title = f'{title}\nby {author}' if author else title
            if is_own:
                display_title = f'[bold]{display_title}[/bold]'

            table.add_row(
                book['asin'],
                display_title,
                bsr,
                price,
                reviews,
                rating,
                daily_sales,
                monthly_rev,
                style=style,
            )

        console.print(table)


def _fmt_number(value):
    """Format a number with comma separators, or '-' if None."""
    if value is None:
        return '-'
    return f'{int(value):,}'


def _fmt_price(value):
    """Format a price as $X.XX, or '-' if None or zero."""
    if value is None or value == 0:
        return '-'
    return f'${value:,.2f}'
