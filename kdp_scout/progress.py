"""Reusable progress bar helpers for KDP Scout.

Provides pre-configured Rich progress bar styles for different
operations: mining, scraping, and scoring. Each progress bar style
includes appropriate spinners, descriptions, and status fields.
"""

from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    TaskProgressColumn,
)


def create_mining_progress():
    """Create a rich progress bar for keyword mining.

    Shows a spinner, description, bar, percentage, time remaining,
    and a status field for the current operation.

    Returns:
        Rich Progress instance.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn('[bold blue]{task.description}'),
        BarColumn(),
        TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
        TimeRemainingColumn(),
        TextColumn('{task.fields[status]}', style='dim'),
    )


def create_scraping_progress():
    """Create a rich progress bar for web scraping.

    Shows a spinner, description, bar, fraction completed,
    and elapsed time. Suited for operations with variable timing.

    Returns:
        Rich Progress instance.
    """
    return Progress(
        SpinnerColumn(spinner_name='dots'),
        TextColumn('[bold cyan]{task.description}'),
        BarColumn(),
        TextColumn('({task.completed}/{task.total})'),
        TimeElapsedColumn(),
        TextColumn('{task.fields[status]}', style='dim'),
    )


def create_scoring_progress():
    """Create a rich progress bar for keyword scoring.

    Shows a spinner, description, bar, and percentage. Lightweight
    since scoring is a fast CPU-bound operation.

    Returns:
        Rich Progress instance.
    """
    return Progress(
        SpinnerColumn(spinner_name='line'),
        TextColumn('[bold green]{task.description}'),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn('{task.fields[status]}', style='dim'),
    )


def create_automation_progress():
    """Create a rich progress bar for automation tasks.

    Shows a spinner, description, bar, percentage, and elapsed time.
    Used by the DailyAutomation runner.

    Returns:
        Rich Progress instance.
    """
    return Progress(
        SpinnerColumn(spinner_name='dots2'),
        TextColumn('[bold yellow]{task.description}'),
        BarColumn(),
        TextColumn('[progress.percentage]{task.percentage:>3.0f}%'),
        TimeElapsedColumn(),
        TextColumn('{task.fields[status]}', style='dim'),
    )
