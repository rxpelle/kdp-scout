"""KDP Scout CLI entry point.

Provides the command-line interface using Click and Rich for
keyword research, competitor analysis, ads integration, and reporting.
"""

import sys
import json
import signal
import logging

import click
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn,
)
from rich.panel import Panel

from kdp_scout import __version__
from kdp_scout.config import Config, MARKETPLACES, get_marketplace
from kdp_scout.db import init_db

console = Console()

# Shared CLI option for marketplace selection
_marketplace_codes = list(MARKETPLACES.keys())


def _validate_marketplace(ctx, param, value):
    """Resolve and validate the marketplace, including env/config fallback."""
    try:
        get_marketplace(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--marketplace")
    return value


marketplace_option = click.option(
    '--marketplace', '-m',
    type=click.Choice(_marketplace_codes, case_sensitive=False),
    default=None,
    callback=_validate_marketplace,
    expose_value=True,
    is_eager=False,
    help=f'Amazon marketplace ({", ".join(_marketplace_codes)}). Default: MARKETPLACE env or "us".',
)


def handle_interrupt(signum, frame):
    """Handle keyboard interrupt gracefully."""
    console.print('\n[yellow]Interrupted. Partial results have been saved.[/yellow]')
    sys.exit(0)


signal.signal(signal.SIGINT, handle_interrupt)


@click.group()
@click.version_option(version=__version__, prog_name='kdp-scout')
def main():
    """KDP Scout - Amazon KDP keyword research and competitor analysis."""
    Config.setup_logging()


@main.command()
@click.argument('seed')
@click.option(
    '--depth',
    type=click.IntRange(1, 2),
    default=1,
    help='Mining depth: 1 = seed + a-z (27 queries), 2 = recursive expansion.',
)
@click.option(
    '--department',
    type=click.Choice(['kindle', 'books', 'all']),
    default='kindle',
    help='Amazon department to search.',
)
@marketplace_option
def mine(seed, depth, department, marketplace):
    """Mine keywords from Amazon autocomplete.

    SEED is the keyword to expand (e.g., "historical fiction").

    Examples:
        kdp-scout mine "historical fiction"
        kdp-scout mine "thriller" --depth 2
        kdp-scout mine "romance" --department books
        kdp-scout mine "ausgestorbene tiere" -m de
    """
    from kdp_scout.keyword_engine import mine_keywords
    from kdp_scout.config import get_marketplace

    mp = get_marketplace(marketplace)
    mp_label = marketplace or Config.MARKETPLACE

    console.print(
        Panel(
            f'[bold]Seed:[/bold] {seed}\n'
            f'[bold]Depth:[/bold] {depth}\n'
            f'[bold]Department:[/bold] {department}\n'
            f'[bold]Marketplace:[/bold] {mp_label} ({mp["domain"]})',
            title='[bold cyan]KDP Scout - Keyword Mining[/bold cyan]',
            border_style='cyan',
        )
    )

    expected_queries = 27 if depth == 1 else 27  # depth 2 total is unknown upfront

    with Progress(
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
        TextColumn('({task.completed}/{task.total})'),
        console=console,
    ) as progress:
        task = progress.add_task(
            f'Mining "{seed}"...', total=expected_queries
        )

        def on_progress(completed, total):
            progress.update(task, completed=completed, total=total)

        try:
            results = mine_keywords(
                seed,
                depth=depth,
                department=department,
                marketplace=marketplace,
                progress_callback=on_progress,
            )
        except KeyboardInterrupt:
            console.print(
                '\n[yellow]Mining interrupted. Partial results saved.[/yellow]'
            )
            return
        except Exception as e:
            console.print(f'\n[red]Error during mining: {e}[/red]')
            logging.getLogger(__name__).exception('Mining failed')
            return

    # Display results summary
    console.print()

    # Summary stats
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column('Label', style='bold')
    summary_table.add_column('Value', style='green')

    summary_table.add_row('Total keywords mined', str(results['total_mined']))
    summary_table.add_row('New keywords', str(results['new_count']))
    summary_table.add_row('Already in database', str(results['existing_count']))

    console.print(
        Panel(summary_table, title='[bold green]Results Summary[/bold green]', border_style='green')
    )

    # Top keywords table
    if results['keywords']:
        console.print()
        kw_table = Table(
            title=f'Top Keywords (showing up to 20)',
            show_lines=False,
        )
        kw_table.add_column('#', style='dim', width=4, justify='right')
        kw_table.add_column('Keyword', style='bold')
        kw_table.add_column('Position', justify='center', width=10)
        kw_table.add_column('Status', justify='center', width=10)

        # Sort by position and show top 20
        sorted_kws = sorted(results['keywords'], key=lambda x: x[1])
        for i, (kw, pos, is_new) in enumerate(sorted_kws[:20], 1):
            status = '[green]NEW[/green]' if is_new else '[dim]exists[/dim]'
            kw_table.add_row(str(i), kw, str(pos), status)

        console.print(kw_table)

    console.print()
    console.print(
        f'[dim]Database: {Config.get_db_path()}[/dim]'
    )


# -- Config command group --------------------------------------------------


@main.group()
def config():
    """View and manage configuration."""
    pass


@config.command('show')
def config_show():
    """Show current configuration."""
    cfg = Config.as_dict()

    table = Table(title='KDP Scout Configuration')
    table.add_column('Setting', style='bold cyan')
    table.add_column('Value')

    for key, value in cfg.items():
        table.add_row(key, str(value))

    console.print(table)


@config.command('init')
def config_init():
    """Initialize configuration and database."""
    console.print('[bold]Initializing KDP Scout...[/bold]')

    # Initialize database
    init_db()
    console.print(f'[green]Database created at {Config.get_db_path()}[/green]')

    # Check for .env file
    from pathlib import Path
    env_file = Path(__file__).parent.parent / '.env'
    if not env_file.exists():
        console.print(
            '[yellow]No .env file found. Copy .env.example to .env '
            'and configure your settings.[/yellow]'
        )
    else:
        console.print('[green].env file found[/green]')

    console.print('[bold green]Initialization complete![/bold green]')


# -- Track command group ---------------------------------------------------


@main.group()
def track():
    """Track and monitor competitor books."""
    pass


@track.command('add')
@click.argument('asin')
@click.option('--name', default=None, help='Display name for the book.')
@click.option('--own', is_flag=True, help='Mark as your own book.')
@marketplace_option
def track_add(asin, name, own, marketplace):
    """Add a book to tracking by ASIN.

    Scrapes the Amazon product page for initial data and begins tracking.

    Examples:
        kdp-scout track add B003K16PJW --name "The Name of the Rose"
        kdp-scout track add B08N5WRWNW --own --name "My Book Title"
        kdp-scout track add B0G5B1KZVC --own -m de
    """
    from kdp_scout.competitor_engine import CompetitorEngine
    from kdp_scout.collectors.product_scraper import CaptchaDetected
    from kdp_scout.collectors.bsr_model import sales_velocity_label

    engine = CompetitorEngine(marketplace=marketplace)
    try:
        console.print(f'\n[bold]Adding book:[/bold] {asin.upper()}')
        if name:
            console.print(f'[bold]Name:[/bold] {name}')
        if own:
            console.print(f'[bold]Type:[/bold] [green]Your book[/green]')
        console.print()

        with console.status('[bold cyan]Scraping Amazon product page...'):
            result = engine.add_book(asin, name=name, is_own=own)

        if result is None:
            console.print('[red]Failed to add book. Scraping returned no data.[/red]')
            return

        # Build the info panel
        scraped = result.get('scraped') or {}
        snapshot = result.get('snapshot') or {}
        title = result.get('title') or 'Unknown'
        author = result.get('author') or 'Unknown'

        lines = [
            f'[bold]Title:[/bold] {title}',
            f'[bold]Author:[/bold] {author}',
            f'[bold]ASIN:[/bold] {result["asin"]}',
        ]

        bsr = snapshot.get('bsr_overall')
        if bsr:
            lines.append(f'[bold]BSR (Overall):[/bold] #{bsr:,}')

        # Category BSR
        bsr_cats = snapshot.get('bsr_categories', {})
        if bsr_cats:
            for cat, rank in bsr_cats.items():
                lines.append(f'  [dim]#{rank:,} in {cat}[/dim]')

        price_k = snapshot.get('price_kindle')
        price_p = snapshot.get('price_paperback')
        if price_k:
            lines.append(f'[bold]Kindle Price:[/bold] ${price_k:.2f}')
        if price_p:
            lines.append(f'[bold]Paperback Price:[/bold] ${price_p:.2f}')

        reviews = snapshot.get('review_count')
        rating = snapshot.get('avg_rating')
        if reviews is not None:
            lines.append(f'[bold]Reviews:[/bold] {reviews:,}')
        if rating is not None:
            lines.append(f'[bold]Rating:[/bold] {rating:.1f}/5.0')

        pages = snapshot.get('page_count')
        if pages:
            lines.append(f'[bold]Pages:[/bold] {pages}')

        daily = snapshot.get('estimated_daily_sales')
        monthly = snapshot.get('estimated_monthly_revenue')
        if daily is not None:
            velocity = sales_velocity_label(daily)
            lines.append(f'[bold]Est. Daily Sales:[/bold] {daily:.1f} ({velocity})')
        if monthly is not None:
            lines.append(f'[bold]Est. Monthly Revenue:[/bold] ${monthly:,.2f}')

        pub_date = scraped.get('publication_date')
        if pub_date:
            lines.append(f'[bold]Published:[/bold] {pub_date}')

        status = '[green]NEW - Added to tracking[/green]' if result['is_new'] else '[yellow]Already tracked - Updated[/yellow]'
        lines.append(f'\n[bold]Status:[/bold] {status}')

        border = 'green' if own else 'cyan'
        panel_title = '[bold green]Your Book[/bold green]' if own else '[bold cyan]Competitor Book[/bold cyan]'

        console.print(Panel(
            '\n'.join(lines),
            title=panel_title,
            border_style=border,
        ))

    except CaptchaDetected:
        console.print(
            '[red bold]CAPTCHA detected![/red bold] Amazon is blocking scraping.\n'
            '[yellow]Try again in a few minutes, or configure a proxy in .env.[/yellow]'
        )
    except Exception as e:
        console.print(f'[red]Error adding book: {e}[/red]')
        logging.getLogger(__name__).exception('Failed to add book')
    finally:
        engine.close()


@track.command('remove')
@click.argument('asin')
def track_remove(asin):
    """Remove a book from tracking.

    Example:
        kdp-scout track remove B003K16PJW
    """
    from kdp_scout.competitor_engine import CompetitorEngine

    engine = CompetitorEngine()
    try:
        removed = engine.remove_book(asin)
        if removed:
            console.print(f'[green]Removed {asin.upper()} from tracking.[/green]')
        else:
            console.print(f'[yellow]Book {asin.upper()} not found in tracking.[/yellow]')
    finally:
        engine.close()


@track.command('list')
def track_list():
    """List all tracked books with latest snapshot data."""
    from kdp_scout.competitor_engine import CompetitorEngine

    engine = CompetitorEngine()
    try:
        books = engine.list_books()

        if not books:
            console.print(
                '[yellow]No books tracked yet. Use "kdp-scout track add <ASIN>" to start.[/yellow]'
            )
            return

        table = Table(
            title='Tracked Books',
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
        table.add_column('Updated', width=10)

        for book in books:
            is_own = book['is_own']
            style = 'bold green' if is_own else ''

            bsr = f"{int(book['bsr_overall']):,}" if book['bsr_overall'] else '-'
            price = f"${book['price_kindle']:.2f}" if book['price_kindle'] and book['price_kindle'] > 0 else '-'
            reviews = f"{int(book['review_count']):,}" if book['review_count'] else '-'
            rating = f"{book['avg_rating']:.1f}" if book['avg_rating'] else '-'
            daily = f"{book['estimated_daily_sales']:.1f}" if book['estimated_daily_sales'] else '-'
            monthly = f"${book['estimated_monthly_revenue']:,.0f}" if book['estimated_monthly_revenue'] else '-'
            updated = (book['last_snapshot_date'] or '')[:10] or '-'

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
                daily,
                monthly,
                updated,
                style=style,
            )

        console.print(table)
        console.print(f'\n[dim]{len(books)} book(s) tracked[/dim]')

    finally:
        engine.close()


@track.command('snapshot')
@click.option('--quiet', is_flag=True, help='Suppress output (for cron jobs).')
@marketplace_option
def track_snapshot(quiet, marketplace):
    """Take a fresh snapshot of all tracked books.

    Scrapes current data for every tracked book and stores BSR,
    price, review, and sales estimate snapshots.

    Example:
        kdp-scout track snapshot
        kdp-scout track snapshot --quiet
    """
    from kdp_scout.competitor_engine import CompetitorEngine

    engine = CompetitorEngine(marketplace=marketplace)
    try:
        books = engine.list_books()
        if not books:
            if not quiet:
                console.print('[yellow]No books tracked.[/yellow]')
            return

        if not quiet:
            console.print(
                f'\n[bold cyan]Taking snapshots of {len(books)} tracked book(s)...[/bold cyan]\n'
            )

        results = []
        if quiet:
            results = engine.take_snapshot()
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn('[progress.description]{task.description}'),
                BarColumn(),
                TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
                TextColumn('({task.completed}/{task.total})'),
                console=console,
            ) as progress:
                task = progress.add_task('Snapshotting...', total=len(books))

                for book in books:
                    progress.update(task, description=f'Scraping {book["asin"]}...')
                    book_results = engine.take_snapshot(asin=book['asin'])
                    results.extend(book_results)
                    progress.advance(task)

        if quiet:
            return

        # Display results
        console.print()
        success_count = sum(1 for r in results if r['success'])
        fail_count = len(results) - success_count

        for result in results:
            if result['success']:
                title = result['title'] or 'Unknown'
                snapshot = result.get('snapshot', {})
                changes = result.get('changes', {})

                bsr = snapshot.get('bsr_overall')
                bsr_str = f'BSR #{bsr:,}' if bsr else 'BSR unknown'

                parts = [f'[green]OK[/green] {title} ({result["asin"]}) - {bsr_str}']

                # Show changes
                for field, change in changes.items():
                    old_val = change['old']
                    new_val = change['new']
                    direction = change['direction']

                    if direction == 'improved':
                        color = 'green'
                        arrow = 'v' if field == 'BSR' else '^'
                    elif direction == 'declined':
                        color = 'red'
                        arrow = '^' if field == 'BSR' else 'v'
                    else:
                        color = 'dim'
                        arrow = '='

                    if isinstance(old_val, float):
                        parts.append(f'  [{color}]{arrow} {field}: {old_val:.2f} -> {new_val:.2f}[/{color}]')
                    else:
                        parts.append(f'  [{color}]{arrow} {field}: {old_val:,} -> {new_val:,}[/{color}]')

                console.print('\n'.join(parts))
            else:
                console.print(
                    f'[red]FAIL[/red] {result.get("title", "Unknown")} '
                    f'({result["asin"]}): {result.get("error", "Unknown error")}'
                )

        console.print()
        summary = f'[bold]Snapshot complete:[/bold] {success_count} succeeded'
        if fail_count:
            summary += f', [red]{fail_count} failed[/red]'
        console.print(summary)

    finally:
        engine.close()


