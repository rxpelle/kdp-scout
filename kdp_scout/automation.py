"""Automated daily and weekly tasks for KDP Scout.

Provides a standalone automation module that can be run via cron or
manually to perform recurring tasks: BSR snapshots, keyword re-mining,
scoring, and summary generation.
"""

import logging
from datetime import datetime, date

from rich.console import Console
from rich.panel import Panel

from kdp_scout.config import Config
from kdp_scout.db import (
    init_db, KeywordRepository, BookRepository, get_connection,
)
from kdp_scout.seeds import SeedManager
from kdp_scout.progress import create_automation_progress

logger = logging.getLogger(__name__)
console = Console()


class DailyAutomation:
    """Automated daily tasks for KDP Scout.

    Runs BSR snapshots, keyword re-mining, scoring, and generates
    daily summaries. Designed to be called from cron or manually.
    """

    def __init__(self):
        """Initialize automation with database and seed manager."""
        init_db()
        self._seed_mgr = SeedManager()

    def run_daily(self, quiet=False):
        """Run all daily automation tasks.

        Steps:
            1. Take BSR snapshots of all tracked books
            2. Re-mine top seed keywords for new autocomplete suggestions
            3. Re-score all keywords
            4. Generate daily summary

        Args:
            quiet: If True, suppress Rich output (for cron jobs).
                   Logs are still written to the log file.
        """
        start_time = datetime.now()
        logger.info('Starting daily automation run')

        results = {
            'snapshots': None,
            'mining': None,
            'scoring': None,
            'timestamp': start_time.isoformat(),
        }

        if not quiet:
            console.print(
                Panel(
                    f'[bold]Starting daily automation[/bold]\n'
                    f'Time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}',
                    title='[bold yellow]KDP Scout - Daily Automation[/bold yellow]',
                    border_style='yellow',
                )
            )
            console.print()

        # Step 1: BSR snapshots
        if not quiet:
            console.print('[bold]Step 1/3:[/bold] Taking BSR snapshots...')
        results['snapshots'] = self._take_snapshots(quiet=quiet)

        # Step 2: Re-mine seed keywords
        if not quiet:
            console.print('[bold]Step 2/3:[/bold] Re-mining seed keywords...')
        results['mining'] = self._remine_seeds(top_n=5, quiet=quiet)

        # Step 3: Re-score all keywords
        if not quiet:
            console.print('[bold]Step 3/3:[/bold] Scoring keywords...')
        results['scoring'] = self._score_keywords(quiet=quiet)

        elapsed = (datetime.now() - start_time).total_seconds()
        results['elapsed_seconds'] = elapsed

        logger.info(f'Daily automation complete in {elapsed:.1f}s')

        if not quiet:
            console.print()
            summary = self.get_daily_summary()
            console.print(
                Panel(
                    summary,
                    title='[bold green]Daily Summary[/bold green]',
                    border_style='green',
                )
            )

        return results

    def run_weekly(self, quiet=False):
        """Run weekly tasks.

        Steps:
            1. Everything in daily
            2. Full keyword re-mine from ALL seeds (not just top N)
            3. Generate weekly summary

        Args:
            quiet: If True, suppress Rich output (for cron jobs).
        """
        start_time = datetime.now()
        logger.info('Starting weekly automation run')

        if not quiet:
            console.print(
                Panel(
                    f'[bold]Starting weekly automation[/bold]\n'
                    f'Time: {start_time.strftime("%Y-%m-%d %H:%M:%S")}',
                    title='[bold yellow]KDP Scout - Weekly Automation[/bold yellow]',
                    border_style='yellow',
                )
            )
            console.print()

        results = {
            'timestamp': start_time.isoformat(),
        }

        # Step 1: BSR snapshots
        if not quiet:
            console.print('[bold]Step 1/4:[/bold] Taking BSR snapshots...')
        results['snapshots'] = self._take_snapshots(quiet=quiet)

        # Step 2: Full re-mine from ALL seeds
        if not quiet:
            console.print('[bold]Step 2/4:[/bold] Full keyword re-mine (all seeds)...')
        results['mining'] = self._remine_seeds(top_n=None, quiet=quiet)

        # Step 3: Re-score all keywords
        if not quiet:
            console.print('[bold]Step 3/4:[/bold] Scoring keywords...')
        results['scoring'] = self._score_keywords(quiet=quiet)

        # Step 4: Export updated keyword lists
        if not quiet:
            console.print('[bold]Step 4/4:[/bold] Exporting keyword lists...')
        results['export'] = self._export_keywords(quiet=quiet)

        elapsed = (datetime.now() - start_time).total_seconds()
        results['elapsed_seconds'] = elapsed

        logger.info(f'Weekly automation complete in {elapsed:.1f}s')

        if not quiet:
            console.print()
            summary = self.get_daily_summary()
            console.print(
                Panel(
                    summary,
                    title='[bold green]Weekly Summary[/bold green]',
                    border_style='green',
                )
            )

        return results

    def get_daily_summary(self):
        """Generate a text summary of today's data state.

        Returns:
            Formatted string with summary of books, BSR changes,
            keywords, and top movers.
        """
        conn = get_connection()
        try:
            kw_repo = KeywordRepository(conn)
            book_repo = BookRepository(conn)
            today = date.today().isoformat()

            # Books tracked
            books = book_repo.get_books_with_latest_snapshot()
            book_count = len(books)

            # BSR changes
            bsr_changes = []
            for book in books:
                book_id = book['id']
                prev = book_repo.get_previous_snapshot(book_id)
                latest = book_repo.get_latest_snapshot(book_id)

                if prev and latest and prev['bsr_overall'] and latest['bsr_overall']:
                    old_bsr = prev['bsr_overall']
                    new_bsr = latest['bsr_overall']
                    if old_bsr != new_bsr:
                        title = book['title'] or book['asin']
                        direction = 'improved' if new_bsr < old_bsr else 'declined'
                        bsr_changes.append(
                            f'  {title}: #{old_bsr:,} -> #{new_bsr:,} ({direction})'
                        )

            # Keywords summary
            total_keywords = kw_repo.get_keyword_count()
            top_keywords = kw_repo.get_keywords_with_latest_metrics(
                limit=5, min_score=0, order_by='score'
            )

            # Seed keywords
            seed_count = len(self._seed_mgr)

            # Build summary
            lines = [
                f'Books tracked: {book_count}',
                f'Seed keywords: {seed_count}',
                f'Total keywords: {total_keywords}',
            ]

            if bsr_changes:
                lines.append('')
                lines.append('BSR Changes:')
                lines.extend(bsr_changes)
            else:
                lines.append('BSR Changes: None detected')

            if top_keywords:
                lines.append('')
                lines.append('Top Keywords:')
                for i, kw in enumerate(top_keywords, 1):
                    score = kw['score'] or 0
                    lines.append(
                        f'  {i}. {kw["keyword"]} (score: {score:.0f})'
                    )

            lines.append('')
            lines.append(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

            return '\n'.join(lines)

        finally:
            conn.close()

    def _take_snapshots(self, quiet=False):
        """Take BSR snapshots of all tracked books.

        Returns:
            Dict with snapshot results.
        """
        from kdp_scout.competitor_engine import CompetitorEngine

        engine = CompetitorEngine()
        try:
            books = engine.list_books()
            if not books:
                if not quiet:
                    console.print('  [dim]No books tracked[/dim]')
                return {'count': 0, 'success': 0, 'failed': 0}

            results = engine.take_snapshot()
            success = sum(1 for r in results if r['success'])
            failed = len(results) - success

            if not quiet:
                console.print(
                    f'  [green]{success} snapshots taken[/green]'
                    + (f', [red]{failed} failed[/red]' if failed else '')
                )

            return {
                'count': len(results),
                'success': success,
                'failed': failed,
            }
        except Exception as e:
            logger.error(f'Snapshot failed: {e}')
            if not quiet:
                console.print(f'  [red]Error: {e}[/red]')
            return {'count': 0, 'success': 0, 'failed': 0, 'error': str(e)}
        finally:
            engine.close()

    def _remine_seeds(self, top_n=5, quiet=False):
        """Re-mine seed keywords for new autocomplete suggestions.

        Args:
            top_n: Number of top seeds to mine. None for all seeds.
            quiet: Suppress output.

        Returns:
            Dict with mining results.
        """
        from kdp_scout.keyword_engine import mine_keywords

        seeds = self._seed_mgr.list_seeds()
        if not seeds:
            if not quiet:
                console.print('  [dim]No seed keywords configured[/dim]')
            return {'seeds_mined': 0, 'new_keywords': 0}

        # Limit to top_n if specified
        if top_n is not None:
            seeds = seeds[:top_n]

        total_new = 0
        total_mined = 0

        for seed_data in seeds:
            keyword = seed_data['keyword']
            department = seed_data.get('department', 'kindle')

            try:
                result = mine_keywords(
                    keyword,
                    depth=1,
                    department=department,
                )
                total_new += result['new_count']
                total_mined += result['total_mined']

                # Mark as mined
                self._seed_mgr.mark_mined(keyword)

                if not quiet:
                    console.print(
                        f'  [dim]{keyword}:[/dim] '
                        f'{result["new_count"]} new, '
                        f'{result["total_mined"]} total'
                    )

            except Exception as e:
                logger.error(f'Failed to mine seed "{keyword}": {e}')
                if not quiet:
                    console.print(f'  [red]{keyword}: Error - {e}[/red]')

        if not quiet:
            console.print(
                f'  [green]Mined {len(seeds)} seeds: '
                f'{total_new} new keywords found[/green]'
            )

        return {
            'seeds_mined': len(seeds),
            'new_keywords': total_new,
            'total_keywords_seen': total_mined,
        }

    def _score_keywords(self, quiet=False):
        """Re-score all keywords.

        Returns:
            Dict with scoring results.
        """
        from kdp_scout.keyword_engine import KeywordScorer

        scorer = KeywordScorer()
        try:
            count = scorer.score_all_keywords()
            if not quiet:
                console.print(f'  [green]{count} keywords scored[/green]')
            return {'scored': count}
        except Exception as e:
            logger.error(f'Scoring failed: {e}')
            if not quiet:
                console.print(f'  [red]Error: {e}[/red]')
            return {'scored': 0, 'error': str(e)}
        finally:
            scorer.close()

    def _export_keywords(self, quiet=False):
        """Export keyword lists for the weekly run.

        Returns:
            Dict with export results.
        """
        from kdp_scout.reporting import ReportingEngine
        import io
        import sys

        engine = ReportingEngine()
        try:
            # Capture the CSV output
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            try:
                content = engine.export_for_ads(min_score=25)
            finally:
                sys.stdout = old_stdout

            keyword_count = content.count('\n') - 1 if content else 0  # minus header

            if not quiet:
                console.print(
                    f'  [green]{keyword_count} keywords ready for export[/green]'
                )

            return {'keywords_exported': max(0, keyword_count)}
        except Exception as e:
            logger.error(f'Export failed: {e}')
            if not quiet:
                console.print(f'  [red]Error: {e}[/red]')
            return {'keywords_exported': 0, 'error': str(e)}
        finally:
            engine.close()
