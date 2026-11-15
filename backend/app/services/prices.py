"""EOD price ingestion from Yahoo Finance (one batched request for all tickers)."""

import logging
import math
import warnings

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Company, IngestionRun, PriceBar
from app.services.upsert import upsert_rows

log = logging.getLogger(__name__)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def ingest_prices(db: Session, companies: list[Company], period: str = "1y") -> dict:
    import yfinance as yf

    run = IngestionRun(source="prices")
    db.add(run)
    db.flush()
    by_ticker = {c.yf_ticker: c for c in companies if c.yf_ticker}
    stats: dict = {"tickers": len(by_ticker), "rows": 0, "missing": []}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(
                list(by_ticker), period=period, interval="1d", group_by="ticker",
                progress=False, auto_adjust=False, threads=True,
            )
        for ticker, company in by_ticker.items():
            if ticker not in df.columns.get_level_values(0):
                stats["missing"].append(ticker)
                continue
            frame = df[ticker].dropna(subset=["Close"])
            rows = [
                {
                    "company_id": company.id,
                    "trade_date": idx.date(),
                    "open": _num(r["Open"]),
                    "high": _num(r["High"]),
                    "low": _num(r["Low"]),
                    "close": float(r["Close"]),
                    "adj_close": _num(r.get("Adj Close")),
                    "volume": int(_num(r["Volume"]) or 0),
                }
                for idx, r in frame.iterrows()
            ]
            if not rows:
                stats["missing"].append(ticker)
            upsert_rows(
                db, PriceBar, rows, ["company_id", "trade_date"],
                ["open", "high", "low", "close", "adj_close", "volume"],
            )
            stats["rows"] += len(rows)
        run.status = "ok"
    except Exception as e:  # keep the run log honest
        log.exception("price ingestion failed")
        run.status, run.error = "failed", str(e)
    run.finished_at, run.stats = utcnow(), stats
    db.commit()
    return stats
