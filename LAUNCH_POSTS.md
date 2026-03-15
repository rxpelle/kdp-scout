# KDP Scout Launch Posts - Week of March 9, 2026

Copy-paste ready. Edit as needed. Post in this order.


## MONDAY MORNING: Hacker News (Show HN)

**Title:** Show HN: KDP Scout - Open-source Amazon keyword research for self-published authors

**URL:** https://github.com/rxpelle/kdp-scout

**Top-level comment (post immediately after submitting):**

I self-publish novels on Amazon KDP. Like most indie authors, I was paying for keyword research tools (Publisher Rocket at $97, Helium 10 at $39/month) that essentially query Amazon's public autocomplete API and wrap it in a UI.

So I built my own. KDP Scout is a Python CLI that:

- Mines hundreds of long-tail keywords from Amazon autocomplete
- Imports your Sponsored Products ad reports and cross-references them with your keyword database
- Scores keywords using a composite algorithm (autocomplete position, ad impressions, clicks, orders, competition)
- Tracks competitor books (BSR, pricing, ratings over time)
- Exports directly into formats for KDP backend metadata or ad campaigns

The interesting technical bits:

- Uses a token-bucket rate limiter to stay under Amazon's radar
- BSR-to-sales estimation uses a power-law model calibrated against known sales data
- Keyword scoring combines signals from multiple sources into a single composite score
- Rich terminal output for reports, but also supports CSV/JSON export
- SQLite for local storage, zero external dependencies for core features

It's MIT licensed. No telemetry, no accounts, no upsell. I shared it in a large self-publishing Facebook group earlier this week and 300+ authors checked it out in a day. Figured the HN crowd might find the implementation interesting too.

Happy to answer questions about the technical approach or the self-publishing keyword game.

**Post at:** Tuesday or Wednesday, 8-9 AM ET
**Submit at:** https://news.ycombinator.com/submit


---


## MONDAY MORNING: r/Python

**Title:** I built an open-source CLI for Amazon keyword research (Click + Rich + SQLite)

**Body:**

I self-publish novels on Amazon and got tired of paying for keyword tools that basically wrap Amazon's autocomplete API in a GUI and charge $97 for it. So I built my own.

**KDP Scout** is a Python CLI built with Click, Rich, and SQLite. It mines keywords from Amazon autocomplete, imports ad performance data from CSVs, scores everything with a composite algorithm, and tracks competitor books over time.

Some things that might be interesting from a Python perspective:

- Click for the CLI with nested command groups (mine, track, report, export, etc.)
- Rich for terminal tables, progress bars, and formatted output
- Token-bucket rate limiter to manage scraping without getting blocked
- Power-law model for estimating daily sales from Amazon's Best Seller Rank
- SQLite with a repository pattern for local data storage
- Supports CSV/JSON export alongside Rich terminal output

It's MIT licensed and works entirely free without any API keys. Optional DataForSEO integration if you want actual search volume data.

GitHub: https://github.com/rxpelle/kdp-scout

Full writeup on why I built it: https://randypellegrini.com/blog/i-built-a-free-keyword-tool/

Happy to answer questions about the implementation.

**Post at:** Same day as HN
**Submit at:** https://www.reddit.com/r/Python/submit


---


## MONDAY: r/opensource

**Title:** KDP Scout - free, open-source keyword research tool for self-published authors (Python, MIT)

**Body:**

I self-publish novels on Amazon KDP. The keyword research tools in this space charge $97 (Publisher Rocket) or $39/month (Helium 10) for what is essentially Amazon's public autocomplete API in a paid wrapper.

I built KDP Scout as a free alternative and MIT-licensed it. It's a Python CLI that mines keywords from Amazon autocomplete, imports your ad data, scores keywords with a composite algorithm, and tracks competitor books.

I shared it in a large self-publishing community on Facebook and 300+ authors checked it out in one day. Figured the open-source community might appreciate it too.

No telemetry. No accounts. No "free tier" with an upsell. Just a CLI tool that works.

GitHub: https://github.com/rxpelle/kdp-scout

**Submit at:** https://www.reddit.com/r/opensource/submit


---


## MONDAY: r/commandline

**Title:** KDP Scout - CLI tool for Amazon keyword research (Python/Click/Rich)

**Body:**

Built a CLI tool for researching keywords on Amazon's book marketplace. Uses Click for command groups, Rich for terminal output, and SQLite for local storage.

Some commands:

```
kdp-scout mine "historical fiction"     # mine Amazon autocomplete
kdp-scout trending                       # discover trending keywords
kdp-scout track add B003K16PJW          # track a competitor book
kdp-scout score                          # score all keywords
kdp-scout report keywords               # rich terminal report
kdp-scout export backend                # export for Amazon KDP
```