@track.command('compare')
def track_compare():
    """Side-by-side comparison of all tracked books."""
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.competitor_summary()
    finally:
        engine.close()


# -- Import Ads command ----------------------------------------------------


@main.command('import-ads')
@click.argument('filepath', type=click.Path(exists=True))
@click.option(
    '--campaign',
    default=None,
    help='Filter by campaign name (substring match).',
)
def import_ads(filepath, campaign):
    """Import Amazon Ads search term report CSV.

    FILEPATH is the path to the exported CSV file from Amazon Ads console.

    Examples:
        kdp-scout import-ads search-terms-report.csv
        kdp-scout import-ads report.csv --campaign "My Campaign"
    """
    from kdp_scout.collectors.ads_importer import AdsImporter

    console.print(
        Panel(
            f'[bold]File:[/bold] {filepath}\n'
            f'[bold]Campaign filter:[/bold] {campaign or "(all campaigns)"}',
            title='[bold cyan]Amazon Ads Import[/bold cyan]',
            border_style='cyan',
        )
    )

    importer = AdsImporter()
    try:
        with console.status('[bold cyan]Importing search term report...'):
            result = importer.import_csv(filepath, campaign_filter=campaign)

        # Display results
        summary_table = Table(show_header=False, box=None, padding=(0, 2))
        summary_table.add_column('Label', style='bold')
        summary_table.add_column('Value', style='green')

        summary_table.add_row('Search terms imported', str(result['imported']))
        summary_table.add_row('Rows skipped', str(result['skipped']))
        summary_table.add_row('Keywords enriched', str(result['keywords_enriched']))

        console.print(
            Panel(
                summary_table,
                title='[bold green]Import Summary[/bold green]',
                border_style='green',
            )
        )

        if result['keywords_enriched'] > 0:
            console.print(
                '\n[dim]Tip: Run "kdp-scout score" to recalculate keyword '
                'scores with the new ads data.[/dim]'
            )

    except FileNotFoundError as e:
        console.print(f'[red]File not found: {e}[/red]')
    except ValueError as e:
        console.print(f'[red]Invalid file format: {e}[/red]')
    except Exception as e:
        console.print(f'[red]Error importing: {e}[/red]')
        logging.getLogger(__name__).exception('Ads import failed')
    finally:
        importer.close()


