# Contributing to KDP Scout

Thanks for your interest in contributing! This guide covers how to get set up and submit changes.

## Setup

```bash
git clone https://github.com/rxpelle/kdp-scout.git
cd kdp-scout
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
kdp-scout config init
```

## Running Tests

```bash
pytest
pytest --cov=kdp_scout  # with coverage report
```

## Code Style

- Follow existing patterns in the codebase
- Use type hints where practical
- Write docstrings for public functions (Google style)
- Keep functions focused and reasonably short

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make your changes
4. Add tests for new functionality
5. Run `pytest` and ensure all tests pass
6. Commit with a clear message
7. Push and open a Pull Request

## What to Contribute

Good first issues:
- Add tests for untested modules
- Improve error messages
- Add new report formats
- Fix scraping for new Amazon page layouts

Larger contributions:
- New collector plugins (see `kdp_scout/collectors/`)
- Additional marketplace support
- Better search volume estimation

## Architecture Overview

```
kdp_scout/
    cli.py               # Click CLI — entry point
    keyword_engine.py    # Scoring algorithm
    reporting.py         # Report generation
    collectors/          # Data collection plugins
        base.py          # Base collector class
        autocomplete.py  # Amazon autocomplete
        product_scraper.py  # Product page scraper
        ads_importer.py  # CSV importer
        dataforseo.py    # DataForSEO API
```

The scoring algorithm in `keyword_engine.py` and the parsing functions in `ads_importer.py` are the most testable modules. The collectors under `collectors/` follow a plugin pattern — see `base.py` for the interface.

## Questions?

Open an issue on GitHub. We're happy to help.
