# FINN: covering note

**What it is:** a mobile web app (installable as a PWA) for an investor with 16 NSE holdings and 5 research names. It has three tabs: **Today** (Push), **Ask** (Pull and Network queries) and **People** (the Network itself). Network suggestions also appear inside every pushed card and every company page.

## What I built

**Push: Today tab**
- **A digest you can trust to stay short.** Pick a window (24h, 3d, 7d or 30d). Every NSE filing across the portfolio in that window is classified, and the material ones are grouped *by company*. So "TATAPOWER: results + 1,800 MW capacity addition + 3.7× volume on Thursday" reads as one story, not three rows. Routine paperwork (171 of the 208 portfolio filings in the last 30 days) collapses into one line. If the window is empty, for example on a weekend, it shows the latest filing day and says so.
- **Your thresholds.** A volume spike above N× the 20-day average and a price move beyond ±X% are both set in a bottom sheet. Saving re-checks the portfolio immediately.
- **Results card.** Revenue, EBITDA, PBT and PAT, QoQ and YoY, plus the margin change, for every results filing. ASTRAL is the example worth opening: revenue +26% YoY, PAT −6%, EBITDA margin −3.2 pts, on the same day the stock fell 9.7% on 13× volume.
- **Management change.** FINN reads the actual filing PDF to get who is joining or leaving, their role, and the SEBI-mandated brief profile, quoted verbatim. Example: "Prithvi Vachani joins Dixon as Executive Director… a 2017 graduate of Bentley University". FINN then notices that Rohan Mehta in your network studied at Bentley from 2013 to 2017, so the two likely overlapped.
- **Material event → who to call.** For M&A, capex, fund raises and litigation: the contact best placed to give context, and why ("Ex-Astral sales 2012–19, now at competitor Supreme").

**Pull: any NSE ticker, from Ask or by tapping a company**
- A snapshot, the latest quarter, a six-year trajectory (CAGRs and margin drift), the balance sheet and working-capital cycle, and cash conversion (CFO/EBITDA over 5 years).
- **Promised vs delivered.** Explicit numeric guidance is pulled from the last four earnings-call transcripts, quoted verbatim with a page link, and checked in code against the reported quarters. ASTRAL guided a 16–18% EBITDA margin and is delivering 13.8% in H1 FY27, so it's behind. Its 20%+ growth guidance is on track at 21.4%. Segment-level targets are kept but deliberately *not* scored against company totals.
- **Ask the company's own calls.** On any company page, or in the Ask tab ("What did ASTRAL say about PVC prices?"):
  - Keyword relevance search (BM25) over that company's last four transcripts picks the most relevant pages.
  - Gemini 3.5 Flash answers **only** from those pages, and must cite each claim with a verbatim quote and the call and page.
  - **Code then checks every quote word-for-word against the cited page** and drops any it can't find. An answer with no verified quote is replaced by the raw passages.
  - Ask it something the transcripts don't cover and it says so, rather than answering from memory.
  - Without a key, it shows the best-matching passages verbatim.
- **Bull and bear facts.** Each side is a short list of facts derived from the numbers above, not prose.
- Sources are listed with links. Pull uses only primary documents: exchange-filed results (as standardised by screener.in), company transcripts and annual reports.
- **It generalises.** An unseen ticker is resolved lazily: company metadata from Yahoo, financials and document links from screener, then the transcripts are read. It takes a few seconds the first time and is cached after that.

**Network: People tab, and inside every card**
- **Who should I call** about a company: worked there, at a competitor (same industry), in the sector, or knows the theme. Current employees are flagged ("good for context, not for non-public information").
- **Second-degree reach.** If the best person isn't your contact, FINN shows who can introduce you and why ("Omkar Patil, Astral plant manager, via Devika Shah, who overlapped with him at Astral 2018–19").
- **Diligence on a person from a filing.** "Who can introduce me to Prithvi Vachani?" returns his profile from the filing and your paths to him.
- **Expertise map.** A themes cloud across the network; tap "specialty chemicals" to see your go-to people.
- **Keep the network warm.** Contacts you haven't spoken to in more than 4 months whose employer or ex-employer just filed something material. For example, Vikram Sethi (ex-HDFC Bank SME banking, 9 months quiet) and HDFC Bank's new Chief Compliance Officer.

## Key decisions and tradeoffs

1. **Code computes numbers; models only read and explain.** QoQ/YoY, margins, CAGRs, guidance hit-or-miss and network scores are all deterministic Python. This makes the output checkable, cheap and free of hallucinated figures, which matters most in a product that tells someone to act.
2. **Rules first, model second.** Keyword rules on NSE's own subject label place **~87% of filings** into the reference categories, with a 1–5 materiality score, at zero cost. Only the ambiguous ~13% ("General Updates", "Press Release") go to the cheap model, batched 20 per call and cached by prompt hash. The same pattern applies to PDF extraction and guidance mining.
3. **Honest about what a rule can't know.** Guidance quotes always show the page, segment-level targets are labelled rather than scored, missing profiles say "No profile in the filing", and an empty window says it widened.
4. **Grouping by company, not by filing.** An investor thinks in names, not in disclosure types.
5. **The network infers links to real people; it never asserts them.** "Likely overlapped" is based on the same employer at the same time, or the same school in years the filing itself states.

