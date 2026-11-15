"""Name normalisation: the glue for matching filings ↔ companies ↔ people."""

import re

_HONORIFICS = r"\b(mr|mrs|ms|dr|shri|smt|kum|prof|ca|cs)\b\.?"
_COMPANY_SUFFIXES = (
    r"\b(limited|ltd|private|pvt|incorporated|inc|corporation|corp|company|co|llp|plc)\b\.?"
)


def _squash(s: str) -> str:
    s = re.sub(r"[^\w\s&]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_person_name(name: str) -> str:
    s = name.lower()
    s = re.sub(_HONORIFICS, " ", s)
    return _squash(s)


def normalize_org_name(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(_COMPANY_SUFFIXES, " ", s)
    s = re.sub(r"\bthe\b", " ", s)
    return _squash(s)