# -- Score command ---------------------------------------------------------


@main.command('score')
@click.option(
    '--recalculate',
    is_flag=True,
    help='Force recalculation of all scores.',
)
def score(recalculate):
    """Score all keywords based on available signals.

    Combines autocomplete position, competition data, and ads performance
    into a composite score for each keyword.

    Examples:
        kdp-scout score
        kdp-scout score --recalculate
    """
    from kdp_scout.keyword_engine import KeywordScorer

    scorer = KeywordScorer()
    try:
        label = 'Rescoring all keywords...' if recalculate else 'Scoring keywords...'
        with console.status(f'[bold cyan]{label}'):
            count = scorer.score_all_keywords(recalculate=recalculate)

        console.print(
            f'[bold green]Scored {count} keywords[/bold green]\n'
        )

        # Show top 10 preview
        top = scorer.get_top_keywords(limit=10, min_score=0)
        if top:
            table = Table(
                title='Top 10 Keywords by Score',
                show_lines=False,
            )
            table.add_column('#', style='dim', width=4, justify='right')
            table.add_column('Keyword', style='bold', ratio=3)
            table.add_column('Score', justify='right', width=7,
                             style='bold cyan')
            table.add_column('AC Pos', justify='center', width=7)
            table.add_column('Impressions', justify='right', width=12)
            table.add_column('Orders', justify='right', width=8)

            for i, kw in enumerate(top, 1):
                pos = (str(kw['autocomplete_position'])
                       if kw['autocomplete_position'] else '-')
                imp = (f"{kw['impressions']:,}"
                       if kw['impressions'] else '-')
                orders = (str(kw['orders'])
                          if kw['orders'] else '-')
                score_val = f"{kw['score']:.0f}" if kw['score'] else '0'

                table.add_row(str(i), kw['keyword'], score_val,
                              pos, imp, orders)

            console.print(table)

        console.print(
            '\n[dim]Run "kdp-scout report keywords" for the full report.[/dim]'
        )

    finally:
        scorer.close()


