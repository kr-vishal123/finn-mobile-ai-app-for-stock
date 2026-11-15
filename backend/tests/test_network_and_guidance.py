"""Pure-logic tests for the parts that turn text into claims: guidance parsing, verdicts,
filing-person extraction, and the result-period parser."""

from datetime import date

from app.models.enums import GuidanceStatus
from app.services.filing_text import extract_management, subject_line
from app.services.fundamentals import discussed_quarter, fy_label
from app.services.guidance import _target_fy, _value, find_promises, verdict
from app.services.results import period_from_text


def test_fiscal_labels():
    assert fy_label(date(2026, 9, 30), True) == "Q2FY27"
    assert fy_label(date(2026, 3, 31), False) == "FY26"
    assert discussed_quarter(date(2026, 11, 30)) == date(2026, 9, 30)
    assert discussed_quarter(date(2026, 2, 28)) == date(2025, 12, 31)


def test_guidance_values():
    assert _value("we expect EBITDA margin of 16% to 18%", "ebitda_margin")[1:] == (16.0, 18.0)
    assert _value("revenue growth in the mid-teens", "revenue_growth")[1:] == (14, 16)
    assert _value("capex of INR 1,000 crores next year", "capex")[1] == 1000.0
    assert _target_fy("we target this by 2030", 27) == 30
    assert _target_fy("next year we expect", 2027) == 28


def test_find_promises_skips_questions_and_segments():
    pages = ["cover", "Can you give guidance on 15% growth for FY27? "
             "We are targeting revenue growth of 15% to 18% for FY27 as a whole company. "
             "Our guidance for the paints segment is EBITDA margins of 8% to 10% this year."]
    got = {p["metric"]: p for p in find_promises(pages, 2027)}
    assert got["revenue_growth"]["low"] == 15 and got["revenue_growth"]["scope"] == "company"
    assert got["ebitda_margin"]["scope"] == "segment"


def test_verdicts():
    assert verdict(16, 18, 13.8, False)[0] == GuidanceStatus.missed
    assert verdict(20, 25, 21.4, False)[0] == GuidanceStatus.partial
    assert verdict(10, 10, 19.0, True)[0] == GuidanceStatus.met


def test_extract_management_from_letter():
    letter = ("Letterhead Sub: Change in management Dear Sir/Madam, We wish to inform you that Mr. Ravi Kumar Sharma "
              "has been appointed as Chief Financial Officer of the Company with effect from 1 November 2026. "
              "Ms. Anita Desai has resigned as Company Secretary. Yours faithfully, For X Limited "
              "Annexure Brief profile: Mr. Ravi Kumar Sharma is a Chartered Accountant with 22 years of experience "
              "in finance at Y Limited.")
    people = {p["name"]: p for p in extract_management(letter)}
    assert people["Ravi Kumar Sharma"]["direction"] == "joining"
    assert "Chief Financial Officer" in people["Ravi Kumar Sharma"]["role"]
    assert people["Ravi Kumar Sharma"]["profile"].startswith("Mr. Ravi Kumar Sharma is a Chartered")
    assert people["Anita Desai"]["direction"] == "leaving"


def test_subject_line_and_period():
    assert subject_line("Dear Sirs, Re : L&T bags (Significant*) order from Noida Metro We enclose herewith") \
        == "L&T bags (Significant*) order from Noida Metro"
    assert period_from_text("financial results for the period ended September 30, 2026") == date(2026, 9, 30)
    assert period_from_text("results for the quarter and half year ended 30th September, 2026") == date(2026, 9, 30)