GitHub: https://github.com/rxpelle/kdp-scout

MIT licensed. Designed to run locally with zero external accounts needed.

**Submit at:** https://www.reddit.com/r/commandline/submit


---


---


## WEDNESDAY: Twitter/X Thread

**Post 1:**
I self-publish books on Amazon and got tired of paying for keyword tools that charge $97 for what Amazon gives away for free.

So I built my own. It's open-source. Here's what it does:

**Post 2:**
KDP Scout mines hundreds of long-tail keywords from Amazon autocomplete, imports your Sponsored Products ad reports, and scores everything so you know what's worth targeting.

It also tracks competitor books -- BSR, pricing, ratings over time.

**Post 3:**
The best part: it's MIT licensed. No subscription. No upsell. No "free tier" that nudges you to pay. Just a Python CLI that works.

I shared it in a self-publishing group of 80,000+ authors and 300 people checked it out in one day.

**Post 4:**
Full writeup on why I built it:
https://randypellegrini.com/blog/i-built-a-free-keyword-tool/

Source code and install instructions:
https://github.com/rxpelle/kdp-scout

#WritingCommunity #IndieAuthor #KDP #SelfPublishing #AmWriting #OpenSource

Pin post 1 after threading.


---


## WEDNESDAY: dev.to Article

**Title:** I Built a Python CLI to Replace $97 Keyword Research Tools for Book Authors

**Tags:** python, opensource, cli, showdev

**Body:**

I self-publish novels on Amazon KDP. The keyword research tools in this space -- Publisher Rocket ($97), Helium 10 ($39/month) -- essentially query Amazon's public autocomplete API, wrap the results in a UI, and charge you for the privilege.