@main.command('explain')
@click.argument('keyword')
def explain(keyword):
    """Explain the score breakdown for a keyword.

    Shows each scoring component with raw value, normalized score (0-1),
    weight, and weighted contribution to the final 0-100 score.

    Examples:
        kdp-scout explain "historical fiction"
        kdp-scout explain "thriller books"
    """
    from kdp_scout.keyword_engine import KeywordScorer
    from kdp_scout.db import KeywordRepository

    repo = KeywordRepository()
    scorer = KeywordScorer()
    try:
        kw_row = repo.find_by_keyword(keyword)
        if kw_row is None:
            console.print(
                f'[red]Keyword "{keyword}" not found in database.[/red]'
            )
            return

        result = scorer.score_keyword_detailed(kw_row['id'])

        # Build the breakdown table
        table = Table(
            title=f'Score Breakdown: "{keyword}"',
            show_lines=True,
            expand=True,
        )
        table.add_column('Component', style='bold', width=20)
        table.add_column('Raw Value', justify='right', width=18)
        table.add_column('Normalized', justify='right', width=10)
        table.add_column('Weight', justify='right', width=8)
        table.add_column('Weighted', justify='right', width=8)
        table.add_column('Bar', width=22)

        component_order = [
            'autocomplete', 'competition', 'bsr_demand',
            'ads_impressions', 'ads_orders', 'ads_profitability',
            'search_volume', 'commercial_value', 'click_through_rate',
            'own_ranking',
        ]

        for name in component_order:
            comp = result['components'][name]
            raw = comp['description']
            norm_str = f"{comp['score']:.2f}"
            weight_str = f"{comp['weight']:.2f}"
            weighted_str = f"{comp['weighted']:.1f}"

            # Visual bar (20 chars wide)
            bar_len = int(comp['score'] * 20)
            bar = '[green]' + '#' * bar_len + '[/green]' + '[dim]' + '-' * (20 - bar_len) + '[/dim]'

            # Color the normalized score
            if comp['score'] >= 0.7:
                norm_display = f'[green]{norm_str}[/green]'
            elif comp['score'] >= 0.3:
                norm_display = f'[yellow]{norm_str}[/yellow]'
            elif comp['score'] > 0:
                norm_display = f'[dim]{norm_str}[/dim]'
            else:
                norm_display = f'[dim]0.00[/dim]'

            display_name = name.replace('_', ' ').title()

            table.add_row(
                display_name, raw, norm_display,
                weight_str, weighted_str, bar,
            )

        console.print()
        console.print(table)

        # Total score panel
        total = result['total']
        if total >= 75:
            total_style = 'bold green'
        elif total >= 50:
            total_style = 'green'
        elif total >= 25:
            total_style = 'yellow'
        else:
            total_style = 'dim'

        console.print(
            Panel(
                f'[{total_style}]{total:.1f} / 100[/{total_style}]',
                title='[bold]Total Score[/bold]',
                border_style='cyan',
                expand=False,
            )
        )
        console.print()

    finally:
        repo.close()
        scorer.close()


# -- Report command group --------------------------------------------------


@main.group()
def report():
    """Generate analysis reports."""
    pass


@report.command('keywords')
@click.option('--limit', default=50, help='Maximum keywords to display.')
@click.option('--min-score', default=0, type=float,
              help='Minimum score threshold.')
@click.option('--format', 'output_format',
              type=click.Choice(['table', 'csv', 'json']),
              default='table', help='Output format.')
