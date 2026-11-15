from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AlertRuleType, AnnouncementCategory, Priority, WatchlistKind


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyOut(ORM):
    id: int
    nse_symbol: str | None
    name: str
    sector: str | None
    industry: str | None
    market_cap_cr: float | None


class WatchlistItemOut(ORM):
    id: int
    kind: WatchlistKind
    weight_pct: float | None
    company: CompanyOut


class FeedItem(BaseModel):
    id: int
    symbol: str
    company_name: str
    published_at: datetime
    category: AnnouncementCategory | None
    priority: Priority | None
    materiality: float | None
    headline: str
    one_liner: str | None
    exchange_category: str | None
    attachment_url: str | None
    enrichment: dict | None = None
    network: list[dict] | None = None  # per-user, computed at request time


class SignalItem(BaseModel):
    id: int
    symbol: str
    company_name: str
    kind: str
    priority: Priority
    trade_date: date | None
    title: str
    body: str | None
    payload: dict | None


class RoutineGroup(BaseModel):
    category: AnnouncementCategory | None
    count: int
    items: list[FeedItem]


class Feed(BaseModel):
    since: datetime
    until: datetime
    requested_hours: int
    note: str | None = None  # set when the window was widened
    counts: dict[str, int]
    signals: list[SignalItem]
    material: list[FeedItem]
    routine: list[RoutineGroup]


class AlertOut(ORM):
    id: int
    company_id: int
    announcement_id: int | None
    priority: Priority
    title: str
    body: str | None
    payload: dict | None
    created_at: datetime
    seen_at: datetime | None


class AlertRuleOut(ORM):
    id: int
    rule_type: AlertRuleType
    company_id: int | None
    params: dict
    enabled: bool


class AlertRuleIn(BaseModel):
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class FinancialPeriodOut(ORM):
    label: str
    period_end: date
    revenue: float | None
    ebitda: float | None
    pbt: float | None
    pat: float | None
