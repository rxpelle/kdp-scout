# KDP Scout

Amazon KDP keyword research and competitor analysis tool. Mines keywords from Amazon autocomplete, tracks competitor books with BSR/sales estimation, imports Amazon Ads data for real performance signals, and scores keywords with a composite algorithm.

Built for self-published authors who want data-driven keyword targeting without paying $50+/month for Publisher Rocket or similar tools.

## Installation

```bash
git clone https://github.com/kdp-scout/kdp-scout.git
cd kdp-scout
pip install -e .
kdp-scout config init
```

Copy the example environment file and configure:

```bash
cp .env.example .env
# Edit .env with your settings (all optional for free tier)
```

## Quick Start

Five commands to get productive:

```bash
# 1. Mine keywords from Amazon autocomplete
kdp-scout mine "historical fiction"

# 2. Track your book and competitors
kdp-scout track add B08N5WRWNW --own --name "My Book Title"
kdp-scout track add B003K16PJW --name "The Name of the Rose"

# 3. Import your Amazon Ads data (if running ads)
kdp-scout import-ads search-terms-report.csv

# 4. Score all keywords
kdp-scout score

# 5. See your top keywords
kdp-scout report keywords
```

## Command Reference

### Keyword Mining

```bash
# Mine with default settings (Kindle department, depth 1 = 27 queries)
kdp-scout mine "thriller"

# Mine deeper (expands each result with a-z, more queries)
kdp-scout mine "thriller" --depth 2

# Mine in Books department instead of Kindle
kdp-scout mine "romance" --department books
```

### Book Tracking

```bash
# Add a competitor book by ASIN
kdp-scout track add B003K16PJW --name "The Name of the Rose"

# Add your own book (highlighted in reports)
kdp-scout track add B08N5WRWNW --own --name "My Book Title"

# List all tracked books with latest data
kdp-scout track list

# Take fresh BSR/price/review snapshots
kdp-scout track snapshot

# Remove a book from tracking
kdp-scout track remove B003K16PJW
```

### Amazon Ads Integration

```bash
# Import search term report from Amazon Ads console
kdp-scout import-ads search-terms-report.csv

# Filter to specific campaign
kdp-scout import-ads report.csv --campaign "My Campaign"
```

### Keyword Scoring

```bash
# Score all keywords (combines autocomplete + competition + ads data)
kdp-scout score

# Force recalculation
kdp-scout score --recalculate
```

### Reports

```bash
# Top keywords ranked by composite score
kdp-scout report keywords
kdp-scout report keywords --limit 100 --min-score 50
kdp-scout report keywords --format csv > keywords.csv
kdp-scout report keywords --format json

# Competitor comparison table
kdp-scout report competitors

# Amazon Ads performance (aggregated search terms)
kdp-scout report ads

# Keyword gaps (impressions but no orders)
kdp-scout report gaps

# Keyword trends over time
kdp-scout report trends
kdp-scout report trends --days 7
```

### Export

```bash
# Export keywords formatted for Amazon Ads campaign import
kdp-scout export ads
kdp-scout export ads --min-score 50 > high-value-keywords.csv

# Generate optimized KDP backend keyword slots (7 x 50 bytes)
kdp-scout export backend
```

### Seed Keywords

```bash
# Add seeds for automated re-mining
kdp-scout seeds add "historical fiction"
kdp-scout seeds add "medieval mystery" --department books

# List all seeds
kdp-scout seeds list

# Remove a seed
kdp-scout seeds remove "historical fiction"
```

### Automation

```bash
# Run daily automation (snapshots + re-mine top seeds + score)
kdp-scout automate --daily

# Run weekly automation (full re-mine all seeds + export)
kdp-scout automate --weekly

# Quiet mode for cron (no Rich output, logs only)
kdp-scout automate --daily --quiet
```

### Cron Setup

```bash
# Show the cron entry that would be installed
kdp-scout cron show

# Install daily automation at 6 AM
kdp-scout cron install --schedule daily

# Install weekly automation (Mondays at 6 AM)
kdp-scout cron install --schedule weekly

# Remove automation
kdp-scout cron uninstall
```

### Configuration

```bash
# Show current settings
kdp-scout config show

# Initialize database and check config
kdp-scout config init
```

## Configuration (.env)

All settings are optional. The tool works entirely free without API keys.

```bash
# DataForSEO API (optional, for search volume data)
DATAFORSEO_API_KEY=

# Proxy for web scraping (optional, helps avoid Amazon rate limits)
PROXY_URL=

# Rate limits (seconds between requests)
AUTOCOMPLETE_RATE_LIMIT=0.5
PRODUCT_SCRAPE_RATE_LIMIT=2.0

# Database location
DB_PATH=data/kdp_scout.db

# Logging level
LOG_LEVEL=INFO
```

## Automation Setup

KDP Scout can run automatically via cron to keep your data fresh.

**Daily automation** (recommended):
- Takes BSR snapshots of all tracked books
- Re-mines your top 5 seed keywords for new autocomplete suggestions
- Re-scores all keywords with updated data
- Runs at 6 AM local time