def report_keywords(limit, min_score, output_format):
    """Show top keywords ranked by score.

    Examples:
        kdp-scout report keywords
        kdp-scout report keywords --limit 100 --min-score 50
        kdp-scout report keywords --format csv > keywords.csv
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.keyword_summary(
            limit=limit, min_score=min_score, output_format=output_format,
        )
    finally:
        engine.close()


@report.command('competitors')
def report_competitors():
    """Show competitor comparison report.

    Example:
        kdp-scout report competitors
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.competitor_summary()
    finally:
        engine.close()


@report.command('ads')
def report_ads():
    """Show Amazon Ads search term performance report.

    Displays aggregated performance data from imported search term reports.

    Example:
        kdp-scout report ads
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.ads_performance()
    finally:
        engine.close()


@report.command('gaps')
def report_gaps():
    """Show keyword gap analysis.

    Identifies keywords where you get impressions but no orders,
    indicating potential optimization opportunities.

    Example:
        kdp-scout report gaps
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.keyword_gaps()
    finally:
        engine.close()


@report.command('trends')
@click.option('--days', default=30, help='Number of days to look back.')
def report_trends(days):
    """Show keyword metric changes over time.

    Example:
        kdp-scout report trends
        kdp-scout report trends --days 7
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.trend_report(days=days)
    finally:
        engine.close()


# -- Export command group --------------------------------------------------


@main.group()
def export():
    """Export keywords for Amazon Ads and KDP."""
    pass


@export.command('ads')
@click.option('--min-score', default=0, type=float,
              help='Minimum keyword score to include.')
@click.option('--format', 'output_format',
              type=click.Choice(['csv']),
              default='csv', help='Output format.')
def export_ads(min_score, output_format):
    """Export keywords formatted for Amazon Ads campaign import.

    Outputs CSV to stdout for easy piping to a file.

    Examples:
        kdp-scout export ads
        kdp-scout export ads --min-score 50 > high-value-keywords.csv
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.export_for_ads(min_score=min_score, output_format=output_format)
    finally:
        engine.close()


@export.command('backend')
def export_backend():
    """Generate optimized KDP backend keyword slots.

    Packs the highest-scoring keywords into 7 slots of 50 bytes each,
    ready to copy-paste into the KDP dashboard.

    Example:
        kdp-scout export backend
    """
    from kdp_scout.reporting import ReportingEngine

    engine = ReportingEngine()
    try:
        engine.export_backend_keywords()
    finally:
        engine.close()


# -- Reverse ASIN command --------------------------------------------------


@main.command('reverse')
@click.argument('asin')
@click.option(
    '--method',
    type=click.Choice(['probe', 'dataforseo', 'auto']),
    default='auto',
    help='Lookup method: probe (free), dataforseo (paid), or auto.',
)
@click.option(
    '--top',
    'top_n',
    type=int,
    default=None,
    help='Only check top N keywords by score (speeds up probing).',
)
@marketplace_option
def reverse(asin, method, top_n, marketplace):
    """Reverse ASIN lookup: find keywords a book ranks for.

    ASIN is the Amazon ASIN to look up (e.g., B003K16PJW).

    The 'probe' method searches Amazon for each keyword in your database
    and checks if the ASIN appears in results (free, but slow ~2s/keyword).

    The 'dataforseo' method uses the DataForSEO API (fast, but costs ~$0.01).

    Examples:
        kdp-scout reverse B003K16PJW
        kdp-scout reverse B003K16PJW --method probe --top 50
        kdp-scout reverse B08N5WRWNW --method dataforseo
    """
    from kdp_scout.keyword_engine import ReverseASIN

    engine = ReverseASIN(marketplace=marketplace)
    try:
        # Determine method display
        if method == 'auto':
            from kdp_scout.collectors.dataforseo import DataForSEOCollector
            dfs = DataForSEOCollector()
            actual_method = 'dataforseo' if dfs.is_available() else 'probe'
        else:
            actual_method = method

        panel_lines = [
            f'[bold]ASIN:[/bold] {asin.upper()}',
            f'[bold]Method:[/bold] {actual_method}',
        ]
        if top_n:
            panel_lines.append(f'[bold]Keywords to check:[/bold] {top_n}')

        if actual_method == 'probe':
            from kdp_scout.db import KeywordRepository, init_db
            init_db()
            repo = KeywordRepository()
            try:
                total_kws = len(repo.get_all_keywords(active_only=True))
            finally:
                repo.close()
            check_count = min(top_n, total_kws) if top_n else total_kws
            est_seconds = check_count * 2.5  # ~2.5s per keyword with rate limiting
            est_minutes = est_seconds / 60
            panel_lines.append(
                f'[bold]Keywords in DB:[/bold] {total_kws}'
            )
            panel_lines.append(
                f'[bold]Estimated time:[/bold] ~{est_minutes:.1f} minutes '
                f'({check_count} keywords x 2.5s)'
            )

        console.print(
            Panel(
                '\n'.join(panel_lines),
                title='[bold cyan]Reverse ASIN Lookup[/bold cyan]',
                border_style='cyan',
            )
        )
        console.print()

        results = []

        if actual_method == 'probe':
            with Progress(
                SpinnerColumn(),
                TextColumn('[progress.description]{task.description}'),
                BarColumn(),
                TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
                TextColumn('({task.completed}/{task.total})'),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    'Probing...', total=check_count
                )

                found_count = [0]

                def on_progress(completed, total, found, keyword):
                    found_count[0] = found
                    short_kw = keyword[:30] + '...' if len(keyword) > 30 else keyword
                    progress.update(
                        task,
                        completed=completed,
                        total=total,
                        description=f'Probing: "{short_kw}" (found: {found})',
                    )

                try:
                    results = engine.reverse_asin_probe(
                        asin, top_n=top_n, method='probe',
                        progress_callback=on_progress,
                    )
                except KeyboardInterrupt:
                    console.print(
                        '\n[yellow]Interrupted. Partial results saved.[/yellow]'
                    )
        else:
            with console.status('[bold cyan]Querying DataForSEO API...'):
                results = engine.reverse_asin_probe(
                    asin, top_n=top_n, method='dataforseo',
                )

        # Display results
        console.print()

        if not results:
            console.print(
                f'[yellow]No rankings found for {asin.upper()}.[/yellow]\n'
                '[dim]The book may not appear in the first page of results '
                'for any of the keywords in your database.[/dim]'
            )
            return

        # Sort by position
        results.sort(key=lambda x: x['position'])

        table = Table(
            title=f'Keywords Ranking for {asin.upper()}',
            show_lines=False,
        )
        table.add_column('#', style='dim', width=4, justify='right')
        table.add_column('Keyword', style='bold', ratio=3)
        table.add_column('Position', justify='center', width=10)
        table.add_column('Source', justify='center', width=12)
        table.add_column('Date', width=12)

        if any('search_volume' in r for r in results):
            table.add_column('Search Vol', justify='right', width=11)

        for i, result in enumerate(results, 1):
            pos = result['position']
            if pos <= 3:
                pos_str = f'[bold green]{pos}[/bold green]'
            elif pos <= 8:
                pos_str = f'[green]{pos}[/green]'
            elif pos <= 12:
                pos_str = f'[yellow]{pos}[/yellow]'
            else:
                pos_str = str(pos)

            row = [
                str(i),
                result['keyword'],
                pos_str,
                result['source'],
                result['snapshot_date'],
            ]

            if any('search_volume' in r for r in results):
                vol = result.get('search_volume', 0)
                row.append(f'{vol:,}' if vol else '-')

            table.add_row(*row)

        console.print(table)

        # Summary
        console.print(
            f'\n[bold green]{len(results)} keywords found[/bold green] '
            f'for {asin.upper()}'
        )

        if actual_method == 'dataforseo':
            from kdp_scout.collectors.dataforseo import DataForSEOCollector
            dfs = DataForSEOCollector()
            console.print(
                f'[dim]Estimated DataForSEO spend: '
                f'${dfs.get_estimated_spend():.4f}[/dim]'
            )

        console.print(
            f'[dim]Results stored in database. '
            f'Run "kdp-scout report gaps" for gap analysis.[/dim]'
        )

    except Exception as e:
        console.print(f'[red]Error during reverse ASIN lookup: {e}[/red]')
        logging.getLogger(__name__).exception('Reverse ASIN failed')
    finally:
        engine.close()


