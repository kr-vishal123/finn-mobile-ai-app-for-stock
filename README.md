# FINN — Financial Investment Agent

> Covering note, architecture, decisions and what's next: **[WRITEUP.md](WRITEUP.md)**.

A mobile-first agent for public-markets investors, with three layers:

- **Push**: tells you what changed across your portfolio and why it matters (windowed digest + threshold alerts).
- **Pull**: on-demand research on any NSE company, grounded only in primary sources (annual reports, concall transcripts).
- **Network**: your own contacts as an intelligence layer. Answers "who do I know who can help me understand this?" inside Push and Pull.

**Live:** https://finn-kjk0.onrender.com (free tier, so the first load can take about 50 s)

## Code tour (where to look first)

| Concern | File | What's interesting |
|---|---|---|
| Filing classification | [`backend/app/services/announcements.py`](backend/app/services/announcements.py) | Rules place 87% of NSE filings at no cost; the rest are batched to the cheap model |
| Model routing + cache | [`backend/app/services/llm.py`](backend/app/services/llm.py) | Cheap/strong tiers, prompt-hash cache, cost ledger, validated before caching |
| Reading filing PDFs | [`backend/app/services/filing_text.py`](backend/app/services/filing_text.py) | Who joined or left, role, verbatim SEBI profile; subject lines |
| Results card numbers | [`backend/app/services/fundamentals.py`](backend/app/services/fundamentals.py), [`results.py`](backend/app/services/results.py) | Screener tables → QoQ/YoY computed in code |
| Promised vs delivered | [`backend/app/services/guidance.py`](backend/app/services/guidance.py) | Guidance quotes (with page) from transcripts, checked against actuals |
| Grounded company Q&A | [`backend/app/services/qa.py`](backend/app/services/qa.py) | BM25 over transcript pages; every quote verified against the cited page |
| Network engine | [`backend/app/services/network.py`](backend/app/services/network.py) | Who to call, second-degree paths, filing-person links inferred from evidence, keep-warm |
| Ask router | [`backend/app/services/ask.py`](backend/app/services/ask.py) | Deterministic intent routing; name → ticker for any NSE company |
| Threshold alerts | [`backend/app/services/rules.py`](backend/app/services/rules.py) | Volume/price checks as pure functions over user-set thresholds |
| Schema | [`backend/app/models/`](backend/app/models/) | Every network table is scoped by `owner_id` |
| Mobile UI | [`frontend/src/screens/`](frontend/src/screens/) | Today (company-grouped feed), Company (Pull), Ask, People |
| Tests | [`backend/tests/`](backend/tests/) | Classifier, thresholds, guidance parsing, person extraction, regressions |

## Repo layout

```
backend/           FastAPI + SQLAlchemy
  app/
    config.py      settings from .env
    db.py          engine, session, Base
    models/        schema (market, filings, fundamentals, network, push, system)
    api/           routes, schemas, auth dependency
    services/      ingestion, LLM routing, filings, fundamentals, guidance, Q&A, network, ask
  scripts/         init_db, seeders, ingestion jobs
  tests/
frontend/          mobile-first web app (Vite + React + Tailwind PWA)
```

## Run it locally

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # optional: add ANTHROPIC_API_KEY
python -m scripts.seed                              # universe, prices, NSE filings + PDFs, fundamentals,
                                                    # transcripts -> guidance, synthetic network, alerts
uvicorn app.main:app --reload                       # http://localhost:8000  (API docs: /docs)

# frontend (dev, hot reload; proxies /api to :8000)
cd frontend && npm install && npm run dev           # http://localhost:5173
# or build once and let FastAPI serve it at :8000
npm run build
```

No network? `python -m scripts.seed --skip-prices --offline` uses the committed NSE snapshots, and a
fresh server with no DB boots from `backend/snapshots/demo.db` (refresh it with `python -m scripts.freeze_demo`).

Tests: `cd backend && pytest -q`

## Deploy

`Dockerfile` builds the frontend and serves it from FastAPI (one image, one URL). `render.yaml` deploys it
on Render's free tier; set `ANTHROPIC_API_KEY` in the dashboard.

## How Push works today

1. **Prices**: one batched yfinance call for all tickers, upserted into `price_bars`.
2. **Thresholds**: the investor's `alert_rules` (volume > N× 20-day average, |move| > X%), checked
   after every close. They're editable in the app, and saving re-checks the portfolio immediately.
3. **Filings**: NSE corporate announcements, one polite request per ticker, snapshotted to
   `backend/snapshots/nse/`. If NSE fails, the snapshot is used.
4. **Classification**: keyword rules on NSE's subject label and the filing text place ~87% of filings into
   the reference categories with a 1–5 materiality, at zero cost. The rest go to the cheap model
   (Claude Haiku 5.5) in batches of 20, cached by prompt hash in `llm_calls`.
5. **Feed**: one card per company that combines filings and market signals; routine filings are
   collapsed by type; an empty window widens to the latest filing day and says so.

## Data model at a glance

| Layer | Tables | Notes |
|---|---|---|
| Market | `companies`, `price_bars`, `watchlist_items`, `users` | EOD OHLCV from yfinance (`.NS`/`.BO`) |
| Push | `announcements`, `alert_rules`, `alerts` | Announcements are classified into the ENAM categories and given a priority, a materiality score, a one-liner and type-specific `enrichment`. Alerts are deduped per user |
| Pull | `financial_periods`, `documents`, `document_chunks`, `guidance_items` | Every claim traces to a document page. `guidance_items` records promised vs. delivered |
| Network | `people`, `experiences`, `educations`, `expertise`, `contacts`, `person_links`, `interactions` | Every row is scoped by `owner_id`, so one investor's network never touches another's. `companies` is the only shared join point |
| System | `llm_calls`, `ingestion_runs` | `llm_calls` is both the response cache and the cost ledger |

Filings, companies and people are linked through normalised names (`app/services/normalize.py`). For example, an incoming CFO named in a filing is matched to `people.name_normalized`, and employer strings in profiles are matched to `companies.name_normalized`.
