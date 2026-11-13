"""Tests for the kdp-scout doctor health check.

Network, crontab, and filesystem edges are mocked. These tests never
open a socket or print credential values.
"""

import sqlite3
import sys
from unittest.mock import MagicMock, patch

import requests
from click.testing import CliRunner

from kdp_scout.cli import (
    CheckResult,
    check_configuration,
    check_cron,
    check_database,
    check_dataforseo,
    check_network,
    check_python_version,
    check_scavio,
    check_virtualenv,
    doctor_exit_code,
    main,
    render_doctor_report,
    run_doctor_checks,
)
from kdp_scout.config import Config
from kdp_scout.db import init_db


def _passing_results():
    return [
        CheckResult('Python version', True, '3.11.6 (>= 3.9 required)'),
        CheckResult('Virtual environment', True, 'active (.venv)'),
        CheckResult('Database', True, 'data/kdp_scout.db exists, schema present'),
        CheckResult('Configuration', True, '.env loaded, MARKETPLACE=us'),
        CheckResult('Network', True, 'www.amazon.com reachable (HTTP 200, 12ms)'),
        CheckResult('DataForSEO', True, 'not configured (optional)', required=False),
        CheckResult('Scavio', True, 'not in use (optional)', required=False),
        CheckResult('Cron job', True, 'not installed (optional)', required=False),
    ]


def test_python_version_pass_and_fail():
    passed = check_python_version((3, 11, 6))
    assert passed.ok
    assert passed.detail == '3.11.6 (>= 3.9 required)'
    assert passed.fix is None

    failed = check_python_version((3, 8, 2))
    assert not failed.ok
    assert failed.required
    assert '3.8.2' in failed.detail
    assert '3.9' in failed.fix


def test_virtualenv_pass_and_fail(tmp_path):
    passed = check_virtualenv(prefix=str(tmp_path / '.venv'), base_prefix='/usr')
    assert passed.ok
    assert passed.detail == 'active (.venv)'

    failed = check_virtualenv(prefix='/usr', base_prefix='/usr')
    assert not failed.ok
    assert failed.required
    assert failed.detail == 'not active'
    assert '.venv' in failed.fix


def test_database_pass_reports_schema_without_inventing_version(tmp_path, monkeypatch):
    db_path = tmp_path / 'kdp_scout.db'
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))
    init_db()

    result = check_database()

    assert result.ok
    assert 'exists' in result.detail
    assert 'schema present' in result.detail
    assert 'schema version' not in result.detail


def test_database_reports_user_version_when_set(tmp_path, monkeypatch):
    db_path = tmp_path / 'kdp_scout.db'
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))
    init_db()
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA user_version = 4')
    conn.commit()
    conn.close()

    result = check_database()

    assert result.ok
    assert 'schema version 4' in result.detail


def test_database_missing_fails_and_does_not_create_file(tmp_path, monkeypatch):
    db_path = tmp_path / 'missing.db'
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))

    result = check_database()

    assert not result.ok
    assert result.required
    assert result.detail == 'not initialized'
    assert result.fix == 'kdp-scout config init'
    assert not db_path.exists()


def test_database_incomplete_schema_fails(tmp_path, monkeypatch):
    db_path = tmp_path / 'empty.db'
    sqlite3.connect(db_path).close()
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))

    result = check_database()

    assert not result.ok
    assert 'schema incomplete' in result.detail
    assert 'keywords' in result.detail
    assert result.fix == 'kdp-scout config init'


def test_database_unreadable_fails(tmp_path, monkeypatch):
    db_path = tmp_path / 'notes.txt'
    db_path.write_text('this is not a database', encoding='utf-8')
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))

    result = check_database()

    assert not result.ok
    assert result.detail == 'could not be read'
    assert result.fix == 'kdp-scout config init'