# -- Discover command ------------------------------------------------------


@main.command('discover')
@click.argument('asin')
@click.option(
    '--top',
    'top_n',
    type=int,
    default=200,
    help='Check top N keywords for reverse ASIN (default 200).',
)
@marketplace_option
def discover(asin, top_n, marketplace):
    """Discover keywords and competitors for a book.

    Convenience command that:
    1. Reverse ASIN on the given book
    2. If DataForSEO is available, find product competitors
    3. Show keyword overlap and unique keywords per book

    ASIN is the Amazon ASIN to discover (e.g., B003K16PJW).

    Examples:
        kdp-scout discover B003K16PJW
        kdp-scout discover B003K16PJW --top 100
    """
    from kdp_scout.keyword_engine import ReverseASIN
    from kdp_scout.collectors.dataforseo import DataForSEOCollector

    engine = ReverseASIN(marketplace=marketplace)
    dfs = DataForSEOCollector()

    try:
        console.print(
            Panel(
                f'[bold]ASIN:[/bold] {asin.upper()}\n'
                f'[bold]Top keywords:[/bold] {top_n}\n'
                f'[bold]DataForSEO:[/bold] '
                f'{"Available" if dfs.is_available() else "Not configured (using probe)"}',
                title='[bold cyan]Discovery Mode[/bold cyan]',
                border_style='cyan',
            )
        )
        console.print()

        # Step 1: Reverse ASIN on the target book
        console.print('[bold]Step 1:[/bold] Reverse ASIN lookup...\n')

        method = 'dataforseo' if dfs.is_available() else 'probe'

        if method == 'probe':
            with Progress(
                SpinnerColumn(),
                TextColumn('[progress.description]{task.description}'),
                BarColumn(),
                TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
                TextColumn('({task.completed}/{task.total})'),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task('Probing...', total=top_n)

                def on_progress(completed, total, found, keyword):
                    short_kw = keyword[:30] + '...' if len(keyword) > 30 else keyword
                    progress.update(
                        task,
                        completed=completed,
                        total=total,
                        description=f'Probing: "{short_kw}" (found: {found})',
                    )

                main_results = engine.reverse_asin_probe(
                    asin, top_n=top_n, method='probe',
                    progress_callback=on_progress,
                )
        else:
            with console.status('[bold cyan]Querying DataForSEO...'):
                main_results = engine.reverse_asin_probe(
                    asin, top_n=top_n, method='dataforseo',
                )

        console.print(
            f'[green]Found {len(main_results)} keywords for {asin.upper()}[/green]\n'
        )

        # Step 2: Find competitors (DataForSEO only)
        competitors = []
        if dfs.is_available():
            console.print('[bold]Step 2:[/bold] Finding product competitors...\n')
            with console.status('[bold cyan]Querying DataForSEO for competitors...'):
                competitors = dfs.product_competitors(asin)

            if competitors:
                table = Table(
                    title='Product Competitors',
                    show_lines=False,
                )
                table.add_column('#', style='dim', width=4, justify='right')
                table.add_column('ASIN', width=12)
                table.add_column('Title', ratio=3)
                table.add_column('Common Keywords', justify='right', width=16)

                for i, comp in enumerate(competitors[:10], 1):
                    title = comp['title'] or 'Unknown'
                    if len(title) > 50:
                        title = title[:47] + '...'
                    table.add_row(
                        str(i),
                        comp['asin'],
                        title,
                        str(comp['common_keywords']),
                    )

                console.print(table)
                console.print()
            else:
                console.print('[yellow]No competitors found via API.[/yellow]\n')
        else:
            console.print(
                '[dim]Step 2: Skipped competitor discovery '
                '(requires DataForSEO API)[/dim]\n'
            )

        # Summary
        summary_lines = [
            f'[bold]Target ASIN:[/bold] {asin.upper()}',
            f'[bold]Keywords found:[/bold] {len(main_results)}',
        ]
        if competitors:
            summary_lines.append(
                f'[bold]Competitors found:[/bold] {len(competitors)}'
            )
        if dfs.is_available():
            summary_lines.append(
                f'[bold]Estimated API spend:[/bold] ${dfs.get_estimated_spend():.4f}'
            )

        console.print(
            Panel(
                '\n'.join(summary_lines),
                title='[bold green]Discovery Complete[/bold green]',
                border_style='green',
            )
        )

        console.print(
            '\n[dim]Run "kdp-scout report gaps" to see keyword gap analysis.[/dim]'
        )

    except Exception as e:
        console.print(f'[red]Error during discovery: {e}[/red]')
        logging.getLogger(__name__).exception('Discovery failed')
    finally:
        engine.close()


# -- Trending command ------------------------------------------------------


@main.command('trending')
@click.option(
    '--source',
    type=click.Choice(['bestsellers', 'google', 'both']),
    default='both',
    help='Discovery source: bestsellers, google suggest, or both.',
)
@click.option(
    '--list-type',
    type=click.Choice(['kindle', 'kindle_free', 'kindle_new', 'kindle_movers']),
    default='kindle',
    help='Bestseller list to scrape.',
)
@click.option(
    '--limit',
    default=50,
    type=int,
    help='Maximum keywords to display.',
)
@click.option(
    '--save/--no-save',
    default=True,
    help='Save discovered keywords to database.',
)
@marketplace_option
def trending(source, list_type, limit, save, marketplace):
    """Discover trending keywords without a seed phrase.

    Finds popular keywords by scraping Amazon bestseller pages
    and/or querying Google suggest with book-related patterns.

    No seed keyword required - this automatically discovers what's
    trending in the Kindle marketplace.

    Examples:
        kdp-scout trending
        kdp-scout trending --source bestsellers --list-type kindle_movers
        kdp-scout trending --source google --limit 100
        kdp-scout trending --no-save
        kdp-scout trending -m de
    """
    from kdp_scout.collectors.trending import (
        scrape_bestseller_keywords, discover_trending_keywords,
    )
    from kdp_scout.keyword_engine import mine_keywords
    from kdp_scout.db import KeywordRepository, init_db
    from kdp_scout.config import get_marketplace

    mp = get_marketplace(marketplace)
    mp_label = marketplace or Config.MARKETPLACE

    console.print(
        Panel(
            f'[bold]Source:[/bold] {source}\n'
            f'[bold]Bestseller list:[/bold] {list_type}\n'
            f'[bold]Marketplace:[/bold] {mp_label} ({mp["domain"]})\n'
            f'[bold]Save to DB:[/bold] {"Yes" if save else "No"}',
            title='[bold cyan]KDP Scout - Trending Discovery[/bold cyan]',
            border_style='cyan',
        )
    )
    console.print()

    all_keywords = {}

    # Bestseller scraping
    if source in ('bestsellers', 'both'):
        console.print('[bold]Phase 1:[/bold] Scraping Amazon bestseller page...\n')

        with Progress(
            SpinnerColumn(),
            TextColumn('[progress.description]{task.description}'),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f'Scraping {list_type} bestsellers...', total=1)

            try:
                bs_results = scrape_bestseller_keywords(
                    list_type=list_type,
                    marketplace=marketplace,
                    progress_callback=lambda c, t: progress.update(task, completed=c, total=t),
                )
            except Exception as e:
                console.print(f'[red]Error scraping bestsellers: {e}[/red]')
                bs_results = []

        for kw, info in bs_results:
            if kw not in all_keywords:
                all_keywords[kw] = {'source': 'bestseller', 'info': info}

        console.print(
            f'  [green]{len(bs_results)} keywords from bestsellers[/green]\n'
        )

    # Google suggest trending
    if source in ('google', 'both'):
        console.print('[bold]Phase 2:[/bold] Discovering trending topics via Google suggest...\n')

        with Progress(
            SpinnerColumn(),
            TextColumn('[progress.description]{task.description}'),
            BarColumn(),
            TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
            TextColumn('({task.completed}/{task.total})'),
            console=console,
        ) as progress:
            task = progress.add_task('Querying Google suggest...', total=84)

            try:
                gs_results = discover_trending_keywords(
                    marketplace=marketplace,
                    progress_callback=lambda c, t: progress.update(task, completed=c, total=t),
                )
            except Exception as e:
                console.print(f'[red]Error querying Google suggest: {e}[/red]')
                gs_results = []

        for kw, pos in gs_results:
            if kw not in all_keywords:
                all_keywords[kw] = {'source': 'google_suggest', 'position': pos}

        console.print(
            f'  [green]{len(gs_results)} keywords from Google suggest[/green]\n'
        )

    if not all_keywords:
        console.print('[yellow]No keywords discovered. Try again later or use a different source.[/yellow]')
        return

    # Save to database
    saved_count = 0
    if save:
        init_db()
        repo = KeywordRepository()
        try:
            for kw, meta in all_keywords.items():
                keyword_id, is_new = repo.upsert_keyword(
                    kw, source=meta['source'], category='trending',
                )
                pos = meta.get('position')
                if pos:
                    repo.add_metric(keyword_id, autocomplete_position=pos)
                if is_new:
                    saved_count += 1
        finally:
            repo.close()

    # Display results
    table = Table(
        title=f'Trending Keywords ({len(all_keywords)} discovered)',
        show_lines=False,
    )
    table.add_column('#', style='dim', width=4, justify='right')
    table.add_column('Keyword', style='bold', min_width=25)
    table.add_column('Source', justify='center', width=16)

    for i, (kw, meta) in enumerate(list(all_keywords.items())[:limit], 1):
        source_label = meta['source'].replace('_', ' ').title()
        table.add_row(str(i), kw, source_label)

    console.print(table)

    # Summary
    console.print()
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column('Label', style='bold')
    summary_table.add_column('Value', style='green')
    summary_table.add_row('Total discovered', str(len(all_keywords)))
    if save:
        summary_table.add_row('New keywords saved', str(saved_count))

    console.print(
        Panel(summary_table, title='[bold green]Discovery Summary[/bold green]', border_style='green')
    )

    console.print(
        '\n[dim]Tip: Run "kdp-scout score" to score these keywords, '
        'or "kdp-scout mine <keyword>" to expand any interesting ones.[/dim]'
    )


# -- Mine Categories command -----------------------------------------------


@main.command('mine-categories')
@click.option(
    '--categories',
    default=None,
    help='Comma-separated list of categories to mine (default: all built-in).',
)
@click.option(
    '--depth',
    type=click.IntRange(1, 2),
    default=1,
    help='Mining depth per category.',
)
@click.option(
    '--department',
    type=click.Choice(['kindle', 'books', 'all']),
    default='kindle',
    help='Amazon department to search.',
)
@click.option(
    '--limit-categories',
    type=int,
    default=None,
    help='Only mine the first N categories (useful for testing).',
)
@marketplace_option
def mine_categories(categories, depth, department, limit_categories, marketplace):
    """Auto-mine keywords across major KDP book categories.

    Runs autocomplete mining for each category in the built-in list
    (or a custom list), building a comprehensive keyword database
    without manual seed entry.

    This is equivalent to running "kdp-scout mine" once for each
    category, but automated.

    Examples:
        kdp-scout mine-categories
        kdp-scout mine-categories --depth 2
        kdp-scout mine-categories --categories "romance,thriller,mystery"
        kdp-scout mine-categories --limit-categories 5
    """
    from kdp_scout.collectors.trending import get_category_seeds
    from kdp_scout.keyword_engine import mine_keywords

    # Determine category list
    if categories:
        cat_list = [c.strip() for c in categories.split(',') if c.strip()]
    else:
        cat_list = get_category_seeds()

    if limit_categories:
        cat_list = cat_list[:limit_categories]

    console.print(
        Panel(
            f'[bold]Categories:[/bold] {len(cat_list)}\n'
            f'[bold]Depth:[/bold] {depth}\n'
            f'[bold]Department:[/bold] {department}\n'
            f'[bold]Marketplace:[/bold] {marketplace or Config.MARKETPLACE}\n'
            f'[bold]Est. queries:[/bold] ~{len(cat_list) * 27 * depth:,}',
            title='[bold cyan]KDP Scout - Category Mining[/bold cyan]',
            border_style='cyan',
        )
    )
    console.print()

    # Show categories being mined
    cat_preview = ', '.join(cat_list[:10])
    if len(cat_list) > 10:
        cat_preview += f', ... (+{len(cat_list) - 10} more)'
    console.print(f'[dim]Categories: {cat_preview}[/dim]\n')

    total_new = 0
    total_existing = 0
    total_mined = 0
    category_results = []

    with Progress(
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
        TextColumn('({task.completed}/{task.total})'),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        cat_task = progress.add_task(
            'Mining categories...', total=len(cat_list)
        )

        for cat in cat_list:
            progress.update(
                cat_task,
                description=f'Mining "{cat}"...',
            )

            try:
                result = mine_keywords(
                    seed=cat,
                    depth=depth,
                    department=department,
                    marketplace=marketplace,
                )

                total_new += result['new_count']
                total_existing += result['existing_count']
                total_mined += result['total_mined']

                category_results.append({
                    'category': cat,
                    'total': result['total_mined'],
                    'new': result['new_count'],
                })

            except KeyboardInterrupt:
                console.print(
                    '\n[yellow]Interrupted. Partial results have been saved.[/yellow]'
                )
                break
            except Exception as e:
                console.print(f'\n[red]Error mining "{cat}": {e}[/red]')
                category_results.append({
                    'category': cat,
                    'total': 0,
                    'new': 0,
                    'error': str(e),
                })

            progress.advance(cat_task)

    # Results summary
    console.print()

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column('Label', style='bold')
    summary_table.add_column('Value', style='green')
    summary_table.add_row('Categories mined', str(len(category_results)))
    summary_table.add_row('Total keywords found', str(total_mined))
    summary_table.add_row('New keywords', str(total_new))
    summary_table.add_row('Already in database', str(total_existing))

    console.print(
        Panel(summary_table, title='[bold green]Category Mining Summary[/bold green]', border_style='green')
    )

    # Top categories by new keywords
    if category_results:
        console.print()
        top_cats = sorted(category_results, key=lambda x: x['new'], reverse=True)[:15]
        cat_table = Table(title='Top Categories by New Keywords', show_lines=False)
        cat_table.add_column('Category', style='bold', min_width=25)
        cat_table.add_column('Total', justify='right', width=8)
        cat_table.add_column('New', justify='right', width=8, style='green')

        for cat in top_cats:
            cat_table.add_row(cat['category'], str(cat['total']), str(cat['new']))

        console.print(cat_table)

    console.print(
        '\n[dim]Tip: Run "kdp-scout score" to score all keywords, '
        'then "kdp-scout report keywords" for the full ranked list.[/dim]'
    )
    console.print(f'[dim]Database: {Config.get_db_path()}[/dim]')


# -- Phase 5: Automation, Seeds, Cron --------------------------------------

from kdp_scout.cli_automation import automate, seeds, cron
main.add_command(automate)
main.add_command(seeds)
main.add_command(cron)


if __name__ == '__main__':
    main()
