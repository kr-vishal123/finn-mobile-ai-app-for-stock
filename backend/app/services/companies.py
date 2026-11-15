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

    info: dict = {}
    try:
        info = yf.Ticker(f"{symbol}.NS").info or {}
    except Exception:  # Yahoo often blocks cloud IPs: fall back to screener below
        info = {}
    name = info.get("longName") or info.get("shortName")
    sector, industry = info.get("sector"), info.get("industry")
    if not name:
        ident = screener_identity(symbol)
        if ident is None:
            return None
        name, sector, industry = ident
    company = upsert_company(db, symbol, name, sector, industry)
    if info.get("marketCap"):
        company.market_cap_cr = info["marketCap"] / 1e7
    db.commit()
    return company


def screener_identity(symbol: str) -> tuple[str, str | None, str | None] | None:
    """Name, sector and industry from the company's screener page (fallback resolver)."""
    import httpx
    from bs4 import BeautifulSoup

    from app.config import get_settings

    s = get_settings()
    try:
        r = httpx.get(f"{s.screener_base_url}/company/{symbol}/", headers={"User-Agent": s.http_user_agent},
                      timeout=30, follow_redirects=True)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
    except httpx.HTTPError:
        return None
    h1 = soup.find("h1")
    if h1 is None:
        return None
    tags = {a.get("title"): a.get_text(strip=True) for a in soup.select("#peers a[title]")}
    return h1.get_text(strip=True), tags.get("Broad Sector") or tags.get("Sector"), tags.get("Industry")