def test_configuration_loaded_hides_secrets(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    secret = 'super-secret-api-key'
    env.write_text(
        'MARKETPLACE=uk\n'
        f'DATAFORSEO_API_KEY={secret}\n'
        'DATAFORSEO_LOGIN=hidden-login@example.com\n'
        'PROXY_URL=http://user:password@proxy.example:8080\n',
        encoding='utf-8',
    )
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: env)
    monkeypatch.setattr(Config, 'MARKETPLACE', 'uk')

    result = check_configuration()
    blob = f'{result.detail} {result.fix}'

    assert result.ok
    assert result.detail == '.env loaded, MARKETPLACE=uk'
    assert secret not in blob
    assert 'hidden-login' not in blob
    assert 'password' not in blob


def test_configuration_missing_env_passes(tmp_path, monkeypatch):
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: tmp_path / '.env')
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')

    result = check_configuration()

    assert result.ok
    assert result.detail == 'no .env file (optional), MARKETPLACE=us'


def test_configuration_invalid_marketplace_fails(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('MARKETPLACE=zz\n', encoding='utf-8')
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: env)
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')

    result = check_configuration()

    assert not result.ok
    assert result.required
    assert result.detail == 'MARKETPLACE=zz is not supported'
    assert 'us' in result.fix


def test_configuration_unreadable_fails(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('MARKETPLACE=us\n', encoding='utf-8')
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: env)

    with patch('dotenv.dotenv_values', side_effect=OSError('denied')):
        result = check_configuration()

    assert not result.ok
    assert result.detail == '.env could not be read'
    assert '.env.example' in result.fix


def test_network_pass_uses_robots_txt_and_timeout(monkeypatch):
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')
    monkeypatch.setattr(Config, 'PROXY_URL', '')
    response = MagicMock(status_code=200)

    with patch('requests.head', return_value=response) as head, \
            patch('requests.get') as get:
        result = check_network()

    assert result.ok
    assert 'www.amazon.com reachable (HTTP 200,' in result.detail
    assert result.detail.endswith('ms)')
    url = head.call_args.args[0]
    assert url == 'https://www.amazon.com/robots.txt'
    assert 'dataforseo' not in url
    assert head.call_args.kwargs['timeout'] == 5
    get.assert_not_called()


def test_network_head_405_falls_back_to_get(monkeypatch):
    monkeypatch.setattr(Config, 'MARKETPLACE', 'de')
    monkeypatch.setattr(Config, 'PROXY_URL', '')
    head_response = MagicMock(status_code=405)
    get_response = MagicMock(status_code=200)

    with patch('requests.head', return_value=head_response), \
            patch('requests.get', return_value=get_response) as get:
        result = check_network()

    assert result.ok
    assert 'www.amazon.de reachable (HTTP 200,' in result.detail
    assert get.call_args.args[0] == 'https://www.amazon.de/robots.txt'
    assert get.call_args.kwargs['timeout'] == 5
    assert get.call_args.kwargs['stream'] is True


def test_network_connection_error_fails(monkeypatch):
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')
    monkeypatch.setattr(Config, 'PROXY_URL', '')

    with patch('requests.head', side_effect=requests.Timeout('slow')):
        result = check_network()

    assert not result.ok
    assert result.required
    assert result.detail == 'www.amazon.com unreachable'
    assert 'PROXY_URL' in result.fix


def test_network_http_error_fails_without_printing_proxy(monkeypatch):
    secret = 'http://user:s3cret@proxy.example:8080'
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')
    monkeypatch.setattr(Config, 'PROXY_URL', secret)
    response = MagicMock(status_code=503)

    with patch('requests.head', return_value=response) as head:
        result = check_network()

    assert not result.ok
    assert 'HTTP 503' in result.detail
    assert 's3cret' not in result.detail
    assert 's3cret' not in result.fix
    assert head.call_args.kwargs['proxies']['https'] == secret
    assert head.call_args.kwargs['timeout'] == 5


