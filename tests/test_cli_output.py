"""CLI tests for report/export output file support."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from kdp_scout.cli import main


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
            result = CliRunner().invoke(main, args)

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
            result = CliRunner().invoke(main, [*args, '-o', str(output_path)])

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
        result = CliRunner().invoke(
            main,
            ['report', 'keywords', '--output', str(output_path)],
        )

    assert result.exit_code == 0
    assert result.stdout == ''
    assert output_path.read_text(encoding='utf-8') == 'name,value\ncafé,1\nplain,2\n'
    assert f'Wrote 2 rows to {output_path}' in result.stderr
