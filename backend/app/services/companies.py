from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.services.normalize import normalize_org_name


def upsert_company(
    db: Session,
    symbol: str,
    name: str,
    sector: str | None = None,
    industry: str | None = None,
) -> Company:
    symbol = symbol.upper().strip()
    company = db.scalar(select(Company).where(Company.nse_symbol == symbol))
    if company is None:
        company = Company(nse_symbol=symbol, name=name, name_normalized=normalize_org_name(name))
        db.add(company)
    company.name = name
    company.name_normalized = normalize_org_name(name)
    company.sector = sector or company.sector
    company.industry = industry or company.industry
    company.screener_slug = company.screener_slug or symbol
    db.flush()
    return company


def ensure_company(db: Session, symbol: str) -> Company | None:
    """Resolve any NSE symbol, creating the row on first sight (lazy, so unseen tickers work).
    Name/sector come from Yahoo's metadata; returns None if the symbol doesn't exist."""
    symbol = symbol.upper().strip()
    company = db.scalar(select(Company).where(Company.nse_symbol == symbol))
    if company is not None:
        return company
    import yfinance as yf

    try:
        info = yf.Ticker(f"{symbol}.NS").info or {}
    except Exception:
        return None
    name = info.get("longName") or info.get("shortName")
    if not name:
        return None
    company = upsert_company(db, symbol, name, info.get("sector"), info.get("industry"))
    if info.get("marketCap"):
        company.market_cap_cr = info["marketCap"] / 1e7
    db.commit()
    return company
