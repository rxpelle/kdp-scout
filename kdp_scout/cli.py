"""KDP Scout CLI entry point.

Provides the command-line interface using Click and Rich for
keyword research and competitor analysis.
"""

import sys
import signal
import logging

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel

from kdp_scout import __version__
from kdp_scout.config import Config
from kdp_scout.db import init_db

console = Console()


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
def mine(seed, depth, department):
    """Mine keywords from Amazon autocomplete.

    SEED is the keyword to expand (e.g., "historical fiction").

    Examples:
        kdp-scout mine "historical fiction"
        kdp-scout mine "thriller" --depth 2
        kdp-scout mine "romance" --department books
    """
    from kdp_scout.keyword_engine import mine_keywords

    console.print(
        Panel(
            f'[bold]Seed:[/bold] {seed}\n'
            f'[bold]Depth:[/bold] {depth}\n'
            f'[bold]Department:[/bold] {department}',
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


if __name__ == '__main__':
    main()