def test_dataforseo_pass_fail_and_redaction(monkeypatch):
    monkeypatch.setattr(Config, 'DATAFORSEO_LOGIN', '')
    monkeypatch.setattr(Config, 'DATAFORSEO_API_KEY', '')
    unset = check_dataforseo()
    assert unset.ok
    assert not unset.required
    assert unset.detail == 'not configured (optional)'

    monkeypatch.setattr(Config, 'DATAFORSEO_LOGIN', 'hidden-login@example.com')
    monkeypatch.setattr(Config, 'DATAFORSEO_API_KEY', 'super-secret-api-key')
    configured = check_dataforseo()
    assert configured.ok
    assert configured.detail == 'configured (optional)'
    assert 'hidden-login' not in configured.detail
    assert 'super-secret-api-key' not in configured.detail

    monkeypatch.setattr(Config, 'DATAFORSEO_API_KEY', '   ')
    partial = check_dataforseo()
    assert not partial.ok
    assert not partial.required
    assert partial.detail == 'incomplete (DATAFORSEO_API_KEY not set)'
    assert 'hidden-login' not in partial.detail
    assert 'DATAFORSEO_LOGIN' in partial.fix


def test_scavio_states_and_redaction(monkeypatch):
    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scraper')
    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', '')
    unused = check_scavio()
    assert unused.ok
    assert not unused.required
    assert unused.detail == 'not in use (optional)'

    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', 'super-secret-scavio-key')
    key_only = check_scavio()
    assert key_only.ok
    assert 'PRODUCT_SOURCE=scavio' in key_only.detail
    assert 'super-secret-scavio-key' not in key_only.detail

    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scavio')
    in_use = check_scavio()
    assert in_use.ok
    assert in_use.detail == 'product source (optional)'

    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', '   ')
    missing = check_scavio()
    assert not missing.ok
    assert not missing.required
    assert missing.detail == 'PRODUCT_SOURCE is scavio but SCAVIO_API_KEY is not set'
    assert 'SCAVIO_API_KEY' in missing.fix


def test_cron_optional_states():
    with patch('shutil.which', return_value=None):
        missing_bin = check_cron()
    assert missing_bin.ok
    assert not missing_bin.required
    assert missing_bin.detail == 'not available (optional)'

    with patch('shutil.which', return_value='/usr/bin/crontab'), \
            patch('kdp_scout.cron_helper.has_existing_entry', return_value=False):
        absent = check_cron()
    assert absent.ok
    assert absent.detail == 'not installed (optional)'

    with patch('shutil.which', return_value='/usr/bin/crontab'), \
            patch('kdp_scout.cron_helper.has_existing_entry', return_value=True):
        installed = check_cron()
    assert installed.ok
    assert installed.detail == 'installed (optional)'


def test_run_doctor_checks_pass_path_never_calls_network(tmp_path, monkeypatch):
    db_path = tmp_path / 'kdp_scout.db'
    monkeypatch.setattr(Config, 'DB_PATH', str(db_path))
    init_db()
    env = tmp_path / '.env'
    env.write_text(
        'MARKETPLACE=us\nDATAFORSEO_API_KEY=do-not-print\n',
        encoding='utf-8',
    )
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: env)
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / '.venv'))
    monkeypatch.setattr(sys, 'base_prefix', '/usr')
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')
    monkeypatch.setattr(Config, 'DATAFORSEO_LOGIN', '')
    monkeypatch.setattr(Config, 'DATAFORSEO_API_KEY', '')
    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', '')
    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scraper')
    monkeypatch.setattr(Config, 'PROXY_URL', '')
    response = MagicMock(status_code=200)

    with patch('requests.head', return_value=response) as head, \
            patch('requests.get') as get, \
            patch('shutil.which', return_value='/usr/bin/crontab'), \
            patch('kdp_scout.cron_helper.has_existing_entry', return_value=False):
        results = run_doctor_checks()

    rendered = '\n'.join(
        f'{result.detail} {result.fix or ""}' for result in results
    )
    assert all(result.ok for result in results)
    assert doctor_exit_code(results) == 0
    assert head.call_args.args[0].endswith('/robots.txt')
    get.assert_not_called()
    assert 'do-not-print' not in rendered
    assert results[0].name == 'Python version'
    assert results[0].ok


