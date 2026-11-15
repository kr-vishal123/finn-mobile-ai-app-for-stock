from enum import Enum


class AnnouncementCategory(str, Enum):
    """From the ENAM reference doc. Kept as-is so the classifier output maps 1:1."""

    results = "results"
    m_and_a = "m_and_a"
    fund_raise = "fund_raise"
    management_change = "management_change"
    litigation = "litigation"
    insider_trading = "insider_trading"
    earnings_call = "earnings_call"
    investor_meetings = "investor_meetings"
    credit_rating = "credit_rating"
    dividend = "dividend"
    bonus_split = "bonus_split"
    capex = "capex"
    press_release = "press_release"
    postal_ballot = "postal_ballot"
    agm_egm = "agm_egm"
    pledging = "pledging"
    unclassified = "unclassified"


class Priority(str, Enum):
    """How the Push feed treats an item: surface, show compactly, or collapse."""

    high = "high"      # card with enrichment (results numbers, bio, who-to-call)
    medium = "medium"  # one-line summary
    low = "low"        # collapsed under "routine"


class WatchlistKind(str, Enum):
    portfolio = "portfolio"
    research = "research"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class PeriodType(str, Enum):
    quarter = "quarter"
    annual = "annual"


class DocType(str, Enum):
    annual_report = "annual_report"
    concall_transcript = "concall_transcript"
    investor_presentation = "investor_presentation"
    results_filing = "results_filing"
    other = "other"


class ProfileSource(str, Enum):
    """Where a person's profile came from — shown in the UI and the writeup."""

    synthetic = "synthetic"          # mock data for the demo
    user_provided = "user_provided"  # investor typed / imported it
    filing = "filing"                # extracted from an exchange announcement
    public_profile = "public_profile"


class RelationshipType(str, Enum):
    colleague = "colleague"
    classmate = "classmate"
    friend = "friend"
    met_management = "met_management"  # company / management met in meetings
    industry = "industry"
    family = "family"
    other = "other"


class AlertRuleType(str, Enum):
    announcement_category = "announcement_category"  # params: {categories: [...]}
    volume_spike = "volume_spike"                    # params: {multiple, lookback_days}
    price_move = "price_move"                        # params: {pct}


class GuidanceStatus(str, Enum):
    pending = "pending"
    met = "met"
    missed = "missed"
    partial = "partial"
    withdrawn = "withdrawn"