**Weekly automation**:
- Everything in daily
- Full re-mine from ALL seed keywords
- Exports updated keyword lists
- Runs at 6 AM on Mondays

To set up:

```bash
# Install daily cron job
kdp-scout cron install --schedule daily

# Or install weekly
kdp-scout cron install --schedule weekly

# Verify it's installed
crontab -l

# Logs go to data/automation.log
tail -f data/automation.log
```

## Architecture

```
kdp_scout/
    __init__.py          # Package version
    cli.py               # Click CLI entry point
    config.py            # Settings from .env
    db.py                # SQLite schema, repositories
    keyword_engine.py    # Mining orchestration, scoring algorithm
    competitor_engine.py # Book tracking, BSR snapshots
    reporting.py         # Rich-formatted reports, exports
    http_client.py       # Shared requests session with retry/rotation
    rate_limiter.py      # Token bucket rate limiter
    automation.py        # Daily/weekly automation runner
    cron_helper.py       # Crontab management
    seeds.py             # Seed keyword persistence
    formatters.py        # Table/CSV/JSON output formatters
    progress.py          # Rich progress bar helpers
    collectors/
        __init__.py
        autocomplete.py      # Amazon autocomplete API miner
        product_scraper.py   # Amazon product page scraper
        bsr_model.py         # BSR-to-sales estimation model
        ads_importer.py      # Amazon Ads CSV importer
        dataforseo.py        # DataForSEO API (optional)
```

**Data flow:**
1. `mine` queries Amazon autocomplete, stores keywords + positions
2. `track add` scrapes product pages, stores BSR/price/reviews
3. `import-ads` reads CSV, cross-references with keyword table
4. `score` combines all signals into a composite score
5. `report` / `export` renders scored data for analysis or upload

## Free Tier vs Paid

| Feature | Free | With DataForSEO |
|---------|------|-----------------|
| Autocomplete mining | Unlimited | Unlimited |
| Book tracking | Unlimited | Unlimited |
| BSR snapshots | Unlimited | Unlimited |
| Ads data import | Unlimited | Unlimited |
| Keyword scoring | All signals | All signals |
| Reports & exports | Full | Full |
| Search volume data | Estimated | Actual monthly volumes |
| Competition scores | From scraping | API-accurate |

The free tier covers everything most authors need. DataForSEO adds actual search volume numbers if you want them (~$0.001 per keyword lookup).

## Example Workflows

### "I just published a book. What keywords should I target?"

```bash
# Mine keywords in your genre
kdp-scout mine "historical thriller"
kdp-scout mine "medieval mystery"
kdp-scout mine "conspiracy fiction"

# Score them
kdp-scout score

# See the best ones
kdp-scout report keywords --limit 50

# Export for Amazon Ads
kdp-scout export ads --min-score 50 > ads-keywords.csv

# Generate KDP backend keywords
kdp-scout export backend
```

### "What are my competitors ranking for?"

```bash
# Track competitor books
kdp-scout track add B003K16PJW --name "The Name of the Rose"
kdp-scout track add B00CW0OHR2 --name "The Pillars of the Earth"
kdp-scout track add B007OZKFQA --name "The Historian"

# Add your own book
kdp-scout track add B08N5WRWNW --own --name "My Book Title"

# Compare everyone
kdp-scout report competitors

# Mine keywords from competitor titles
kdp-scout mine "name of the rose"
kdp-scout mine "pillars of the earth"
```

### "How do I optimize my Amazon Ads?"

```bash
# Import your search term report
kdp-scout import-ads search-terms-feb.csv

# Score keywords with ads data
kdp-scout score

# Find gaps (impressions but no sales)
kdp-scout report gaps

# See top-performing search terms
kdp-scout report ads

# Export optimized keyword list with bid tiers
kdp-scout export ads --min-score 25 > optimized-keywords.csv
```

## Shell Completion

For zsh tab completion, add to your `~/.zshrc`:

```bash
# Adjust the path to where you cloned kdp-scout
source /path/to/kdp-scout/completions/kdp-scout.zsh
```

Then restart your shell or run `source ~/.zshrc`.

## Legal Disclaimer

This tool interacts with Amazon's public-facing autocomplete API and product pages for research purposes. **You are solely responsible for ensuring your use complies with Amazon's Terms of Service.**

Specifically:
- **Autocomplete mining** uses the same public API that powers Amazon's search bar suggestions. Use reasonable rate limits (the defaults are conservative).
- **Product page scraping** fetches publicly available book data (BSR, price, reviews). Respect rate limits to avoid being blocked.
- **Amazon Ads import** reads CSV files you export from your own Amazon Ads account. No Amazon systems are accessed.
- **DataForSEO integration** (optional) uses a licensed third-party API and does not scrape Amazon directly.

The authors of this software make no guarantees about continued access to Amazon's APIs or the accuracy of scraped data. Amazon may change their systems at any time.

**This tool is provided for educational and personal research purposes. Use responsibly and at your own risk.**

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

## License

MIT License. See [LICENSE](LICENSE) for details.
