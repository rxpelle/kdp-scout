"""Cron setup helper for KDP Scout automation.

Generates, installs, and uninstalls crontab entries for running
daily and weekly automation tasks. Detects the correct Python
interpreter and project paths automatically.
"""

import os
import sys
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root (one level up from this file's directory)
_project_root = Path(__file__).parent.parent

# Marker comment used to identify our cron entries
CRON_MARKER = '# KDP Scout automation'


def _get_python_path():
    """Get the path to the current Python interpreter.

    Returns:
        Absolute path to the Python binary.
    """
    return sys.executable


def _get_kdp_scout_path():
    """Get the path to the kdp-scout binary.

    Checks several locations where the binary might be installed:
    1. The same bin directory as the Python interpreter
    2. The user's PATH

    Returns:
        Path to kdp-scout binary, or a python -m invocation as fallback.
    """
    # Check if kdp-scout is in the same directory as the Python interpreter
    python_dir = Path(_get_python_path()).parent
    kdp_scout_bin = python_dir / 'kdp-scout'
    if kdp_scout_bin.exists():
        return str(kdp_scout_bin)

    # Check PATH
    try:
        result = subprocess.run(
            ['which', 'kdp-scout'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Fallback: use python -m invocation
    return f'{_get_python_path()} -m kdp_scout.cli'


def _get_log_path():
    """Get the path for the automation log file.

    Returns:
        Absolute path to the log file in the data/ directory.
    """
    log_dir = _project_root / 'data'
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / 'automation.log')


def generate_cron_entry(schedule='daily'):
    """Generate the crontab entry for automation.

    Args:
        schedule: 'daily' or 'weekly'.
            daily: Run at 6:00 AM local time every day.
            weekly: Run at 6:00 AM on Mondays.

    Returns:
        The complete crontab line string.
    """
    kdp_scout = _get_kdp_scout_path()
    log_path = _get_log_path()

    if schedule == 'weekly':
        # At 06:00 on Mondays
        cron_schedule = '0 6 * * 1'
        flag = '--weekly'
    else:
        # At 06:00 every day
        cron_schedule = '0 6 * * *'
        flag = '--daily'

    # Build the command
    command = f'{kdp_scout} automate {flag} --quiet'

    # Add project directory change and log redirection
    entry = (
        f'{cron_schedule} '
        f'cd {_project_root} && '
        f'{command} '
        f'>> {log_path} 2>&1 '
        f'{CRON_MARKER} ({schedule})'
    )

    return entry


def get_current_crontab():
    """Read the current user's crontab.

    Returns:
        Current crontab content as a string, or empty string if none.
    """
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return ''
    except (subprocess.SubprocessError, FileNotFoundError):
        return ''


def has_existing_entry():
    """Check if a KDP Scout cron entry already exists.

    Returns:
        True if an entry with our marker is found.
    """
    crontab = get_current_crontab()
    return CRON_MARKER in crontab


def install_cron(schedule='daily'):
    """Install the cron entry.

    Adds the cron entry to the user's crontab. If an existing KDP Scout
    entry is found, it is replaced.

    Args:
        schedule: 'daily' or 'weekly'.

    Returns:
        True if installation succeeded, False otherwise.
    """
    new_entry = generate_cron_entry(schedule)
    current = get_current_crontab()

    # Remove any existing KDP Scout entries
    lines = current.splitlines()
    filtered = [line for line in lines if CRON_MARKER not in line]

    # Add the new entry
    filtered.append(new_entry)

    # Write back, ensuring trailing newline
    new_crontab = '\n'.join(filtered).strip() + '\n'

    try:
        result = subprocess.run(
            ['crontab', '-'],
            input=new_crontab, text=True,
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info(f'Installed {schedule} cron entry')
            return True
        else:
            logger.error(f'Failed to install cron: {result.stderr}')
            return False
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f'Failed to install cron: {e}')
        return False


def uninstall_cron():
    """Remove the KDP Scout cron entry.

    Returns:
        True if removal succeeded (or no entry existed), False on error.
    """
    current = get_current_crontab()

    if CRON_MARKER not in current:
        logger.info('No KDP Scout cron entry found to remove')
        return True

    # Filter out our entries
    lines = current.splitlines()
    filtered = [line for line in lines if CRON_MARKER not in line]

    new_crontab = '\n'.join(filtered).strip()
    if new_crontab:
        new_crontab += '\n'

    try:
        if not new_crontab.strip():
            # If crontab would be empty, remove it entirely
            result = subprocess.run(
                ['crontab', '-r'],
                capture_output=True, text=True, timeout=10,
            )
        else:
            result = subprocess.run(
                ['crontab', '-'],
                input=new_crontab, text=True,
                capture_output=True, timeout=10,
            )

        if result.returncode == 0:
            logger.info('Removed KDP Scout cron entry')
            return True
        else:
            logger.error(f'Failed to remove cron: {result.stderr}')
            return False
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f'Failed to remove cron: {e}')
        return False
