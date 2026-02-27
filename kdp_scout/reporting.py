"""Report generation for KDP Scout.

Provides Rich-formatted tables and panels for keyword, competitor,
and ads analysis output. Includes export functionality for Amazon Ads
campaign import and KDP backend keyword optimization.
"""

import csv
import io
import logging
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from kdp_scout.db import (
    KeywordRepository, BookRepository, AdsRepository,
    KeywordRankingRepository, init_db,
)

logger = logging.getLogger(__name__)
console = Console()

# Bid tiers based on keyword score
BID_TIERS = [
    (100, 1.50),
    (75, 1.00),
    (50, 0.75),
    (25, 0.50),
    (0, 0.35),
]

# KDP backend keyword constraints
KDP_SLOT_COUNT = 7
KDP_SLOT_MAX_BYTES = 50


class ReportingEngine:
    """Generates formatted reports for keyword, competitor, and ads data."""

    def __init__(self):
        """Initialize the reporting engine with database access."""
        init_db()
        self._kw_repo = KeywordRepository()
        self._book_repo = BookRepository()
        self._ads_repo = AdsRepository()
        self._ranking_repo = KeywordRankingRepository()

    def close(self):
        """Close database connections."""
        self._kw_repo.close()
        self._book_repo.close()
        self._ads_repo.close()
        self._ranking_repo.close()

    # ── Keyword Reports ───────────────────────────────────────────

    def keyword_summary(self, limit=50, min_score=0, output_format='table'):
        """Print a rich table of top keywords ranked by score.

        Args:
            limit: Maximum number of keywords to display.
            min_score: Minimum score threshold.
            output_format: 'table', 'csv', or 'json'.
        """
        keywords = self._kw_repo.get_keywords_with_latest_metrics(
            limit=limit, min_score=min_score, order_by='score',
        )

        if not keywords:
            console.print(
                '[yellow]No keywords in database. '
                'Run "kdp-scout mine" first.[/yellow]'
            )
            return

        if output_format == 'csv':
            self._keyword_summary_csv(keywords)
            return
        if output_format == 'json':
            self._keyword_summary_json(keywords)
            return

        table = Table(
            title='Top Keywords (by Score)',
            show_lines=False,
        )
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold', min_width=20, no_wrap=False)
        table.add_column('Score', justify='right', width=7,
                         style='bold cyan')
        table.add_column('AC Pos', justify='center', width=7)
        table.add_column('Impressions', justify='right', width=12)
        table.add_column('Clicks', justify='right', width=8)
        table.add_column('Orders', justify='right', width=8)
        table.add_column('Source', justify='center', width=14)

        for i, kw in enumerate(keywords, 1):
            pos = (str(kw['autocomplete_position'])
                   if kw['autocomplete_position'] else '-')
            impressions = (_fmt_number(kw['impressions'])
                          if kw['impressions'] else '-')
            clicks = (_fmt_number(kw['clicks'])
                      if kw['clicks'] else '-')
            orders = (_fmt_number(kw['orders'])
                      if kw['orders'] else '-')
            score = f"{kw['score']:.0f}" if kw['score'] else '0'

            # Color-code score
            score_val = kw['score'] or 0
            if score_val >= 100:
                score_str = f'[bold green]{score}[/bold green]'
            elif score_val >= 75:
                score_str = f'[green]{score}[/green]'
            elif score_val >= 50:
                score_str = f'[yellow]{score}[/yellow]'
            elif score_val >= 25:
                score_str = f'[dim]{score}[/dim]'
            else:
                score_str = score

            table.add_row(
                str(i),
                kw['keyword'],
                score_str,
                pos,
                impressions,
                clicks,
                orders,
                kw['source'] or '-',
            )

        console.print(table)
        total = self._kw_repo.get_keyword_count()
        console.print(
            f'\n[dim]Showing {len(keywords)} of {total} total keywords '
            f'(min score: {min_score})[/dim]'
        )

    def _keyword_summary_csv(self, keywords):
        """Output keyword summary as CSV to stdout."""
        writer = csv.writer(sys.stdout)
        writer.writerow([
            'Rank', 'Keyword', 'Score', 'Autocomplete Position',
            'Impressions', 'Clicks', 'Orders', 'Source',
        ])
        for i, kw in enumerate(keywords, 1):
            writer.writerow([
                i,
                kw['keyword'],
                kw['score'] or 0,
                kw['autocomplete_position'] or '',
                kw['impressions'] or '',
                kw['clicks'] or '',
                kw['orders'] or '',
                kw['source'] or '',
            ])

    def _keyword_summary_json(self, keywords):
        """Output keyword summary as JSON to stdout."""
        import json
        data = []
        for i, kw in enumerate(keywords, 1):
            data.append({
                'rank': i,
                'keyword': kw['keyword'],
                'score': kw['score'] or 0,
                'autocomplete_position': kw['autocomplete_position'],
                'impressions': kw['impressions'],
                'clicks': kw['clicks'],
                'orders': kw['orders'],
                'source': kw['source'],
            })
        print(json.dumps(data, indent=2))

    # ── Competitor Reports ────────────────────────────────────────

    def competitor_summary(self):
        """Print a rich table comparing all tracked books."""
        books = self._book_repo.get_books_with_latest_snapshot()

        if not books:
            console.print(
                '[yellow]No books tracked. Use "kdp-scout track add <ASIN>" '
                'to start.[/yellow]'
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
            rating = (f"{book['avg_rating']:.1f}"
                      if book['avg_rating'] else '-')
            daily_sales = (f"{book['estimated_daily_sales']:.1f}"
                          if book['estimated_daily_sales'] else '-')
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

    # ── Keyword Gap Analysis ──────────────────────────────────────

    def keyword_gaps(self, competitor_asin=None):
        """Show keyword gap opportunities from three sources.

        Enhanced gap analysis:
        1. Keywords where competitors rank but your books don't (from reverse ASIN data)
        2. Keywords where competitors rank higher than you (position comparison)
        3. Keywords from ads with high impressions but no orders (opportunity)

        Args:
            competitor_asin: Optional ASIN to focus gap analysis on.
        """
        has_ranking_data = False
        has_ads_data = self._ads_repo.get_search_term_count() > 0

        # Check for ranking data from reverse ASIN
        books = self._book_repo.get_all_books()
        own_books = [b for b in books if b['is_own']]
        competitor_books = [b for b in books if not b['is_own']]

        own_ids = [b['id'] for b in own_books]
        comp_ids = [b['id'] for b in competitor_books]

        if competitor_asin:
            comp_book = self._book_repo.find_by_asin(competitor_asin)
            if comp_book:
                comp_ids = [comp_book['id']]

        # Section 1: Competitor keywords you don't rank for
        if own_ids and comp_ids:
            gaps = self._ranking_repo.get_gaps(own_ids, comp_ids)
            if gaps:
                has_ranking_data = True
                table = Table(
                    title='Competitor Keywords You Don\'t Rank For',
                    show_lines=False,
                    expand=True,
                )
                table.add_column('#', style='dim', width=4, justify='right')
                table.add_column('Keyword', style='bold', ratio=3)
                table.add_column('Competitor', ratio=2)
                table.add_column('Their Pos', justify='center', width=10)
                table.add_column('Score', justify='right', width=7)
                table.add_column('Priority', width=12)

                for i, row in enumerate(gaps[:50], 1):
                    score = row['score'] or 0
                    position = row['competitor_position'] or 0

                    # Prioritize: high score + good competitor position
                    if position <= 5 and score >= 50:
                        priority = '[bold red]HIGH[/bold red]'
                    elif position <= 10 or score >= 25:
                        priority = '[yellow]MEDIUM[/yellow]'
                    else:
                        priority = '[dim]LOW[/dim]'

                    comp_title = row['competitor_title'] or row['competitor_asin']
                    if len(comp_title) > 30:
                        comp_title = comp_title[:27] + '...'

                    table.add_row(
                        str(i),
                        row['keyword'],
                        comp_title,
                        str(position) if position else '-',
                        f'{score:.0f}',
                        priority,
                    )

                console.print(table)
                console.print(
                    f'\n[dim]{len(gaps)} keyword gaps from competitor rankings[/dim]\n'
                )

        # Section 2: Keywords where competitors rank higher
        if own_ids and comp_ids:
            position_gaps = self._find_position_gaps(own_ids, comp_ids)
            if position_gaps:
                has_ranking_data = True
                table = Table(
                    title='Keywords Where Competitors Rank Higher',
                    show_lines=False,
                    expand=True,
                )
                table.add_column('#', style='dim', width=4, justify='right')
                table.add_column('Keyword', style='bold', ratio=3)
                table.add_column('Your Pos', justify='center', width=9)
                table.add_column('Their Pos', justify='center', width=10)
                table.add_column('Competitor', ratio=2)
                table.add_column('Gap', justify='center', width=6)

                for i, gap in enumerate(position_gaps[:30], 1):
                    diff = gap['your_position'] - gap['their_position']
                    if diff >= 5:
                        gap_str = f'[red]-{diff}[/red]'
                    elif diff >= 2:
                        gap_str = f'[yellow]-{diff}[/yellow]'
                    else:
                        gap_str = f'[dim]-{diff}[/dim]'

                    comp_title = gap['competitor_title'] or gap['competitor_asin']
                    if len(comp_title) > 30:
                        comp_title = comp_title[:27] + '...'

                    table.add_row(
                        str(i),
                        gap['keyword'],
                        str(gap['your_position']),
                        str(gap['their_position']),
                        comp_title,
                        gap_str,
                    )

                console.print(table)
                console.print(
                    f'\n[dim]{len(position_gaps)} keywords where competitors '
                    f'outrank you[/dim]\n'
                )

        # Section 3: Ads opportunity keywords (impressions but no orders)
        if has_ads_data:
            opportunities = self._ads_repo.get_opportunity_keywords()

            if opportunities:
                table = Table(
                    title='Ads Keywords: Impressions but No Orders',
                    show_lines=False,
                    expand=True,
                )
                table.add_column('#', style='dim', width=4, justify='right')
                table.add_column('Search Term', style='bold', ratio=3)
                table.add_column('Impressions', justify='right', width=12)
                table.add_column('Clicks', justify='right', width=8)
                table.add_column('Spend', justify='right', width=10)
                table.add_column('Action', width=20)

                for i, row in enumerate(opportunities[:50], 1):
                    impressions = _fmt_number(row['total_impressions'])
                    clicks = _fmt_number(row['total_clicks'])
                    spend = _fmt_price(row['total_spend'])

                    total_clicks = row['total_clicks'] or 0
                    total_impressions = row['total_impressions'] or 0

                    if total_clicks > 5 and total_impressions > 100:
                        action = '[red]Review listing[/red]'
                    elif total_impressions > 500 and total_clicks == 0:
                        action = '[yellow]Improve ad copy[/yellow]'
                    elif total_impressions < 50:
                        action = '[dim]Low data[/dim]'
                    else:
                        action = '[yellow]Monitor[/yellow]'

                    table.add_row(str(i), row['search_term'], impressions,
                                  clicks, spend, action)

                console.print(table)
                console.print(
                    f'\n[dim]{len(opportunities)} opportunity keywords from ads[/dim]\n'
                )

        # If no data at all
        if not has_ranking_data and not has_ads_data:
            console.print(
                '[yellow]No gap analysis data available.\n'
                'Run "kdp-scout reverse <ASIN>" to get ranking data, or\n'
                'use "kdp-scout import-ads <file>" to import ads data.[/yellow]'
            )

    def _find_position_gaps(self, own_book_ids, competitor_book_ids):
        """Find keywords where competitors rank higher than own books.

        Args:
            own_book_ids: List of own book IDs.
            competitor_book_ids: List of competitor book IDs.

        Returns:
            List of dicts with position comparison data,
            sorted by gap size descending.
        """
        from kdp_scout.db import get_connection

        conn = get_connection()
        try:
            own_placeholders = ','.join('?' * len(own_book_ids))
            comp_placeholders = ','.join('?' * len(competitor_book_ids))

            query = f"""
                SELECT k.keyword,
                       own_kr.rank_position as your_position,
                       comp_kr.rank_position as their_position,
                       b.title as competitor_title,
                       b.asin as competitor_asin
                FROM keyword_rankings own_kr
                JOIN keyword_rankings comp_kr
                    ON own_kr.keyword_id = comp_kr.keyword_id
                JOIN keywords k ON own_kr.keyword_id = k.id
                JOIN books b ON comp_kr.book_id = b.id
                WHERE own_kr.book_id IN ({own_placeholders})
                  AND comp_kr.book_id IN ({comp_placeholders})
                  AND comp_kr.rank_position < own_kr.rank_position
                ORDER BY (own_kr.rank_position - comp_kr.rank_position) DESC
            """
            params = list(own_book_ids) + list(competitor_book_ids)
            rows = conn.execute(query, params).fetchall()

            return [
                {
                    'keyword': row['keyword'],
                    'your_position': row['your_position'],
                    'their_position': row['their_position'],
                    'competitor_title': row['competitor_title'],
                    'competitor_asin': row['competitor_asin'],
                }
                for row in rows
            ]
        finally:
            conn.close()

    # ── Ads Performance Report ────────────────────────────────────

    def ads_performance(self):
        """Print ads search term performance report.

        Shows aggregated performance across all imported report dates,
        sorted by orders descending, then impressions descending.
        """
        if self._ads_repo.get_search_term_count() == 0:
            console.print(
                '[yellow]No ads data imported yet. '
                'Use "kdp-scout import-ads <file>" to import your '
                'Amazon Ads search term report first.[/yellow]'
            )
            return

        terms = self._ads_repo.get_aggregated_search_terms()

        if not terms:
            return

        table = Table(
            title='Amazon Ads - Search Term Performance',
            show_lines=False,
            expand=True,
        )
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Search Term', style='bold', ratio=3)
        table.add_column('Impressions', justify='right', width=12)
        table.add_column('Clicks', justify='right', width=8)
        table.add_column('CTR', justify='right', width=7)
        table.add_column('Spend', justify='right', width=9)
        table.add_column('Sales', justify='right', width=9)
        table.add_column('ACOS', justify='right', width=7)
        table.add_column('Orders', justify='right', width=8)

        total_spend = 0
        total_sales = 0
        total_orders = 0

        for i, term in enumerate(terms[:100], 1):
            impressions = _fmt_number(term['total_impressions'])
            clicks = _fmt_number(term['total_clicks'])
            spend = _fmt_price(term['total_spend'])
            sales = _fmt_price(term['total_sales'])
            orders = _fmt_number(term['total_orders'])

            ctr = (f"{term['avg_ctr'] * 100:.1f}%"
                   if term['avg_ctr'] else '-')

            acos_val = term['avg_acos']
            if acos_val is not None:
                acos_pct = acos_val * 100
                if acos_pct > 100:
                    acos_str = f'[red]{acos_pct:.0f}%[/red]'
                elif acos_pct > 50:
                    acos_str = f'[yellow]{acos_pct:.0f}%[/yellow]'
                else:
                    acos_str = f'[green]{acos_pct:.0f}%[/green]'
            else:
                acos_str = '-'

            total_spend += term['total_spend'] or 0
            total_sales += term['total_sales'] or 0
            total_orders += term['total_orders'] or 0

            table.add_row(
                str(i), term['search_term'], impressions, clicks,
                ctr, spend, sales, acos_str, orders,
            )

        console.print(table)

        # Summary
        overall_acos = (total_spend / total_sales * 100
                        if total_sales > 0 else 0)
        console.print(
            f'\n[bold]Totals:[/bold] Spend: ${total_spend:,.2f} | '
            f'Sales: ${total_sales:,.2f} | '
            f'Orders: {total_orders:,} | '
            f'ACOS: {overall_acos:.1f}%'
        )

    # ── Trend Report ──────────────────────────────────────────────

    def trend_report(self, days=30):
        """Show keyword metric changes over time.

        Compares the latest snapshot to the oldest snapshot within the
        date range for each keyword.

        Args:
            days: Number of days to look back.
        """
        keywords = self._kw_repo.get_keywords_with_latest_metrics(
            limit=100, min_score=0, order_by='score',
        )

        if not keywords:
            console.print(
                '[yellow]No keywords in database. '
                'Run "kdp-scout mine" first.[/yellow]'
            )
            return

        table = Table(
            title=f'Keyword Trends (Last {days} Days)',
            show_lines=False,
        )
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold', ratio=3)
        table.add_column('Score', justify='right', width=7)
        table.add_column('AC Pos Change', justify='center', width=14)
        table.add_column('Impressions Change', justify='center', width=18)
        table.add_column('Snapshots', justify='center', width=10)

        rows_with_changes = 0

        for i, kw in enumerate(keywords, 1):
            history = self._kw_repo.get_keyword_metrics_history(
                kw['id'], days=days,
            )

            if len(history) < 2:
                # Only one snapshot, no trend to show
                snapshots = str(len(history))
                score = f"{kw['score']:.0f}" if kw['score'] else '0'
                table.add_row(
                    str(i), kw['keyword'], score,
                    '[dim]--[/dim]', '[dim]--[/dim]', snapshots,
                )
                continue

            oldest = history[0]
            newest = history[-1]

            # Autocomplete position change
            old_pos = oldest['autocomplete_position']
            new_pos = newest['autocomplete_position']
            if old_pos and new_pos:
                delta = old_pos - new_pos  # positive = improved (lower pos)
                if delta > 0:
                    pos_change = f'[green]+{delta} (improved)[/green]'
                elif delta < 0:
                    pos_change = f'[red]{delta} (declined)[/red]'
                else:
                    pos_change = '[dim]unchanged[/dim]'
            else:
                pos_change = '[dim]--[/dim]'

            # Impressions change
            old_imp = oldest['impressions']
            new_imp = newest['impressions']
            if old_imp is not None and new_imp is not None:
                delta = new_imp - old_imp
                if delta > 0:
                    imp_change = f'[green]+{delta:,}[/green]'
                elif delta < 0:
                    imp_change = f'[red]{delta:,}[/red]'
                else:
                    imp_change = '[dim]unchanged[/dim]'
            else:
                imp_change = '[dim]--[/dim]'

            score = f"{kw['score']:.0f}" if kw['score'] else '0'
            snapshots = str(len(history))

            table.add_row(
                str(i), kw['keyword'], score,
                pos_change, imp_change, snapshots,
            )
            rows_with_changes += 1

        console.print(table)
        console.print(
            f'\n[dim]{len(keywords)} keywords analyzed over {days} days[/dim]'
        )

    # ── Export: Amazon Ads ────────────────────────────────────────

    def export_for_ads(self, min_score=0, output_format='csv') -> str:
        """Export keywords formatted for Amazon Ads campaign import.

        Generates a CSV with columns: Keyword, Match Type, Bid
        Bid is calculated from the keyword score tier.

        Args:
            min_score: Minimum score threshold for export.
            output_format: 'csv' (default).

        Returns:
            The CSV content as a string (also printed to stdout).
        """
        keywords = self._kw_repo.get_keywords_with_latest_metrics(
            limit=500, min_score=min_score, order_by='score',
        )

        if not keywords:
            console.print(
                '[yellow]No keywords meet the minimum score threshold. '
                'Run "kdp-scout score" first, or lower --min-score.[/yellow]',
                file=sys.stderr,
            )
            return ''

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Keyword', 'Match Type', 'Bid'])

        for kw in keywords:
            score = kw['score'] or 0
            bid = _score_to_bid(score)
            writer.writerow([kw['keyword'], 'broad', f'{bid:.2f}'])

        content = output.getvalue()
        print(content, end='')
        return content

    # ── Export: KDP Backend Keywords ──────────────────────────────

    def export_backend_keywords(self):
        """Generate optimized 7 backend keyword slots for KDP.

        Each slot has a 50-byte limit. The algorithm packs the highest-scoring
        keywords into 7 slots, avoiding word duplication across slots.

        Prints the 7 slots ready to copy-paste into KDP dashboard.
        """
        keywords = self._kw_repo.get_keywords_with_latest_metrics(
            limit=200, min_score=0, order_by='score',
        )

        if not keywords:
            console.print(
                '[yellow]No keywords in database. '
                'Run "kdp-scout mine" and "kdp-scout score" first.[/yellow]'
            )
            return

        # Build list of (keyword_text, score, individual_words)
        keyword_data = []
        for kw in keywords:
            text = kw['keyword'].strip()
            score = kw['score'] or 0
            words = text.split()
            keyword_data.append((text, score, words))

        # Greedy packing algorithm: only add NEW words from each keyword
        slots = [[] for _ in range(KDP_SLOT_COUNT)]
        slot_bytes = [0] * KDP_SLOT_COUNT
        used_words = set()  # Track all words used across all slots
        total_score = 0

        for text, score, words in keyword_data:
            # Find which words from this keyword are new
            new_words = [w for w in words if w.lower() not in used_words]
            if not new_words:
                continue  # Skip - all words already covered

            # Only add the new words (Amazon treats backend keywords as
            # a bag of words, so order doesn't matter)
            phrase_to_add = ' '.join(new_words)
            phrase_bytes = len(phrase_to_add.encode('utf-8'))

            # Try to fit in a slot
            placed = False
            for slot_idx in range(KDP_SLOT_COUNT):
                current_bytes = slot_bytes[slot_idx]
                separator_bytes = 1 if slots[slot_idx] else 0  # space separator
                needed = phrase_bytes + separator_bytes

                if current_bytes + needed <= KDP_SLOT_MAX_BYTES:
                    slots[slot_idx].append(phrase_to_add)
                    slot_bytes[slot_idx] += needed
                    for w in new_words:
                        used_words.add(w.lower())
                    total_score += score
                    placed = True
                    break

        # Display results
        console.print(
            Panel(
                '[bold]KDP Backend Keywords[/bold]\n'
                'Copy each slot into your KDP dashboard backend keywords.\n'
                'Each slot is within the 50-byte limit.',
                title='[bold cyan]KDP Backend Keywords Export[/bold cyan]',
                border_style='cyan',
            )
        )
        console.print()

        for i, slot in enumerate(slots, 1):
            content = ' '.join(slot)
            byte_count = len(content.encode('utf-8'))

            if content:
                bar_len = int(byte_count / KDP_SLOT_MAX_BYTES * 20)
                bar = '#' * bar_len + '-' * (20 - bar_len)

                if byte_count > 45:
                    byte_color = 'yellow'
                else:
                    byte_color = 'green'

                console.print(
                    f'[bold]Slot {i}:[/bold] [{byte_color}]'
                    f'{byte_count}/{KDP_SLOT_MAX_BYTES} bytes[/{byte_color}] '
                    f'[dim][{bar}][/dim]'
                )
                console.print(f'  {content}')
            else:
                console.print(f'[bold]Slot {i}:[/bold] [dim](empty)[/dim]')
            console.print()

        console.print(
            f'[bold]Total unique words:[/bold] {len(used_words)}'
        )
        console.print(
            f'[bold]Total score packed:[/bold] {total_score:.0f}'
        )


# ── Utility functions ─────────────────────────────────────────────


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


def _score_to_bid(score):
    """Convert a keyword score to a suggested bid amount.

    Args:
        score: Keyword composite score.

    Returns:
        Suggested bid in dollars.
    """
    for threshold, bid in BID_TIERS:
        if score >= threshold:
            return bid
    return BID_TIERS[-1][1]