def test_run_doctor_checks_fail_path(tmp_path, monkeypatch):
    missing_db = tmp_path / 'missing.db'
    monkeypatch.setattr(Config, 'DB_PATH', str(missing_db))
    monkeypatch.setattr('kdp_scout.cli.env_file_path', lambda: tmp_path / '.env')
    monkeypatch.setattr(Config, 'MARKETPLACE', 'us')
    monkeypatch.setattr(Config, 'DATAFORSEO_LOGIN', 'only-login')
    monkeypatch.setattr(Config, 'DATAFORSEO_API_KEY', '')
    monkeypatch.setattr(Config, 'SCAVIO_API_KEY', '')
    monkeypatch.setattr(Config, 'PRODUCT_SOURCE', 'scraper')
    monkeypatch.setattr(Config, 'PROXY_URL', '')
    monkeypatch.setattr(sys, 'prefix', '/usr')
    monkeypatch.setattr(sys, 'base_prefix', '/usr')

    with patch('requests.head', side_effect=requests.ConnectionError('blocked')), \
            patch('shutil.which', return_value=None):
        results = run_doctor_checks()

    by_name = {result.name: result for result in results}
    assert by_name['Python version'].ok
    assert not by_name['Virtual environment'].ok
    assert not by_name['Database'].ok
    assert by_name['Configuration'].ok
    assert not by_name['Network'].ok
    assert not by_name['DataForSEO'].ok
    assert not by_name['DataForSEO'].required
    assert 'only-login' not in by_name['DataForSEO'].detail
    assert by_name['Cron job'].ok
    assert doctor_exit_code(results) == 1
    assert not missing_db.exists()


def test_doctor_command_pass(monkeypatch):
    monkeypatch.setattr('kdp_scout.cli.run_doctor_checks', _passing_results)
    result = CliRunner().invoke(main, ['doctor'])

    assert result.exit_code == 0
    assert 'KDP Scout Doctor' in result.output
    assert '✓ Python version: 3.11.6 (>= 3.9 required)' in result.output
    assert '✓ DataForSEO: not configured (optional)' in result.output
    assert '✓ Cron job: not installed (optional)' in result.output
    assert "All checks passed. You're good to go." in result.output
    assert 'Fix:' not in result.output


def test_doctor_command_required_failure(monkeypatch):
    results = _passing_results()
    results[2] = CheckResult(
        'Database',
        False,
        'not initialized',
        fix='kdp-scout config init',
        required=True,
    )
    monkeypatch.setattr('kdp_scout.cli.run_doctor_checks', lambda: results)

    result = CliRunner().invoke(main, ['doctor'])

    assert result.exit_code == 1
    assert '✗ Database: not initialized' in result.output
    assert '   Fix: kdp-scout config init' in result.output
    assert 'Some required checks failed.' in result.output


def test_doctor_command_optional_failure_exits_zero(monkeypatch):
    results = _passing_results()
    results[5] = CheckResult(
        'DataForSEO',
        False,
        'incomplete (DATAFORSEO_API_KEY not set)',
        fix=(
            'Set both DATAFORSEO_LOGIN and DATAFORSEO_API_KEY in .env, '
            'or leave both empty'
        ),
        required=False,
    )
    monkeypatch.setattr('kdp_scout.cli.run_doctor_checks', lambda: results)

    result = CliRunner().invoke(main, ['doctor'])

    assert result.exit_code == 0
    assert '✗ DataForSEO: incomplete (DATAFORSEO_API_KEY not set)' in result.output
    assert 'Fix: Set both DATAFORSEO_LOGIN and DATAFORSEO_API_KEY' in result.output
    assert 'Required checks passed. Review the optional items above.' in result.output


def test_render_doctor_report_matches_command_summary():
    code = render_doctor_report(_passing_results())
    assert code == 0
