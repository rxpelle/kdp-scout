"""CLI commands for Phase 5: Automation & Polish.

Provides Click command groups for automation, seed management, and
cron setup. These commands are registered with the main CLI group
in cli.py.

To wire up after Phase 4 merge, add to cli.py:

    from kdp_scout.cli_automation import automate, seeds, cron
    main.add_command(automate)
    main.add_command(seeds)
    main.add_command(cron)
"""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


# -- Automate command ------------------------------------------------------


@click.command()
@click.option('--daily', 'schedule', flag_value='daily',
              help='Run daily automation tasks.')
@click.option('--weekly', 'schedule', flag_value='weekly',
              help='Run weekly automation tasks.')
@click.option('--quiet', is_flag=True,
              help='Suppress Rich output (for cron jobs).')
def automate(schedule, quiet):
    """Run automation tasks (daily or weekly).

    Daily: BSR snapshots + re-mine top seeds + score keywords.
    Weekly: Full re-mine all seeds + export keyword lists.

    Examples:
        kdp-scout automate --daily
        kdp-scout automate --weekly
        kdp-scout automate --daily --quiet
    """
    if not schedule:
        console.print(
            '[yellow]Specify --daily or --weekly.[/yellow]\n'
            'Example: kdp-scout automate --daily'
        )
        return

    from kdp_scout.automation import DailyAutomation

    auto = DailyAutomation()

    if schedule == 'weekly':
        auto.run_weekly(quiet=quiet)
    else:
        auto.run_daily(quiet=quiet)


# -- Seeds command group ---------------------------------------------------


@click.group()
def seeds():
    """Manage seed keywords for automated re-mining."""
    pass


@seeds.command('add')
@click.argument('keyword')
@click.option(
    '--department',
    type=click.Choice(['kindle', 'books', 'all']),
    default='kindle',
    help='Amazon department to search.',
)
def seeds_add(keyword, department):
    """Add a seed keyword for automated re-mining.

    Seeds are re-mined during daily/weekly automation to discover
    new autocomplete suggestions over time.

    Examples:
        kdp-scout seeds add "historical fiction"
        kdp-scout seeds add "medieval mystery" --department books
    """
    from kdp_scout.seeds import SeedManager

    mgr = SeedManager()
    is_new = mgr.add_seed(keyword, department=department)

    if is_new:
        console.print(
            f'[green]Added seed:[/green] "{keyword}" ({department})'
        )
    else:
        console.print(
            f'[yellow]Updated seed:[/yellow] "{keyword}" ({department})'
        )

    console.print(f'[dim]{len(mgr)} total seeds[/dim]')


@seeds.command('remove')
@click.argument('keyword')
def seeds_remove(keyword):
    """Remove a seed keyword.

    Example:
        kdp-scout seeds remove "historical fiction"
    """
    from kdp_scout.seeds import SeedManager

    mgr = SeedManager()
    removed = mgr.remove_seed(keyword)

    if removed:
        console.print(f'[green]Removed seed:[/green] "{keyword}"')
    else:
        console.print(f'[yellow]Seed not found:[/yellow] "{keyword}"')

    console.print(f'[dim]{len(mgr)} total seeds[/dim]')


@seeds.command('list')
def seeds_list():
    """List all seed keywords.

    Example:
        kdp-scout seeds list
    """
    from kdp_scout.seeds import SeedManager

    mgr = SeedManager()
    seed_list = mgr.list_seeds()

    if not seed_list:
        console.print(
            '[yellow]No seeds configured. '
            'Use "kdp-scout seeds add <keyword>" to add one.[/yellow]'
        )
        return

    table = Table(title='Seed Keywords', show_lines=False)
    table.add_column('#', style='dim', width=4, justify='right')
    table.add_column('Keyword', style='bold', min_width=20)
    table.add_column('Department', width=12)
    table.add_column('Times Mined', justify='right', width=12)
    table.add_column('Last Mined', width=20)
    table.add_column('Added', width=20)

    for i, seed in enumerate(seed_list, 1):
        last_mined = seed.get('last_mined')
        if last_mined:
            last_mined = last_mined[:19].replace('T', ' ')
        else:
            last_mined = '[dim]never[/dim]'

        added = seed.get('added_at', '')[:19].replace('T', ' ')
        mine_count = str(seed.get('mine_count', 0))

        table.add_row(
            str(i),
            seed['keyword'],
            seed.get('department', 'kindle'),
            mine_count,
            last_mined,
            added,
        )

    console.print(table)
    console.print(f'\n[dim]{len(seed_list)} seed(s)[/dim]')


# -- Cron command group ----------------------------------------------------


@click.group()
def cron():
    """Set up cron automation."""
    pass


@cron.command('show')
def cron_show():
    """Show the cron entry that would be installed.

    Example:
        kdp-scout cron show
    """
    from kdp_scout.cron_helper import (
        generate_cron_entry, has_existing_entry,
    )

    console.print('[bold]Daily entry:[/bold]')
    console.print(f'  {generate_cron_entry("daily")}')
    console.print()
    console.print('[bold]Weekly entry:[/bold]')
    console.print(f'  {generate_cron_entry("weekly")}')
    console.print()

    if has_existing_entry():
        console.print('[green]Status: Cron entry is installed[/green]')
    else:
        console.print('[yellow]Status: No cron entry installed[/yellow]')


@cron.command('install')
@click.option(
    '--schedule',
    type=click.Choice(['daily', 'weekly']),
    default='daily',
    help='Automation schedule.',
)
@click.confirmation_option(
    prompt='Install cron entry for KDP Scout automation?',
)
def cron_install(schedule):
    """Install cron automation.

    Adds a crontab entry to run KDP Scout automation on the specified
    schedule. Requires user confirmation.

    Examples:
        kdp-scout cron install
        kdp-scout cron install --schedule weekly
    """
    from kdp_scout.cron_helper import install_cron, generate_cron_entry

    entry = generate_cron_entry(schedule)
    console.print(f'[bold]Installing:[/bold] {entry}')

    success = install_cron(schedule)
    if success:
        console.print(
            f'[green]Cron entry installed ({schedule})[/green]\n'
            f'[dim]Logs: data/automation.log[/dim]'
        )
    else:
        console.print('[red]Failed to install cron entry[/red]')


@cron.command('uninstall')
@click.confirmation_option(
    prompt='Remove KDP Scout cron entry?',
)
def cron_uninstall():
    """Remove cron automation.

    Removes the KDP Scout entry from crontab.

    Example:
        kdp-scout cron uninstall
    """
    from kdp_scout.cron_helper import uninstall_cron

    success = uninstall_cron()
    if success:
        console.print('[green]Cron entry removed[/green]')
    else:
        console.print('[red]Failed to remove cron entry[/red]')
