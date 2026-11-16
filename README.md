# ADA PDF

A tool for auditing website PDFs against ADA/WCAG accessibility standards. It crawls a configured list of sites, catalogs every PDF it finds, scores each document for accessibility, and presents the results in a dashboard with CSV export for auditing and remediation tracking.

## Features

- **Multi-site crawling** — crawl a list of sites organized by platform, via sitemap (with depth-limited crawl fallback)
- **PDF cataloging** — detects PDF documents, records which page each was linked from, and tracks archive notices
- **Accessibility scoring** — per-PDF checks (tagged structure, language, title, etc.) plus WCAG 2.1 Level AA checks on HTML pages
- **Dashboard** — React frontend backed by a FastAPI + PostgreSQL stack
- **CSV export** — download PDF inventory and issue data per site from the dashboard
- **Dead-site reporting** — sites that fail or return zero pages are summarized at the end of each crawl so they can be pruned from the config

## Quick Start

### Prerequisites
- Docker Desktop

```bash
./start.sh
```

- **Dashboard**: http://localhost:3030
- **API**: http://localhost:8000 (docs at `/docs`)

See [DOCKER_README.md](DOCKER_README.md) for the full container architecture and troubleshooting.

> **Security note:** `docker-compose.yml` sets `POSTGRES_HOST_AUTH_METHOD: trust` for local development convenience. Do not deploy this configuration as-is.

## Configuration

Edit `config/sites.yaml` — sites are grouped into platforms, and `crawler_settings` controls depth, page limits, rate limiting, and `allowed_domains` (any crawled domain must appear there). `config/` is volume-mounted into the backend container, so changes take effect without rebuilding.

## Running a Crawl

The crawler writes results to Postgres incrementally, so the dashboard updates live.

```bash
# Inside the backend container
docker-compose exec backend python src/cli.py platforms --all

# Or specific platforms
docker-compose exec backend python src/cli.py platforms --platform platform_1

# Or locally (DB is exposed on localhost:5432)
pip install -r requirements.txt
python src/cli.py platforms --all
```

When the crawl finishes, any site that failed or returned zero pages is listed in the summary so you can remove it from `config/sites.yaml`.

## Clearing the Database

Postgres data persists in the `postgres_data` Docker volume across restarts. To start fresh:

```bash
docker-compose down -v   # drops the volume entirely
./start.sh               # schema is recreated from database/init.sql
```

Or keep the schema and just truncate the data:

```bash
python3 clear_database.py   # also clears output/ files
```

## Project Layout

```
config/sites.yaml          # site list + crawler settings
src/cli.py                 # crawler CLI entry point
src/crawler.py             # async crawler
src/accessibility.py       # WCAG checker (HTML pages)
src/pdf_accessibility_pypdf.py  # PDF accessibility checks
src/database.py            # SQLAlchemy models + helpers
backend/server_database.py # FastAPI dashboard API
frontend/                  # React dashboard
database/init.sql          # Postgres schema
```

## Roadmap

- **Server file inventory via SSH** — connect to the production web server to enumerate actual file paths for PDFs, so reported URLs can be mapped to real files on disk (useful for remediation and cleanup).
- Reconcile crawled PDF list with the on-disk inventory to flag orphaned files and broken links.

## Legal Considerations

- Check robots.txt before crawling (respected by default via `respect_robots_txt`)
- Respect rate limits; ensure you have permission to crawl the sites

## License

MIT — see [LICENSE](LICENSE).
