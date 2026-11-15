"""Pure-function tests: threshold checks and the rules-based announcement classifier.
Classifier cases are real NSE subject/text pairs seen in the demo snapshots."""

import pytest

from app.models.enums import AnnouncementCategory as Cat
from app.services.announcements import clean_text, priority_for, rule_classify
from app.services.rules import pct_change, volume_ratio


def test_volume_ratio():
    vols = [100] * 20 + [250]
    assert volume_ratio(vols, 20) == pytest.approx(2.5)
    assert volume_ratio(vols[:10], 20) is None  # not enough history
    assert volume_ratio([0] * 20 + [5], 20) is None  # no base volume


def test_pct_change():
    assert pct_change([100, 95]) == pytest.approx(-5.0)
    assert pct_change([100]) is None


@pytest.mark.parametrize("subject,text,cat,min_m", [
    ("Outcome of Board Meeting", "X Ltd has submitted to the Exchange, the financial results for the period ended September 30, 2026", Cat.results, 4),
    ("Change in Management", "X Ltd has informed the Exchange about change in Management", Cat.management_change, 3),
    ("Acquisition", "X Ltd has informed the Exchange about Acquisition", Cat.m_and_a, 4),
    ("Acquisition", "Incorporation of wholly owned subsidiary", Cat.m_and_a, 2),
    ("Outcome of Board Meeting", "Outcome of Board Meeting held on October 01, 2026 - Capital raise through QIP and Preferential Issue", Cat.fund_raise, 4),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "X Ltd has informed the Exchange about Transcript", Cat.earnings_call, 2),
    ("Trading Window", "Trading Window closure", Cat.unclassified, 1),
    ("General Updates", "Analyst(s)/Investor(s) meet", Cat.investor_meetings, 1),
    ("Action(s) taken or orders passed", "adjudication order from the Office of the Collector of Stamps", Cat.litigation, 3),
    ("Retirement", "Retirement of Mr. Noel N. Tata as Director and Vice-Chairman", Cat.management_change, 2),
])
def test_rule_classify(subject, text, cat, min_m):
    got = rule_classify(subject, text)
    assert got is not None
    assert got[0] == cat
    assert got[1] >= min_m


def test_rule_classify_defers_ambiguous_to_model():
    assert rule_classify("Updates", "Infosys collaborates with Knorr Bremse on AI transformation") is None


def test_clean_text_and_priority():
    assert clean_text("Infosys Limited has informed the Exchange regarding 'Six Researchers Win'") == "Six Researchers Win"
    assert priority_for(5).value == "high" and priority_for(3).value == "medium" and priority_for(1).value == "low"
