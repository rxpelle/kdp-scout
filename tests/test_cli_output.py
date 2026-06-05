"""CLI tests for report/export output file support."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from kdp_scout import reporting
from kdp_scout.cli import main
from kdp_scout.config import Config
from kdp_scout.db import KeywordRepository, init_db


def make_runner():
    """A CliRunner that keeps stdout and stderr on separate streams.

    Click <8.2 mixes the two by default and needs ``mix_stderr=False``;
    Click >=8.2 removed the argument and always separates them. Supporting
    both keeps these tests green across the versions the project may resolve.
    """
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


COMMANDS = [
    (['report', 'keywords'], 'keyword_summary', 3),
    (['report', 'competitors'], 'competitor_summary', 2),
    (['report', 'ads'], 'ads_performance', 4),
    (['report', 'gaps'], 'keyword_gaps', 5),
    (['report', 'trends'], 'trend_report', 6),
    (['export', 'ads'], 'export_for_ads', None),
    (['export', 'backend'], 'export_backend_keywords', 7),
]


def _engine_with_output(method_name, body, return_value):
    engine = MagicMock()

    def emit_output(*args, **kwargs):
        print(body, end='')
        return body if return_value is None else return_value

    setattr(engine, method_name, MagicMock(side_effect=emit_output))
    return engine


def test_export_report_commands_preserve_stdout_without_output():
    for args, method_name, return_value in COMMANDS:
        body = 'name,value\ncafé,1\nplain,2\n'
        engine = _engine_with_output(method_name, body, return_value)

        with patch('kdp_scout.reporting.ReportingEngine', return_value=engine):
            result = make_runner().invoke(main, args)

        assert result.exit_code == 0
        assert result.stdout == body
        assert result.stderr == ''
        getattr(engine, method_name).assert_called_once()
        engine.close.assert_called_once()


def test_export_report_commands_write_output_file(tmp_path):
    for args, method_name, return_value in COMMANDS:
        body = 'name,value\ncafé,1\nplain,2\n'
        output_path = tmp_path / f'{"-".join(args)}.txt'
        engine = _engine_with_output(method_name, body, return_value)

        with patch('kdp_scout.reporting.ReportingEngine', return_value=engine):
            result = make_runner().invoke(main, [*args, '-o', str(output_path)])

        assert result.exit_code == 0
        assert result.stdout == ''
        assert output_path.read_text(encoding='utf-8') == body
        expected_count = 2 if return_value is None else return_value
        assert f'Wrote {expected_count} rows to {output_path}' in result.stderr
        getattr(engine, method_name).assert_called_once()
        engine.close.assert_called_once()


def test_output_long_option_writes_file(tmp_path):
    output_path = tmp_path / 'keywords.txt'
    engine = _engine_with_output(
        'keyword_summary',
        'name,value\ncafé,1\nplain,2\n',
        2,
    )

    with patch('kdp_scout.reporting.ReportingEngine', return_value=engine):
        result = make_runner().invoke(
            main,
            ['report', 'keywords', '--output', str(output_path)],
        )

    assert result.exit_code == 0
    assert result.stdout == ''
    assert output_path.read_text(encoding='utf-8') == 'name,value\ncafé,1\nplain,2\n'
    assert f'Wrote 2 rows to {output_path}' in result.stderr


# ── Real-engine integration tests ─────────────────────────────────
#
# The tests above mock ReportingEngine and emit via the builtin print(),
# so they never exercise the actual Rich console rendering. The whole
# feature depends on contextlib.redirect_stdout capturing *Rich* output
# (rich.console.Console) into the file. These tests run the real engine
# against a seeded temp database to guard that capture path end to end.


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the reporting engine at an isolated, schema-initialized DB."""
    monkeypatch.setattr(Config, 'DB_PATH', str(tmp_path / 'kdp_scout_test.db'))
    init_db()


def _seed_keywords(rows):
    """Insert (keyword, score) pairs with a metrics snapshot for each."""
    repo = KeywordRepository()
    try:
        for keyword, score in rows:
            keyword_id, _ = repo.upsert_keyword(keyword)
            repo.add_metric(
                keyword_id,
                autocomplete_position=1,
                estimated_volume=1000,
                competition_count=50,
            )
            repo.update_score(keyword_id, score)
    finally:
        repo.close()


def test_real_engine_writes_rich_table_to_file(temp_db, tmp_path, monkeypatch):
    """A real ReportingEngine renders a Rich table through redirect_stdout
    into the output file — the path the mocked tests cannot reach."""
    # Force a wide console so table cells are not width-wrapped/truncated.
    monkeypatch.setattr(reporting, 'console', Console(width=200))
    _seed_keywords([('medieval thriller books', 90), ('historical conspiracy', 70)])

    output_path = tmp_path / 'keywords.txt'
    result = make_runner().invoke(
        main, ['report', 'keywords', '-o', str(output_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == ''
    content = output_path.read_text(encoding='utf-8')
    assert 'Top Keywords' in content          # Rich table title was captured
    assert 'medieval thriller books' in content
    assert 'historical conspiracy' in content
    assert f'Wrote 2 rows to {output_path}' in result.stderr


def test_real_engine_empty_db_writes_zero_rows(temp_db, tmp_path):
    """Boundary: an empty DB still renders its message to the file and
    reports a row count of 0."""
    output_path = tmp_path / 'empty.txt'
    result = make_runner().invoke(
        main, ['report', 'keywords', '-o', str(output_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == ''
    assert output_path.read_text(encoding='utf-8').strip() != ''
    assert f'Wrote 0 rows to {output_path}' in result.stderr