**What the models actually cost.**
- Rules classified 594 of 681 filings (87%) for free.
- The remaining 87 went to the cheap tier, **Gemini 3.5 Flash Lite on Google's free tier**: 5 batched calls, about 14k tokens in total, **$0**. Each call is cached by prompt hash, so a re-run costs nothing.
- The strong tier is configured but optional: the product works fully without it, because every number is computed in code.
- Providers are swappable through `.env` (Gemini, or Claude Haiku/Opus through the official SDK), and every call is logged with tokens and cost in `llm_calls`.
- Only public filing text is ever sent to a model, never network data. That matters on a free tier, where prompts may be used for training.

## Architecture

```
            ┌───────────── ingestion (batch, after close; lazy for unseen tickers) ─────────────┐
 yfinance ──► prices ──► rule engine (user thresholds) ─────────────────────────┐              │
 NSE API ───► announcements ─► rules ─► (cheap LLM for the ambiguous ~13%) ─────┤              │
              └─ filing PDFs ─► people / roles / profiles / key line ────────────┤ SQLite (dev) │
 screener ──► quarterly + annual financials, document links ─► results cards ───┤ Postgres     │
              └─ transcripts (PDF, per page) ─► guidance quotes ─► vs actuals ──┤ (prod)       │
 investor ──► contacts, careers, schools, expertise  (owner-scoped) ────────────┘              │
            └────────────────────────────────────────────────────────────────────────────────┘
                                   │
               FastAPI (feed · research · network · ask) ── per-request network join
                                   │
               React PWA (Today · Ask · People) — served by the same process, one URL
```

**Data pipelines**
- Prices: one batched yfinance call per run, upserted.
- Filings: one polite NSE request per ticker per run, merged into committed JSON snapshots that serve as the fallback.
- Fundamentals: lazy per ticker with a 24h freshness check.
- Everything is idempotent: unique keys on (exchange, ref), (company, period), (user, alert dedupe key).
- **Linking:** company names are normalised (suffixes and punctuation stripped) to match employers and peers. Filing people are matched to the network through (a) same company with overlapping tenure, (b) organisations or schools named in the filing text, with years checked, and (c) explicit person links for introductions.

**Security and privacy**
- Every network row (people, careers, contacts, links, interactions) carries an `owner_id`. Network results are computed **per request** and never written onto shared rows, so the announcements and companies tables hold only public data.
- Profiles of people FINN only knows from filings get an `expires_at`, so they're re-derived rather than hoarded. Contacts carry a `consent_status`.
- A real deployment would add authenticated sessions (the `current_user` dependency is the single choke point), row-level security in Postgres keyed on `owner_id`, encryption at rest, and per-user export and delete.
- **Network data here is synthetic and labelled synthetic in the UI.** For real use: the investor's own contact import (CSV or vCard), LinkedIn only through the user's own authorised data export or an approved partner API, and no scraping.

**LLMs and agents**
- Cheap tier (Gemini 3.5 Flash Lite, free): classification and one-liners for the filings rules can't place, batched 20 per call, with structured JSON output and retries.
- Strong tier (Gemini 3.5 Flash, free): grounded company Q&A only. Each call is about 3k input tokens and runs only when the investor asks.
- Validation before caching: a truncated or malformed model reply is never stored, and a corrupt cache entry heals itself. I learned this the hard way when a thinking model ran out of output tokens.
- Strong tier: Pull interpretation only.
- No autonomous agents: the "Ask" router is deterministic, so it's instant and free, and a model only parses intent when a key exists. I chose predictable tools over an agent loop because every answer here is a lookup plus arithmetic.

**Cloud**
- One Docker image (FastAPI plus the built PWA) on Render's free tier, Singapore region. It boots from a committed demo database so the review never depends on NSE, Yahoo or screener being reachable.
- In production: managed Postgres, a scheduled job after market close for ingestion, object storage for the PDF cache, and push notifications through Web Push.

## What I deliberately left out
- Real push notifications. Alerts are generated and deduplicated; delivery is the next step.
- BSE as a source. BSE's API refuses automated clients, so I didn't work around it.
- Voice input and a chat transcript UI. Answers are cards, not paragraphs, by design.
- Model-written bull and bear prose. Facts come first; the strong model is reserved for questions the investor actually asks.

## Where I'd take it next
1. Use the cheap model to refine guidance extraction and person extraction too. The rule pass already narrows each transcript to a few candidate sentences, so this costs a few hundred tokens per company.
2. An after-close cron job plus Web Push for threshold alerts.
3. Track guidance as a time series: did they change the number, and did they say so?
4. A real contact import plus calendar and email metadata, so "last spoke" maintains itself.

## AI build history
Built with Claude Code. The full session (planning, the course-corrections listed below, and what I accepted or rewrote) is exported alongside this note.

Course-corrections during the build:
- **Data source:** BSE blocked automated access, so I switched to NSE.
- **Classification bug:** a regulatory list of who may make disclosures was being labelled a management change. Caught by reading the PDF.
- **Guidance scoring:** segment-level targets were being scored against company totals, so I added scope detection.
- **Results period bug:** NSE's "September 30, 2026" date format was being missed. Caught by a test.
- **Network false matches:** generic employers like "Independent" were matching "Independent Director" in filings.