So I built [KDP Scout](https://github.com/rxpelle/kdp-scout), an open-source Python CLI that does everything those tools do, plus some things they don't.

### The Problem

Amazon KDP lets you attach 7 keyword slots (50 characters each) to your book's backend metadata. These keywords determine when your book appears in Amazon search results. On top of that, if you run Sponsored Products ads, you're bidding on search terms and need to know which ones convert.

The paid tools help with this, but they're essentially selling you access to data Amazon already makes available through its autocomplete API. Type a phrase into Amazon search, and the suggestions that appear? That's the same data these tools charge for.

### The Stack

- **Click** for the CLI framework with nested command groups
- **Rich** for terminal tables, progress bars, and formatted output
- **SQLite** for local storage (zero external dependencies)
- **Token-bucket rate limiter** to stay under Amazon's radar
- **Power-law model** for BSR-to-sales estimation

### How Keyword Scoring Works

KDP Scout combines multiple signals into a single composite score:

```python
# Simplified scoring logic
score = (
    autocomplete_weight * autocomplete_position_score +
    impressions_weight * normalized_impressions +
    clicks_weight * normalized_clicks +
    orders_weight * normalized_orders +
    competition_weight * inverse_competition
)
```

Autocomplete position matters because Amazon returns suggestions in ranked order -- position 1 has more search volume than position 10. When you layer on actual ad performance data (impressions, clicks, orders), you get a much more accurate picture of keyword value than autocomplete alone.

### The Ads Integration

This is where KDP Scout goes beyond what most paid tools offer. Amazon Ads lets you export search term reports showing exactly which terms triggered your ads, how many impressions/clicks/orders each generated, and what you spent.

KDP Scout imports these CSVs and cross-references them with your autocomplete-mined keywords:

```bash
kdp-scout import-ads search-terms-report.csv
kdp-scout score  # now includes real performance data
kdp-scout report gaps  # keywords with impressions but no orders
```

That `report gaps` command is gold -- it shows you keywords you're paying for that aren't converting, so you can cut them.

### BSR-to-Sales Estimation

Amazon doesn't publish sales numbers, but they do publish Best Seller Rank (BSR). KDP Scout uses a power-law model to estimate daily sales:

```
daily_sales = k * bsr^(-a)
```

Where k=150,000 and a=0.82 for the US Kindle store. This is calibrated against known sales data and is consistent with what other tools use (they just don't tell you the formula).

### Example Session

```bash
# Mine keywords in your genre
$ kdp-scout mine "historical thriller"
Mining 'historical thriller' (depth=1, department=kindle)...
Found 247 keywords (189 new)

# Score everything
$ kdp-scout score
Scored 1,847 keywords

# See what's worth targeting
$ kdp-scout report keywords --limit 10

# Export for your KDP backend
$ kdp-scout export backend
Generated 7 keyword slots (optimized for 50-byte limit)
```

### Why Open Source

The self-publishing community has enough people trying to sell you things. I built this for my own books, it worked, and I figured other authors could use it. It's MIT licensed -- use it, fork it, modify it.

The tool works entirely free. Optional DataForSEO integration adds actual search volume data at ~$0.001 per lookup, but the core features need nothing.

### Try It

```bash
git clone https://github.com/rxpelle/kdp-scout.git
cd kdp-scout
pip install -e .
kdp-scout config init
kdp-scout mine "your genre here"
```

Full writeup on why I built it: [randypellegrini.com/blog/i-built-a-free-keyword-tool](https://randypellegrini.com/blog/i-built-a-free-keyword-tool/)

If you find it useful and you're looking for something to read, I write historical thrillers. An honest review goes further than any payment.

**Publish at:** https://dev.to/new


---


## FRIDAY: Product Hunt

**Tagline:** Free, open-source keyword research for self-published authors

**Description:**

KDP Scout is a Python CLI that handles the full keyword research workflow for Amazon KDP authors -- mining keywords from Amazon autocomplete, importing ad performance data, scoring keywords with a composite algorithm, and tracking competitor books.

Built as a free, open-source alternative to Publisher Rocket ($97) and Helium 10 ($39/month). MIT licensed, no upsell, no accounts needed.

**Topics:** Productivity, Open Source, Developer Tools, Books

**Link:** https://github.com/rxpelle/kdp-scout

**Prep:** Create a short demo GIF showing a mine + score + report workflow in the terminal. Upload as the first image.

**Submit at:** https://www.producthunt.com/posts/new


---


## FRIDAY: Outreach Emails

### To Dale Roberts (selfpublishingwithdale.com)

Subject: Free open-source keyword tool for KDP authors (no pitch, just sharing)

Hi Dale,

I'm Randy Pellegrini, an indie author (The Aethelred Cipher, historical thriller). I built a free, open-source keyword research tool called KDP Scout and thought it might interest your audience.

It mines keywords from Amazon autocomplete, imports Sponsored Products ad reports, and scores everything with a composite algorithm. It's a Python CLI, MIT licensed, no upsell.

I shared it in 20BooksTo50K this week and several hundred authors checked it out in the first day. It also hit the front page of Hacker News [if it did -- otherwise remove this line].

Not looking for anything specific -- just thought it might be worth a look for your channel since you cover keyword research tools regularly.

GitHub: https://github.com/rxpelle/kdp-scout
Blog writeup: https://randypellegrini.com/blog/i-built-a-free-keyword-tool/

Thanks for all the content you put out. It's been genuinely helpful.

Randy


### To Joanna Penn (thecreativepenn.com)

Subject: Author-built open-source keyword tool for KDP

Hi Joanna,

I'm Randy Pellegrini, indie author of The Aethelred Cipher. I also happen to be a software engineer, and I built a free keyword research tool for KDP authors called KDP Scout.

It's open-source, MIT licensed, and built as an alternative to the paid keyword tools most of us use. I shared it in the 20BooksTo50K community and the response has been overwhelming.

I know you cover the intersection of technology and author empowerment -- this felt like it might fit. Happy to chat about it if you're interested.

GitHub: https://github.com/rxpelle/kdp-scout
Blog writeup: https://randypellegrini.com/blog/i-built-a-free-keyword-tool/

Best,
Randy


### To roundup bloggers (rachelharrisonsund.com, amazonseoconsultant.com, etc.)

Subject: Free KDP keyword tool for your tools roundup

Hi [Name],

I noticed your [article name] roundup and wanted to share KDP Scout -- a free, open-source keyword research tool I built for KDP authors. It mines Amazon autocomplete keywords, imports ad data, and scores everything with a composite algorithm.

It's MIT licensed with no upsell. Would you consider adding it to your list?

GitHub: https://github.com/rxpelle/kdp-scout
Blog writeup: https://randypellegrini.com/blog/i-built-a-free-keyword-tool/

Thanks,
Randy Pellegrini


---


## ONGOING: Facebook Groups

Use the same framing as the 20BooksTo50K post. Adjust the opening to reference the response you got there. Post to:

- SPF Community (check rules first, may need admin approval)
- Amazon KDP (unofficial groups -- search Facebook)
- Wide for the Win

---


## CHECKLIST

- [ ] Monday AM: Submit to Hacker News + post top comment
- [ ] Monday AM: Post to r/Python
- [ ] Monday AM: Post to r/opensource
- [ ] Monday AM: Post to r/commandline
- [ ] Wednesday AM: Post to r/selfpublish
- [ ] Wednesday AM: Post to r/kdp
- [ ] Wednesday: Publish dev.to article
- [ ] Wednesday: Post Twitter/X thread and pin
- [ ] Friday AM: Launch on Product Hunt
- [ ] Friday: Send outreach emails (Dale, Joanna, roundup bloggers)
- [ ] Friday: Post to remaining Facebook groups
- [ ] Throughout week: Respond to every comment on every platform
