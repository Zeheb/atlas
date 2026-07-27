"""Unit tests for atlas.analysis.financial_results.

Synthetic fixtures mirror the structure of real BSE Reg 33 filings:
- Cover letter with period, dividend, record/payment dates
- BSR auditor's report with "unmodified audit opinion"
- Consolidated P&L table (6-column quarterly, 5-column annual)
- Consolidated segment revenue table
- Standalone P&L table
- Notes referencing exceptional items

Tests do NOT use real PDFs (those live in integration tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from unittest.mock import MagicMock

import pytest

from atlas.analysis.financial_results import (
    ANALYZER_VERSION,
    _detect_filing,
    _detect_n_cols,
    _extract_balance_sheet_facts,
    _extract_banking_facts,
    _extract_cashflow_facts,
    _extract_eps_facts,
    _extract_n_values,
    _extract_pl_facts,
    _extract_segment_ebit_facts,
    _extract_segment_facts,
    _find_bs_region,
    _find_cf_region,
    _find_pl_regions,
    _fix_ocr_numbers,
    _is_banking_filing,
    _parse_number,
    _primary_col,
    analyze,
)
from atlas.analysis.patterns import extract_dividend_facts as _extract_dividend_facts
from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.knowledge.base import KnowledgeBase, ParsedDocument

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    evidence_id: str = "fr-001",
    status: Literal["ok", "failed"] = "ok",
    char_count: int | None = 20_000,
    source_date: str = "2024-10-10",
    kind: str = "financial_results",
) -> ParsedDocument:
    return ParsedDocument(
        evidence_id=evidence_id,
        kind=kind,
        title="Financial Results Q2 FY2025",
        source_date=source_date,
        local_path="financial_results/fr-001.pdf",
        parsed_at=datetime(2024, 10, 10, tzinfo=timezone.utc),
        parser_version="1.0",
        status=status,
        error=None,
        char_count=char_count,
    )


def _make_kb(doc: ParsedDocument, content: str | None) -> KnowledgeBase:
    kb = MagicMock(spec=KnowledgeBase)
    kb.get.return_value = doc
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


def _con_facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [
        f
        for f in result.facts
        if f.kind == kind and "consolidated" in f.provenance.section
    ]


def _sa_facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [
        f
        for f in result.facts
        if f.kind == kind and "standalone" in f.provenance.section
    ]


# ---------------------------------------------------------------------------
# Synthetic document builders
# ---------------------------------------------------------------------------

_COVER_QUARTERLY = """\
TCS/BM/154/SE/2024-25

October 10, 2024

Dear Sirs,

Sub: Financial Results for the quarter and six-month period ended September 30, 2024, and
declaration of second interim dividend

We enclose the audited standalone financial results of the Company and audited consolidated
financial results of the Company and its subsidiaries for the quarter and six-month period
ended September 30, 2024, under Ind AS.

We would like to inform you that the Directors have declared second interim dividend of INR 10
per Equity Share of INR 1 each of the Company.

The second interim dividend shall be paid on Tuesday, November 5, 2024, to the equity
shareholders of the Company whose names appear on the Register of Members as on Friday,
October 18, 2024, which is the Record Date fixed for the purpose.

Yours faithfully,
For Tata Consultancy Services Limited

"""

_AUDIT_SECTION = """\
B S R & Co. LLP
Chartered Accountants

To the Board of Directors of Tata Consultancy Services Limited
Report on the audit of the Consolidated Financial Results

Opinion
We have audited the accompanying Statement of Consolidated Financial Results.
In our opinion the Statement gives a true and fair view.

The statutory auditors have expressed an unmodified audit opinion on these results.

"""

_CONSOLIDATED_PL_6COL = """\
Year ended
September 30, June 30, September 30, September 30, September 30, March 31,
2024         2024     2023          2024          2023          2024
Revenue from operations
               64,259
62,613
59,692
1,26,872
1,19,073
2,40,893
Other income
                    729
962
1,006
1,691
2,403
4,422
TOTAL INCOME
               64,988
63,575
60,698
1,28,563
1,21,476
2,45,315
Expenses
Employee benefit expenses
               36,654
36,416
35,123
73,070
70,271
1,40,131
Cost of equipment and software licences
                 3,230
2,151
462
5,381
968
3,702
Finance costs
                    162
173
159
335
322
778
Depreciation and amortisation expense
                 1,266
1,220
1,263
2,486
2,506
4,985
Other expenses
                 7,644
7,384
8,361
15,028
17,090
32,764
TOTAL EXPENSES
               48,956                47,344                45,368                96,300                91,157
1,82,360
PROFIT BEFORE EXCEPTIONAL ITEM AND TAX
16,032
16,231
15,330
32,263
30,319
62,955
Exceptional item
Settlement of legal claim
                      -                         -                         -                         -                         -                       958
PROFIT BEFORE TAX
               16,032                16,231                15,330                32,263                30,319                61,997
Tax expense
Current tax
                 4,078
4,290
3,955
8,368
7,823
15,864
Deferred tax
                      (1)                   (164)                       (5)                   (165)                       (4)                       34
TOTAL TAX EXPENSE
                 4,077                  4,126                  3,950                  8,203                  7,819                15,898
PROFIT FOR THE PERIOD
               11,955                12,105                11,380                24,060                22,500                46,099
"""

_EPS_DIVIDEND_SECTION = """\
Earnings per equity share:- Basic and diluted ( )
                 32.92                  33.28                  31.00                  66.20                  61.26                125.88
Dividend per share (Par value 1 each)
Interim dividend on equity shares ( )
                 10.00                  10.00                    9.00                  20.00                  18.00                  45.00
Final dividend on equity shares ( )
                      -                         -                         -                         -                         -                    28.00
Total dividend on equity shares ( )
                 10.00                  10.00                    9.00                  20.00                  18.00                  73.00
"""

_SEGMENT_TABLE = """\
SEGMENT REVENUE
Banking, Financial Services and Insurance
23,785
23,074
22,840
46,859
45,502
90,928
Manufacturing
6,310
6,271
5,787
12,581
11,423
23,491
Consumer Business
10,025
9,991
9,773
20,016
19,649
39,357
Communication, Media and Technology
12,088
10,794
9,572
22,882
19,168
39,391
Life Sciences and Healthcare
6,630
6,909
6,625
13,539
13,261
26,745
Others
5,421
5,574
5,095
10,995
10,070
20,981
Total
64,259
62,613
59,692
1,26,872
1,19,073
2,40,893
SEGMENT RESULT
Banking, Financial Services and Insurance
6,345
6,011
5,861
12,356
11,318
23,574
Manufacturing
2,063
1,988
1,780
4,051
3,519
7,239
Consumer Business
2,695
2,755
2,676
5,450
5,318
10,723
Communication, Media and Technology
2,357
2,203
1,837
4,560
3,613
7,474
Life Sciences and Healthcare
1,849
2,016
1,892
3,865
3,756
7,656
Others
1,422
1,543
1,380
2,965
2,729
5,708
Total
16,731
16,516
15,426
33,247
30,253
62,374
Unallocable expenses*
1,428
1,403
1,231
2,831
2,399
4,914
Operating income
15,303
15,113
14,195
30,416
27,854
57,460
"""

_BALANCE_SHEET_STUB = """\
As at September 30, 2024
ASSETS
Non-current assets
Property, plant and equipment
9,438
"""

_STANDALONE_PL_6COL = """\
Audited Standalone Interim Statement of Financial Results

Year ended
September 30, June 30, September 30, September 30, September 30, March 31,
2024         2024     2023          2024          2023          2024
Revenue from operations
               53,990
52,844
50,165
1,06,834
1,00,027
2,02,359
Other income
                    654
780
820
1,434
1,600
3,100
TOTAL INCOME
               54,644
53,624
50,985
1,08,268
1,01,627
2,05,459
Expenses
Employee benefit expenses
               28,500
28,000
27,000
56,500
54,000
1,08,000
Cost of equipment and software licences
                 2,900
2,000
400
4,900
820
3,200
Finance costs
                    150
160
140
310
280
650
Depreciation and amortisation expense
                 1,100
1,050
1,080
2,150
2,160
4,300
Other expenses
                 6,500
6,200
7,000
12,700
14,500
27,000
TOTAL EXPENSES
               39,150                37,410                35,620                76,560                71,760              1,43,150
PROFIT BEFORE EXCEPTIONAL ITEM AND TAX
15,494
16,214
15,365
31,708
29,867
62,309
PROFIT BEFORE TAX
               15,494                16,214                15,365                31,708                29,867                62,309
Tax expense
Current tax
                 3,900
4,100
3,800
8,000
7,500
15,200
Deferred tax
                      (5)                   (100)                       (3)                   (105)                       (2)                       20
TOTAL TAX EXPENSE
                 3,895                  4,000                  3,797                  7,895                  7,498                15,220
PROFIT FOR THE PERIOD
               11,599                12,214                11,568                23,813                22,369                47,089
"""

_STANDALONE_EPS = """\
Earnings per equity share:- Basic and diluted ( )
                 35.91                  33.48                  29.87                  69.40                  58.52                119.44
"""

_STANDALONE_BALANCE_SHEET = """\
As at September 30, 2024
ASSETS
Non-current assets
Property, plant and equipment
8,413
"""

_NOTES_SECTION = """\
Select explanatory notes to the Statement of Audited Consolidated Interim Financial Results
1. These results have been reviewed by the Audit Committee and approved by the Board of Directors.
   The statutory auditors have expressed an unmodified audit opinion on these results.
2. The Board of Directors has declared an interim dividend of 10.00 per equity share.
"""


def _build_quarterly_filing() -> str:
    return (
        _COVER_QUARTERLY
        + _AUDIT_SECTION
        + _CONSOLIDATED_PL_6COL
        + _EPS_DIVIDEND_SECTION
        + _SEGMENT_TABLE
        + _BALANCE_SHEET_STUB
        + _STANDALONE_PL_6COL
        + _STANDALONE_EPS
        + _STANDALONE_BALANCE_SHEET
        + _NOTES_SECTION
    )


_COVER_ANNUAL = """\
TCS/BM/155/SE/2025-26

April 9, 2026

Dear Sirs,

Sub: Financial Results for the year ended March 31, 2026 and Recommendation of Final Dividend

We enclose the audited standalone financial results of the Company and audited consolidated
financial results for the year ended March 31, 2026 under Ind AS.

The Board has recommended a final dividend of INR 31 per Equity Share.

Yours faithfully,
For Tata Consultancy Services Limited

"""

_CONSOLIDATED_PL_5COL = """\
Three months ended    Year ended
March 31, December 31, March 31, March 31, March 31,
2026      2025         2025      2026      2025
Revenue from operations
           70,698
67,087
64,479
         2,67,021
2,55,324
Other income
                757
1,118
1,028
             4,402
3,962
TOTAL INCOME
           71,455
68,205
65,507
         2,71,423
2,59,286
Expenses
Employee benefit expenses
           40,143
38,530
36,762
         1,54,994
1,45,788
Cost of equipment and software licences
             1,444
1,262
2,748
             4,399
11,648
Finance costs
                265
538
227
             1,227
796
Depreciation and amortisation expense
             1,406
1,380
1,379
             5,560
5,242
Other expenses
             9,835
9,026
7,989
           35,230
30,481
TOTAL EXPENSES
           53,093            50,736            49,105          2,01,410
        1,93,955
PROFIT BEFORE EXCEPTIONAL ITEMS AND TAX
18,362
17,469
16,402
70,013
65,331
Exceptional items
Re-structuring expenses
                  -                  253
                  -               1,388
                  -
Statutory impact of new Labour Codes
                  -               2,128
                  -               2,128
                  -
PROFIT BEFORE TAX
           18,362            14,078            16,402            65,487
          65,331
Tax expense
Current tax
             4,832
3,424
4,325
           16,388
16,910
Deferred tax
              (240)
(181)
(218)
              (910)
(600)
TOTAL TAX EXPENSE
             4,592                3,243                4,107            15,478
          16,310
PROFIT FOR THE YEAR
           13,770            10,835            12,295            50,009
          49,021
"""

_ANNUAL_EPS = """\
Earnings per equity share:- Basic and diluted ( )
              40.15                28.16               30.72             135.70            132.83
"""

_ANNUAL_BALANCE_SHEET = """\
As at March 31, 2026

ASSETS
Non-current assets
Property, plant and equipment
10,500
8,200

Current assets
Cash and cash equivalents
6,417
8,342
Trade receivables
24,000
22,000

EQUITY AND LIABILITIES
Equity attributable to shareholders of the Company
1,07,240
94,756
Non-controlling interests
700
650

CASH FLOWS FROM OPERATING ACTIVITIES
Net cash generated from operating activities
52,094
48,908

CASH FLOWS FROM INVESTING ACTIVITIES
Payment for purchase of property, plant and equipment
               (3,670)                (2,917)

"""

_STANDALONE_PL_5COL = """\
Audited Standalone Statement of Financial Results

Three months ended  Year ended
March 31, December 31, March 31, March 31, March 31,
2026      2025         2025      2026      2025
Revenue from operations
58,052
55,567
54,136
2,18,000
2,06,000
Other income
3,516
2,049
1,922
11,000
9,000
TOTAL INCOME
61,568
57,616
56,058
2,29,000
2,15,000
Expenses
Employee benefit expenses
28,630
27,842
27,215
1,12,000
1,05,000
Cost of equipment and software licences
1,118
960
2,673
4,000
9,000
Finance costs
238
512
201
1,100
750
Depreciation and amortisation expense
944
1,102
1,118
4,100
4,400
Other expenses
12,174
11,071
10,179
44,000
39,000
TOTAL EXPENSES
43,104
41,487
41,386
1,65,200
1,58,150
PROFIT BEFORE EXCEPTIONAL ITEMS AND TAX
18,464
16,129
14,672
63,800
56,850
PROFIT BEFORE TAX
18,464
16,129
14,672
63,800
56,850
Tax expense
Current tax
4,178
2,903
3,774
15,000
13,800
Deferred tax
(240)
(181)
(218)
(800)
(600)
TOTAL TAX EXPENSE
3,938
2,722
3,556
14,200
13,200
PROFIT FOR THE YEAR
14,526
13,407
11,116
49,600
43,650
"""

_STANDALONE_EPS_5COL = """\
Earnings per equity share:- Basic and diluted ( )
              45.00                38.00               34.00             150.00            128.00
"""

_STANDALONE_BALANCE_SHEET_5COL = """\
As at March 31, 2026
ASSETS
Non-current assets
"""


def _build_annual_filing() -> str:
    return (
        _COVER_ANNUAL
        + _AUDIT_SECTION
        + _CONSOLIDATED_PL_5COL
        + _ANNUAL_EPS
        + _ANNUAL_BALANCE_SHEET
        + _STANDALONE_PL_5COL
        + _STANDALONE_EPS_5COL
        + _STANDALONE_BALANCE_SHEET_5COL
    )


# ---------------------------------------------------------------------------
# _parse_number
# ---------------------------------------------------------------------------


class TestParseNumber:
    def test_plain_integer(self) -> None:
        assert _parse_number("64259") == 64259.0

    def test_indian_comma_format(self) -> None:
        assert _parse_number("1,26,872") == 126872.0

    def test_standard_comma(self) -> None:
        assert _parse_number("64,259") == 64259.0

    def test_dash_is_zero(self) -> None:
        assert _parse_number("-") == 0.0

    def test_parenthesized_negative(self) -> None:
        assert _parse_number("(1)") == -1.0

    def test_parenthesized_negative_large(self) -> None:
        assert _parse_number("(164)") == -164.0

    def test_decimal(self) -> None:
        assert _parse_number("32.92") == pytest.approx(32.92)

    def test_empty_string(self) -> None:
        assert _parse_number("") == 0.0

    def test_large_indian_number(self) -> None:
        assert _parse_number("2,40,893") == 240893.0


# ---------------------------------------------------------------------------
# _extract_n_values
# ---------------------------------------------------------------------------


class TestExtractNValues:
    def test_simple_single_column(self) -> None:
        text = "Revenue from operations\n64,259\n"
        values = _extract_n_values(text, len("Revenue from operations\n"), n=1)
        assert values == [64259.0]

    def test_six_values_one_per_line(self) -> None:
        text = "Revenue from operations\n64,259\n62,613\n59,692\n1,26,872\n1,19,073\n2,40,893\n"
        values = _extract_n_values(text, len("Revenue from operations\n"), n=6)
        assert len(values) == 6
        assert values[0] == 64259.0
        assert values[5] == 240893.0

    def test_values_on_single_line(self) -> None:
        text = (
            "TOTAL EXPENSES\n48,956 47,344 45,368 96,300 91,157\n1,82,360\nNext label\n"
        )
        values = _extract_n_values(text, len("TOTAL EXPENSES\n"), n=6)
        assert len(values) == 6
        assert values[0] == 48956.0

    def test_stops_at_next_label(self) -> None:
        text = "Revenue from operations\n64,259\n62,613\nEmployee benefit expenses\n36,654\n"
        values = _extract_n_values(text, len("Revenue from operations\n"), n=6)
        assert values == [64259.0, 62613.0]

    def test_parenthesized_negatives(self) -> None:
        text = "Deferred tax\n(1)\n(164)\n(5)\n"
        values = _extract_n_values(text, len("Deferred tax\n"), n=3)
        assert values == [-1.0, -164.0, -5.0]

    def test_dashes_as_zero(self) -> None:
        text = "Exceptional item\n-\n-\n-\n-\n-\n958\n"
        values = _extract_n_values(text, len("Exceptional item\n"), n=6)
        assert values[0] == 0.0
        assert values[5] == 958.0


# ---------------------------------------------------------------------------
# _detect_filing
# ---------------------------------------------------------------------------


class TestDetectFiling:
    def test_quarterly(self) -> None:
        pt, pe = _detect_filing(_COVER_QUARTERLY)
        assert pt == "quarterly"
        assert pe == "2024-09-30"

    def test_annual(self) -> None:
        pt, pe = _detect_filing(_COVER_ANNUAL)
        assert pt == "annual"
        assert pe == "2026-03-31"

    def test_unknown_returns_none_period(self) -> None:
        pt, pe = _detect_filing("Some random text with no period mentioned.")
        assert pt == "unknown"
        assert pe is None

    def test_six_month_period_quarterly(self) -> None:
        text = "Financial results for the quarter and six-month period ended June 30, 2024."
        pt, pe = _detect_filing(text)
        assert pt == "quarterly"
        assert pe == "2024-06-30"

    def test_half_year_period_is_quarterly_not_annual(self) -> None:
        # Regression: "half year ended" contains "year ended" — must not classify as annual.
        text = "Results for quarter and half year ended September 30, 2025."
        pt, pe = _detect_filing(text)
        assert pt == "quarterly"
        assert pe == "2025-09-30"

    def test_half_year_standalone_is_quarterly(self) -> None:
        text = "Financial results for the half year ended September 30, 2025."
        pt, pe = _detect_filing(text)
        assert pt == "quarterly"
        assert pe == "2025-09-30"

    def test_annual_still_detected_after_half_year_fix(self) -> None:
        text = "Results for the year ended March 31, 2026."
        pt, pe = _detect_filing(text)
        assert pt == "annual"
        assert pe == "2026-03-31"

    def test_q4_annual_bundle_detected_as_annual(self) -> None:
        # Regression: Tata Steel-style Q4 filing that mentions BOTH
        # "quarter ended March 31" and "financial year ended March 31".
        # The shared date means this is an annual filing.
        text = (
            "Results of the Company for the quarter ended March 31, 2025. "
            "Also approved the Standalone and Consolidated Financial Statements "
            "for the financial year ended March 31, 2025."
        )
        pt, pe = _detect_filing(text)
        assert pt == "annual"
        assert pe == "2025-03-31"

    def test_q2_quarterly_not_confused_by_prior_year_annual_mention(self) -> None:
        # A Q2 filing might mention last year's annual period somewhere —
        # the dates differ so it must remain "quarterly".
        text = (
            "Results for the quarter and half year ended September 30, 2025. "
            "This compares to the year ended March 31, 2025."
        )
        pt, pe = _detect_filing(text)
        assert pt == "quarterly"
        assert pe == "2025-09-30"


# ---------------------------------------------------------------------------
# _primary_col
# ---------------------------------------------------------------------------


class TestPrimaryCol:
    def test_quarterly_6col(self) -> None:
        assert _primary_col("quarterly", 6) == 0

    def test_annual_5col(self) -> None:
        assert _primary_col("annual", 5) == 3

    def test_annual_fewer_cols_falls_back(self) -> None:
        assert _primary_col("annual", 3) == 0

    def test_unknown_period_type(self) -> None:
        assert _primary_col("unknown", 6) == 0


# ---------------------------------------------------------------------------
# _find_pl_regions
# ---------------------------------------------------------------------------


class TestFindPlRegions:
    def test_finds_consolidated_region(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        assert "consolidated" in regions

    def test_finds_standalone_region(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        assert "standalone" in regions

    def test_consolidated_before_standalone(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        assert regions["consolidated"][0] < regions["standalone"][0]

    def test_no_pl_table_returns_empty(self) -> None:
        text = "Some text without any financial data."
        regions = _find_pl_regions(text)
        assert regions == {}


# ---------------------------------------------------------------------------
# _extract_pl_facts
# ---------------------------------------------------------------------------


class TestExtractPlFacts:
    def test_extracts_revenue_quarterly(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        revenue = [f for f in facts if f.kind == FactKind.FINANCIAL_REVENUE]
        assert len(revenue) == 1
        assert revenue[0].value == pytest.approx(64259.0)

    def test_revenue_unit_is_crore_inr(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        revenue = [f for f in facts if f.kind == FactKind.FINANCIAL_REVENUE]
        assert revenue[0].unit == FactUnit.CRORE_INR

    def test_extracts_pat(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        pat = [f for f in facts if f.kind == FactKind.FINANCIAL_PAT]
        assert len(pat) == 1
        assert pat[0].value == pytest.approx(11955.0)

    def test_deferred_tax_is_negative(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        dt = [f for f in facts if f.kind == FactKind.FINANCIAL_DEFERRED_TAX]
        assert len(dt) == 1
        assert dt[0].value == pytest.approx(-1.0)

    def test_annual_uses_column_3(self) -> None:
        text = _build_annual_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2026-03-31", 3, "consolidated")
        revenue = [f for f in facts if f.kind == FactKind.FINANCIAL_REVENUE]
        assert len(revenue) == 1
        assert revenue[0].value == pytest.approx(267021.0)

    def test_pbt_is_after_exceptional_not_before(self) -> None:
        """PROFIT BEFORE TAX must read the post-exceptional PBT row (65487),
        not the pre-exceptional row (70013) whose label also ends in 'TAX'."""
        text = _build_annual_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2026-03-31", 3, "consolidated")
        pbt = [f for f in facts if f.kind == FactKind.FINANCIAL_PROFIT_BEFORE_TAX]
        assert len(pbt) == 1
        assert pbt[0].value == pytest.approx(65487.0)

    def test_provenance_section_is_basis_pl_table(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        assert all(f.provenance.section == "consolidated_pl_table" for f in facts)

    def test_provenance_char_offset_is_set(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        assert all(f.provenance.char_offset is not None for f in facts)

    def test_all_facts_have_period(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        assert all(f.period == "2024-09-30" for f in facts)

    def test_standalone_revenue_different_from_consolidated(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        con_rev, con_end = regions["consolidated"]
        sa_rev, sa_end = regions["standalone"]
        con_facts = _extract_pl_facts(
            text, con_rev, con_end, "2024-09-30", 0, "consolidated"
        )
        sa_facts = _extract_pl_facts(
            text, sa_rev, sa_end, "2024-09-30", 0, "standalone"
        )
        con_revenue = next(
            f.value for f in con_facts if f.kind == FactKind.FINANCIAL_REVENUE
        )
        sa_revenue = next(
            f.value for f in sa_facts if f.kind == FactKind.FINANCIAL_REVENUE
        )
        assert con_revenue != sa_revenue
        assert con_revenue == pytest.approx(64259.0)
        assert sa_revenue == pytest.approx(53990.0)

    def test_extracts_all_major_pl_rows(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_pl_facts(text, rev, end, "2024-09-30", 0, "consolidated")
        kinds = {f.kind for f in facts}
        for expected in (
            FactKind.FINANCIAL_REVENUE,
            FactKind.FINANCIAL_OTHER_INCOME,
            FactKind.FINANCIAL_TOTAL_INCOME,
            FactKind.FINANCIAL_EMPLOYEE_COST,
            FactKind.FINANCIAL_FINANCE_COST,
            FactKind.FINANCIAL_DEPRECIATION,
            FactKind.FINANCIAL_TOTAL_EXPENSES,
            FactKind.FINANCIAL_PROFIT_BEFORE_TAX,
            FactKind.FINANCIAL_PAT,
        ):
            assert expected in kinds, f"{expected} not extracted"


# ---------------------------------------------------------------------------
# _extract_eps_facts
# ---------------------------------------------------------------------------


class TestExtractEpsFacts:
    def test_extracts_eps_quarterly(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_eps_facts(
            text, "2024-09-30", 0, "consolidated", rev, end + 3000
        )
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(32.92)

    def test_eps_unit_is_rupees(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_eps_facts(
            text, "2024-09-30", 0, "consolidated", rev, end + 3000
        )
        assert facts[0].unit == FactUnit.RUPEES

    def test_eps_annual_col3(self) -> None:
        text = _build_annual_filing()
        regions = _find_pl_regions(text)
        rev, end = regions["consolidated"]
        facts = _extract_eps_facts(
            text, "2026-03-31", 3, "consolidated", rev, end + 3000
        )
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(135.70)

    def test_returns_empty_when_not_found(self) -> None:
        text = "No EPS information here."
        facts = _extract_eps_facts(text, "2024-09-30", 0, "consolidated", 0, len(text))
        assert facts == []


# ---------------------------------------------------------------------------
# _extract_segment_facts
# ---------------------------------------------------------------------------


class TestExtractSegmentFacts:
    def test_finds_all_six_segments(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        names = [f for f in facts if f.kind == FactKind.SEGMENT_NAME]
        assert len(names) == 6

    def test_segment_revenues_present(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        revenues = [f for f in facts if f.kind == FactKind.SEGMENT_REVENUE]
        assert len(revenues) == 6

    def test_bfsi_revenue(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        # Find BFSI name + its paired revenue
        name_facts = [
            f
            for f in facts
            if f.kind == FactKind.SEGMENT_NAME and "Banking" in str(f.value)
        ]
        rev_facts = [f for f in facts if f.kind == FactKind.SEGMENT_REVENUE]
        assert len(name_facts) == 1
        assert rev_facts[0].value == pytest.approx(23785.0)

    def test_segment_name_unit_is_none(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        names = [f for f in facts if f.kind == FactKind.SEGMENT_NAME]
        assert all(f.unit is None for f in names)

    def test_segment_revenue_unit_is_crore_inr(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        revenues = [f for f in facts if f.kind == FactKind.SEGMENT_REVENUE]
        assert all(f.unit == FactUnit.CRORE_INR for f in revenues)

    def test_provenance_section_is_segment_table(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert all(f.provenance.section == "segment_table" for f in facts)

    def test_no_segment_table_returns_empty(self) -> None:
        text = "Revenue from operations\n64,259\n62,613\n"
        facts = _extract_segment_facts(text, "2024-09-30", 0, 0)
        assert facts == []


# ---------------------------------------------------------------------------
# _extract_dividend_facts
# ---------------------------------------------------------------------------


class TestExtractDividendFacts:
    def test_extracts_interim_dividend_amount(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        dps = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_PER_SHARE]
        assert len(dps) == 1
        assert dps[0].value == pytest.approx(10.0)

    def test_extracts_dividend_type(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        types = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_TYPE]
        assert len(types) == 1
        assert types[0].value == "interim"

    def test_extracts_record_date(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        rec = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_RECORD_DATE]
        assert len(rec) == 1
        assert rec[0].value == "2024-10-18"

    def test_extracts_payment_date(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        pay = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE]
        assert len(pay) == 1
        assert pay[0].value == "2024-11-05"

    def test_dividend_unit_is_rupees_per_share(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        dps = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_PER_SHARE]
        assert dps[0].unit == FactUnit.RUPEES_PER_SHARE

    def test_record_and_payment_unit_is_iso_date(self) -> None:
        facts = _extract_dividend_facts(_COVER_QUARTERLY, "2024-09-30")
        for kind in (
            FactKind.CAPITAL_DIVIDEND_RECORD_DATE,
            FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE,
        ):
            f_list = [f for f in facts if f.kind == kind]
            assert all(f.unit == FactUnit.ISO_DATE for f in f_list)

    def test_returns_empty_when_no_dividend(self) -> None:
        facts = _extract_dividend_facts("Board met to review results.", "2024-09-30")
        assert facts == []

    def test_annual_final_dividend(self) -> None:
        facts = _extract_dividend_facts(_COVER_ANNUAL, "2026-03-31")
        dps = [f for f in facts if f.kind == FactKind.CAPITAL_DIVIDEND_PER_SHARE]
        assert len(dps) >= 1
        assert any(f.value == pytest.approx(31.0) for f in dps)


# ---------------------------------------------------------------------------
# analyze — happy path (quarterly)
# ---------------------------------------------------------------------------


class TestAnalyzeQuarterly:
    def test_returns_analysis_result(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_correct(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert result.evidence_id == "fr-001"

    def test_kind_is_financial_results(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert result.kind == "financial_results"

    def test_analyzer_version_set(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert result.analyzer_version == ANALYZER_VERSION

    def test_period_end_fact(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        pe = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(pe) == 1
        assert pe[0].value == "2024-09-30"

    def test_period_type_fact(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        pt = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert len(pt) == 1
        assert pt[0].value == "quarterly"

    def test_report_basis_consolidated_and_standalone(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        bases = {f.value for f in _facts(result, FactKind.REPORT_BASIS)}
        assert "consolidated" in bases
        assert "standalone" in bases

    def test_consolidated_revenue(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        rev = _con_facts(result, FactKind.FINANCIAL_REVENUE)
        assert len(rev) == 1
        assert rev[0].value == pytest.approx(64259.0)

    def test_standalone_revenue(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        rev = _sa_facts(result, FactKind.FINANCIAL_REVENUE)
        assert len(rev) == 1
        assert rev[0].value == pytest.approx(53990.0)

    def test_confidence_high_when_many_pl_facts(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert result.confidence in ("high", "medium")

    def test_consolidated_pl_excerpt_present(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert "consolidated_pl_table" in result.excerpts

    def test_standalone_pl_excerpt_present(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert "standalone_pl_table" in result.excerpts

    def test_dividend_facts_extracted(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        dps = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert len(dps) >= 1
        assert dps[0].value == pytest.approx(10.0)

    def test_audit_opinion_fact(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        op = _facts(result, FactKind.AUDIT_OPINION)
        assert len(op) >= 1
        assert op[0].value == "unmodified"

    def test_audit_firm_fact(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        firm = _facts(result, FactKind.AUDIT_FIRM)
        assert len(firm) >= 1
        assert "B S R" in str(firm[0].value)

    def test_segment_revenue_facts(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        seg_rev = _facts(result, FactKind.SEGMENT_REVENUE)
        assert len(seg_rev) == 6

    def test_segment_name_facts(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        seg_names = _facts(result, FactKind.SEGMENT_NAME)
        assert len(seg_names) == 6

    def test_eps_fact_extracted(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        eps = _con_facts(result, FactKind.FINANCIAL_EPS_BASIC)
        assert len(eps) == 1
        assert eps[0].value == pytest.approx(32.92)

    def test_all_facts_have_confidence(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert all(f.confidence in ("high", "medium", "low") for f in result.facts)

    def test_all_facts_have_provenance_section(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert all(
            isinstance(f.provenance.section, str) and f.provenance.section
            for f in result.facts
        )

    def test_warnings_is_list(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# analyze — annual filing
# ---------------------------------------------------------------------------


class TestAnalyzeAnnual:
    def test_period_type_annual(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        pt = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert pt[0].value == "annual"

    def test_annual_revenue_is_full_year(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        rev = _con_facts(result, FactKind.FINANCIAL_REVENUE)
        assert len(rev) == 1
        # Col 3 = 2,67,021 crore (full year), not 70,698 (Q4 only)
        assert rev[0].value == pytest.approx(267021.0)

    def test_annual_eps_is_full_year(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        eps = _con_facts(result, FactKind.FINANCIAL_EPS_BASIC)
        assert len(eps) == 1
        assert eps[0].value == pytest.approx(135.70)

    def test_annual_standalone_revenue(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        rev = _sa_facts(result, FactKind.FINANCIAL_REVENUE)
        assert len(rev) == 1
        assert rev[0].value == pytest.approx(218000.0)


# ---------------------------------------------------------------------------
# analyze — error cases
# ---------------------------------------------------------------------------


class TestAnalyzeErrors:
    def test_raises_key_error_unknown_id(self) -> None:
        kb = MagicMock(spec=KnowledgeBase)
        kb.get.return_value = None
        with pytest.raises(KeyError):
            analyze("does-not-exist", kb)

    def test_raises_value_error_failed_document(self) -> None:
        doc = _make_doc(status="failed", char_count=None)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="cannot analyze"):
            analyze("fr-001", kb)

    def test_raises_value_error_content_unavailable(self) -> None:
        doc = _make_doc(status="ok", char_count=10_000)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="content unavailable"):
            analyze("fr-001", kb)


# ---------------------------------------------------------------------------
# analyze — Reg 23(9) disclosure (no P&L)
# ---------------------------------------------------------------------------


class TestReg23Disclosure:
    def test_no_pl_yields_low_confidence(self) -> None:
        text = (
            "Pursuant to Regulation 23(9) of Listing Regulations, please find enclosed "
            "the details of Related Party Transactions on consolidated basis for the "
            "half-year ended September 30, 2022.\n" + "x" * 200
        )
        doc = _make_doc(char_count=len(text))
        kb = _make_kb(doc, text)
        result = analyze("fr-003", kb)
        assert result.confidence == "low"

    def test_no_pl_emits_warning(self) -> None:
        text = (
            "Pursuant to Regulation 23(9) of Listing Regulations, details attached.\n"
            + "x" * 200
        )
        doc = _make_doc(char_count=len(text))
        kb = _make_kb(doc, text)
        result = analyze("fr-003", kb)
        assert any("P&L" in w or "Regulation 23" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Exceptional items
# ---------------------------------------------------------------------------


class TestExceptionalItems:
    def test_nil_exceptional_not_emitted(self) -> None:
        """Q2 FY25 exceptional item is nil in current period (col 0)."""
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        exc_amounts = _con_facts(result, FactKind.EXCEPTIONAL_AMOUNT)
        # Column 0 = current quarter = dash (0); should not emit
        assert (
            all(f.value == 0.0 or f.value is None for f in exc_amounts)
            or exc_amounts == []
        )

    def test_annual_exceptional_in_current_year(self) -> None:
        """Annual FY26 restructuring of 1,388 crore appears in col 3 (FY2026 full year)."""
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        exc_amounts = _con_facts(result, FactKind.EXCEPTIONAL_AMOUNT)
        # Col 3 (FY2026) has restructuring (1388) and labour codes (2128) — both non-zero
        assert len(exc_amounts) >= 1
        amounts = {f.value for f in exc_amounts}
        assert any(v > 0 for v in amounts)


# ---------------------------------------------------------------------------
# Balance sheet extraction
# ---------------------------------------------------------------------------

_BS_TEXT = """\

ASSETS
Non-current assets
Property, plant and equipment
10,500
8,200

Current assets
Inventories
1,200
1,050
Trade receivables
24,000
22,000
Cash and cash equivalents
6,417
8,342

EQUITY AND LIABILITIES
Equity attributable to shareholders of the Company
1,07,240
94,756
Non-controlling interests
700
650

CASH FLOWS FROM OPERATING ACTIVITIES
"""

_BS_TEXT_WITH_DEBT = """\

ASSETS
Non-current assets
Borrowings
10,000
9,500

Current assets
Cash and cash equivalents
5,000
4,500

EQUITY AND LIABILITIES
Equity attributable to shareholders of the Company
50,000
45,000

Current liabilities
Borrowings
2,000
1,500

CASH FLOWS FROM OPERATING ACTIVITIES
"""


class TestFindBsRegion:
    def test_finds_assets_block(self) -> None:
        region = _find_bs_region(_BS_TEXT)
        assert region is not None

    def test_region_ends_before_cash_flows(self) -> None:
        region = _find_bs_region(_BS_TEXT)
        assert region is not None
        start, end = region
        assert "CASH FLOWS FROM OPERATING" not in _BS_TEXT[start:end]

    def test_returns_none_when_no_assets(self) -> None:
        assert _find_bs_region("Just some text with no ASSETS block.") is None

    def test_region_contains_cash_line(self) -> None:
        region = _find_bs_region(_BS_TEXT)
        assert region is not None
        start, end = region
        assert "Cash and cash equivalents" in _BS_TEXT[start:end]


class TestExtractBalanceSheetFacts:
    def test_extracts_cash(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        cash = [f for f in facts if f.kind == FactKind.FINANCIAL_CASH_AND_EQUIVALENTS]
        assert len(cash) == 1
        assert cash[0].value == pytest.approx(6417.0)

    def test_cash_unit_is_crore_inr(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        cash = [f for f in facts if f.kind == FactKind.FINANCIAL_CASH_AND_EQUIVALENTS]
        assert cash[0].unit == FactUnit.CRORE_INR

    def test_extracts_equity(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        eq = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_EQUITY]
        assert len(eq) == 1
        assert eq[0].value == pytest.approx(107240.0)

    def test_equity_is_parent_shareholders_only(self) -> None:
        # 1,07,240 is the parent-only equity; NCI 700 is not included
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        eq = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_EQUITY]
        assert eq[0].value != pytest.approx(107940.0)  # not the group total

    def test_no_debt_when_absent(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        debt = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_DEBT]
        assert debt == []

    def test_extracts_debt_when_present(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT_WITH_DEBT, "2026-03-31")
        debt = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_DEBT]
        assert len(debt) == 1
        assert debt[0].value == pytest.approx(12000.0)  # 10,000 + 2,000

    def test_period_set_on_all_facts(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        assert all(f.period == "2026-03-31" for f in facts)

    def test_provenance_section_is_balance_sheet(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        assert all(f.provenance.section == "balance_sheet" for f in facts)

    def test_returns_empty_when_no_bs_region(self) -> None:
        assert (
            _extract_balance_sheet_facts("No balance sheet here.", "2026-03-31") == []
        )


# ---------------------------------------------------------------------------
# Regression: _extract_n_values must ignore mixed numeric+text lines
# ---------------------------------------------------------------------------


class TestExtractNValuesPureNumericCheck:
    """Section markers and headers that contain digits must not trigger
    value collection (regression for Tata Steel balance-sheet layout)."""

    def test_section_marker_3_not_collected(self) -> None:
        text = "(3) Assets held for sale\n44,589.94\n"
        vals = _extract_n_values(text, 0)
        # (3) has non-numeric residual "Assets held for sale" → skip
        # 44,589.94 is pure numeric → collect
        assert vals == [44589.94]

    def test_dash_in_label_not_collected(self) -> None:
        text = "TOTAL - ASSETS\n44,589.94\n"
        vals = _extract_n_values(text, 0)
        # "TOTAL - ASSETS" has residual text → skip
        assert vals == [44589.94]

    def test_sub_total_label_not_collected(self) -> None:
        text = "Sub-total - Current assets\n9,604.96\n"
        vals = _extract_n_values(text, 0)
        assert vals == [9604.96]

    def test_pure_section_marker_stops_collection(self) -> None:
        text = "10,000\n20,000\n(3) Something\n30,000\n"
        vals = _extract_n_values(text, 0)
        # Collection starts at 10,000; "(3) Something" has text residual → break
        assert vals == [10000.0, 20000.0]

    def test_dash_alone_on_line_is_zero(self) -> None:
        text = "-\n-\n5,000\n"
        vals = _extract_n_values(text, 0)
        assert vals == [0.0, 0.0, 5000.0]


# ---------------------------------------------------------------------------
# Regression: OCR "L as 1" correction in _fix_ocr_numbers
# ---------------------------------------------------------------------------


class TestOcrLAs1:
    def test_l_between_digit_and_period(self) -> None:
        assert _fix_ocr_numbers("68.55L.81") == "68,551.81"

    def test_l_between_two_digits(self) -> None:
        assert _fix_ocr_numbers("1L234") == "11234"

    def test_l_not_replaced_at_end(self) -> None:
        result = _fix_ocr_numbers("50L")
        assert "L" in result  # trailing L not replaced

    def test_l_not_replaced_before_space(self) -> None:
        result = _fix_ocr_numbers("68L crore")
        assert "L" in result  # L before space not replaced


# ---------------------------------------------------------------------------
# Deferred BS layout (Tata Steel style): Cash, Equity, Debt
# ---------------------------------------------------------------------------

_BS_DEFERRED = """
ASSETS
(I) Non-current assets
Property, plant and equipment
Sub-total - Non current assets
As at 31.03.2025 Audited
1,25,215.17
2,11,003.26
Crore
As at 31.03.2024 Audited
1,23,538.14
2,02,875.25
(2) Current assets
(a)
Inventories
(b) Financial assets
(i)
Investments
(ii)
Trade receivables
(iii)
Cash and cash equivalents
(iv)
Other balances with banks
(v)
Loans
TOTAL - ASSETS
Sub-total - Current assets
44,589.94
442.65
5,260.06
9,604.96
2,042.02
4.98
68,391.54
2,79,394.80
B
EQUITY AND LIABILITIES
(1) Equity
(a) Equity share capital
(b) Other equity
Equity attributable to shareholders of the company
Non controlling interest
Sub-total - Total equity
(2) Non-current liabilities
(a) Financial liabilities
(i)
Borrowings
(ii)
Lease Liabilities
(b) Provisions
(c) Deferred income
Sub-total - Non current liabilities
(3) Current liabilities
(a) Financial liabilities
(i)
Borrowings
TOTAL - EQUITY AND LIABILITIES
1,247.44
89,922.19
91,169.63
183.15
91,352.78
68,551.81
4,832.71
5,806.50
2,789.83
81,980.85
20,412.00

CASH FLOWS FROM OPERATING ACTIVITIES
"""


class TestDeferredBalanceSheetLayout:
    def test_cash_extracted_at_index_3(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        cash = [f for f in facts if f.kind == FactKind.FINANCIAL_CASH_AND_EQUIVALENTS]
        assert len(cash) == 1
        assert cash[0].value == pytest.approx(9604.96)

    def test_equity_sub_total_detected_algebraically(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        eq = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_EQUITY]
        assert len(eq) == 1
        assert eq[0].value == pytest.approx(91352.78)

    def test_debt_is_ncl_plus_cl_borrowings(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        debt = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_DEBT]
        assert len(debt) == 1
        # NCL Borrowings 68,551.81 + CL Borrowings 20,412.00 = 88,963.81
        assert debt[0].value == pytest.approx(88963.81, abs=1.0)

    def test_ocr_l_as_1_in_deferred_borrowings(self) -> None:
        text_with_ocr = _BS_DEFERRED.replace("68,551.81", "68.55L.81")
        facts = _extract_balance_sheet_facts(text_with_ocr, "2025-03-31")
        debt = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_DEBT]
        assert len(debt) == 1
        assert debt[0].value == pytest.approx(88963.81)


# ---------------------------------------------------------------------------
# Working-capital items: Inventories, Trade receivables, Trade payables,
# Unbilled revenue (M-P3.1, ADR-0012)
# ---------------------------------------------------------------------------


class TestDirectLayoutWorkingCapital:
    """_BS_TEXT (direct/TCS-style, no Billed/Unbilled split, no payables)."""

    def test_extracts_inventories(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        inv = [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES]
        assert len(inv) == 1
        assert inv[0].value == pytest.approx(1200.0)

    def test_extracts_trade_receivables_single_value(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        tr = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_RECEIVABLES]
        assert len(tr) == 1
        assert tr[0].value == pytest.approx(24000.0)

    def test_no_unbilled_when_no_split_disclosed(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_UNBILLED_REVENUE] == []

    def test_no_payables_when_not_disclosed(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_PAYABLES] == []


# Modeled directly on real TCS financial_results text (verified against the
# live corpus): a non-current Trade receivables/Billed/Unbilled block for
# long-duration contracts appears BEFORE the current-assets one -- this
# fixture exercises the double-occurrence trap the anchor-to-Cash logic must
# resolve correctly. Trade payables modeled on the real Tata Steel MSME/
# non-MSME wording, also verified against the live corpus.
_BS_DIRECT_BILLED_UNBILLED = """\

ASSETS
Non-current assets
Other financial assets
Investments
289
281
Trade receivables
Billed
86
127
Unbilled
62
16
Loans
2
2

Current assets
Inventories
29
28
Financial assets
Investments
35,792
31,481
Trade receivables
Billed
49,532
44,434
Unbilled
8,178
9,143
Cash and cash equivalents
8,142
7,300

EQUITY AND LIABILITIES
Equity attributable to shareholders of the Company
50,000
45,000

Current liabilities
Financial liabilities
Borrowings
1,500
1,200
Trade payables
Total outstanding dues of micro and small enterprises
7,857.27
118.62
Total outstanding dues of creditors other than micro and small enterprises
10,482.34
9,800.00

CASH FLOWS FROM OPERATING ACTIVITIES
"""


class TestBilledUnbilledDoubleOccurrence:
    def test_trade_receivables_selects_current_assets_not_non_current(self) -> None:
        # Non-current block has Billed=86; current-assets block has
        # Billed=49,532. Must select the current-assets one.
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        tr = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_RECEIVABLES]
        assert len(tr) == 1
        assert tr[0].value == pytest.approx(49532.0)

    def test_unbilled_selects_current_assets_not_non_current(self) -> None:
        # Non-current Unbilled=62; current-assets Unbilled=8,178.
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        ub = [f for f in facts if f.kind == FactKind.FINANCIAL_UNBILLED_REVENUE]
        assert len(ub) == 1
        assert ub[0].value == pytest.approx(8178.0)

    def test_receivables_and_unbilled_do_not_overlap(self) -> None:
        # Billed (49,532) and Unbilled (8,178) are additive, distinct facts --
        # never summed together into FINANCIAL_TRADE_RECEIVABLES.
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        tr = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_RECEIVABLES][0]
        ub = [f for f in facts if f.kind == FactKind.FINANCIAL_UNBILLED_REVENUE][0]
        assert tr.value != pytest.approx(tr.value + ub.value)
        assert tr.value == pytest.approx(49532.0)
        assert ub.value == pytest.approx(8178.0)

    def test_inventories_unaffected_by_double_occurrence(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        inv = [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES]
        assert len(inv) == 1
        assert inv[0].value == pytest.approx(29.0)

    def test_debt_and_payables_are_distinct_values(self) -> None:
        # Regression: Borrowings must not accidentally capture the Trade
        # Payables MSME sub-line's numbers.
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        debt = [f for f in facts if f.kind == FactKind.FINANCIAL_TOTAL_DEBT][0]
        payables = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_PAYABLES][0]
        assert debt.value == pytest.approx(1500.0)
        assert payables.value == pytest.approx(18339.61)
        assert debt.value != pytest.approx(payables.value)


class TestTradePayablesSummation:
    def test_sums_msme_and_non_msme(self) -> None:
        # 7,857.27 + 10,482.34 = 18,339.61
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        payables = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_PAYABLES]
        assert len(payables) == 1
        assert payables[0].value == pytest.approx(18339.61)

    def test_no_fact_when_only_one_sub_line_present(self) -> None:
        # Under-emit: a partial sum would misstate the total.
        text = _BS_DIRECT_BILLED_UNBILLED.replace(
            "Total outstanding dues of creditors other than micro and small "
            "enterprises\n10,482.34\n9,800.00\n",
            "",
        )
        facts = _extract_balance_sheet_facts(text, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_PAYABLES] == []


class TestDeferredLayoutWorkingCapital:
    """_BS_DEFERRED (Tata Steel style): Inventories and Trade receivables are
    already-computed byproducts of the Cash extraction's positional vals[]."""

    def test_extracts_inventories_from_shared_vals(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        inv = [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES]
        assert len(inv) == 1
        assert inv[0].value == pytest.approx(44589.94)

    def test_extracts_trade_receivables_from_shared_vals(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        tr = [f for f in facts if f.kind == FactKind.FINANCIAL_TRADE_RECEIVABLES]
        assert len(tr) == 1
        assert tr[0].value == pytest.approx(5260.06)

    def test_no_unbilled_in_deferred_layout(self) -> None:
        # No verified filing discloses a Billed/Unbilled split in this layout.
        facts = _extract_balance_sheet_facts(_BS_DEFERRED, "2025-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_UNBILLED_REVENUE] == []


class TestWorkingCapitalPlausibilityFloor:
    def test_zero_value_dropped_not_emitted(self) -> None:
        text = _BS_TEXT.replace("Inventories\n1,200\n1,050", "Inventories\n0\n0")
        facts = _extract_balance_sheet_facts(text, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES] == []

    def test_negative_value_dropped_not_emitted(self) -> None:
        text = _BS_TEXT.replace(
            "Inventories\n1,200\n1,050", "Inventories\n(1,200)\n1,050"
        )
        facts = _extract_balance_sheet_facts(text, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES] == []

    def test_positive_value_retained(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_TEXT, "2026-03-31")
        assert [f for f in facts if f.kind == FactKind.FINANCIAL_INVENTORIES][
            0
        ].value > 0


class TestWorkingCapitalProvenanceAndPeriod:
    def test_new_facts_carry_balance_sheet_section(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        new_kinds = {
            FactKind.FINANCIAL_INVENTORIES,
            FactKind.FINANCIAL_TRADE_RECEIVABLES,
            FactKind.FINANCIAL_TRADE_PAYABLES,
            FactKind.FINANCIAL_UNBILLED_REVENUE,
        }
        for f in facts:
            if f.kind in new_kinds:
                assert f.provenance.section == "balance_sheet"

    def test_new_facts_carry_period(self) -> None:
        facts = _extract_balance_sheet_facts(_BS_DIRECT_BILLED_UNBILLED, "2026-03-31")
        assert all(f.period == "2026-03-31" for f in facts)


# ---------------------------------------------------------------------------
# Cash flow extraction
# ---------------------------------------------------------------------------

_CF_TEXT = """\
CASH FLOWS FROM OPERATING ACTIVITIES
Profit before tax
65,487
65,331
Net cash generated from operating activities
52,094
48,908

CASH FLOWS FROM INVESTING ACTIVITIES
Payment for purchase of property, plant and equipment
               (3,670)                (2,917)
Proceeds from disposal
121
90
"""


class TestFindCfRegion:
    def test_finds_operating_activities_header(self) -> None:
        region = _find_cf_region(_CF_TEXT)
        assert region is not None

    def test_returns_none_when_absent(self) -> None:
        assert _find_cf_region("No cash flow here.") is None

    def test_region_contains_cfo_line(self) -> None:
        region = _find_cf_region(_CF_TEXT)
        assert region is not None
        start, end = region
        assert "Net cash generated from operating activities" in _CF_TEXT[start:end]


class TestExtractCashflowFacts:
    def test_extracts_operating_cash_flow(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        cfo = [f for f in facts if f.kind == FactKind.FINANCIAL_OPERATING_CASH_FLOW]
        assert len(cfo) == 1
        assert cfo[0].value == pytest.approx(52094.0)

    def test_cfo_unit_is_crore_inr(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        cfo = [f for f in facts if f.kind == FactKind.FINANCIAL_OPERATING_CASH_FLOW]
        assert cfo[0].unit == FactUnit.CRORE_INR

    def test_extracts_capex(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        capex = [f for f in facts if f.kind == FactKind.FINANCIAL_CAPEX]
        assert len(capex) == 1
        assert capex[0].value == pytest.approx(3670.0)

    def test_capex_is_positive_absolute_value(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        capex = [f for f in facts if f.kind == FactKind.FINANCIAL_CAPEX]
        assert capex[0].value > 0

    def test_capex_unit_is_crore_inr(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        capex = [f for f in facts if f.kind == FactKind.FINANCIAL_CAPEX]
        assert capex[0].unit == FactUnit.CRORE_INR

    def test_provenance_section_is_cash_flow_statement(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        assert all(f.provenance.section == "cash_flow_statement" for f in facts)

    def test_period_set_on_all_facts(self) -> None:
        facts = _extract_cashflow_facts(_CF_TEXT, "2026-03-31")
        assert all(f.period == "2026-03-31" for f in facts)

    def test_returns_empty_when_no_cf_section(self) -> None:
        assert _extract_cashflow_facts("No cash flow here.", "2026-03-31") == []


# ---------------------------------------------------------------------------
# Segment EBIT extraction
# ---------------------------------------------------------------------------


class TestExtractSegmentEbitFacts:
    def test_finds_six_ebit_facts(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert len(facts) == 6

    def test_ebit_unit_is_crore_inr(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert all(f.unit == FactUnit.CRORE_INR for f in facts)

    def test_bfsi_ebit_value(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert facts[0].value == pytest.approx(6345.0)

    def test_manufacturing_ebit_value(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        mfg = [f for f in facts if f.value == pytest.approx(2063.0)]
        assert len(mfg) == 1

    def test_all_ebit_facts_have_segment_table_provenance(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert all(f.provenance.section == "segment_table" for f in facts)

    def test_fact_kind_is_segment_ebit(self) -> None:
        text = _build_quarterly_filing()
        regions = _find_pl_regions(text)
        facts = _extract_segment_ebit_facts(
            text, "2024-09-30", 0, regions["consolidated"][0]
        )
        assert all(f.kind == FactKind.SEGMENT_EBIT for f in facts)

    def test_returns_empty_when_no_segment_result(self) -> None:
        text = "Revenue from operations\n64,259\nSEGMENT REVENUE\nBanking, Financial Services and Insurance\n23,785\n"
        facts = _extract_segment_ebit_facts(text, "2024-09-30", 0, 0)
        assert facts == []


# ---------------------------------------------------------------------------
# analyze — quarterly segment EBIT
# ---------------------------------------------------------------------------


class TestAnalyzeQuarterlySegmentEbit:
    def test_segment_ebit_extracted_for_quarterly(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        ebit = _facts(result, FactKind.SEGMENT_EBIT)
        assert len(ebit) == 6

    def test_segment_ebit_bfsi_value(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        ebit = _facts(result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(6345.0) for f in ebit)

    def test_no_balance_sheet_facts_for_quarterly(self) -> None:
        content = _build_quarterly_filing()
        kb = _make_kb(_make_doc(char_count=len(content)), content)
        result = analyze("fr-001", kb)
        bs_facts = [
            f
            for f in result.facts
            if f.kind
            in (
                FactKind.FINANCIAL_CASH_AND_EQUIVALENTS,
                FactKind.FINANCIAL_TOTAL_EQUITY,
                FactKind.FINANCIAL_TOTAL_DEBT,
                FactKind.FINANCIAL_OPERATING_CASH_FLOW,
                FactKind.FINANCIAL_CAPEX,
            )
        ]
        assert bs_facts == []


# ---------------------------------------------------------------------------
# analyze — annual balance sheet and cash flow
# ---------------------------------------------------------------------------


class TestAnalyzeAnnualBalanceSheetAndCashFlow:
    def test_cash_extracted_from_annual(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        cash = _facts(result, FactKind.FINANCIAL_CASH_AND_EQUIVALENTS)
        assert len(cash) == 1
        assert cash[0].value == pytest.approx(6417.0)

    def test_equity_extracted_from_annual(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        eq = _facts(result, FactKind.FINANCIAL_TOTAL_EQUITY)
        assert len(eq) == 1
        assert eq[0].value == pytest.approx(107240.0)

    def test_no_debt_fact_for_debt_free_annual(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        debt = _facts(result, FactKind.FINANCIAL_TOTAL_DEBT)
        assert debt == []

    def test_operating_cash_flow_extracted(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        cfo = _facts(result, FactKind.FINANCIAL_OPERATING_CASH_FLOW)
        assert len(cfo) == 1
        assert cfo[0].value == pytest.approx(52094.0)

    def test_capex_extracted(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        capex = _facts(result, FactKind.FINANCIAL_CAPEX)
        assert len(capex) == 1
        assert capex[0].value == pytest.approx(3670.0)

    def test_capex_is_positive(self) -> None:
        content = _build_annual_filing()
        kb = _make_kb(
            _make_doc(char_count=len(content), source_date="2026-04-09"), content
        )
        result = analyze("fr-002", kb)
        capex = _facts(result, FactKind.FINANCIAL_CAPEX)
        assert capex[0].value > 0


# ---------------------------------------------------------------------------
# _fix_ocr_numbers — OCR comma→period artifact recovery
# ---------------------------------------------------------------------------


class TestFixOcrNumbers:
    """Regression tests for the OCR comma→period artifact.

    Tata Steel (and some other BSE filers) have PDFs where the comma
    thousands-separator is converted to a period by the OCR engine, producing
    multi-period strings ("58.216.04") or period+space fragments ("34.228 34").
    """

    def test_double_period_thousands(self) -> None:
        # 58,216.04 → 58.216.04 (OCR) → restored
        assert _fix_ocr_numbers("58.216.04") == "58,216.04"

    def test_double_period_thousands_small(self) -> None:
        assert _fix_ocr_numbers("52.744.07") == "52,744.07"

    def test_triple_period_lakhs(self) -> None:
        # 1,10,960.11 → 1.10.960.11 (OCR) → restored
        assert _fix_ocr_numbers("1.10.960.11") == "1,10,960.11"

    def test_triple_period_large_lakhs(self) -> None:
        assert _fix_ocr_numbers("2.16.840.35") == "2,16,840.35"

    def test_space_decimal_fragment(self) -> None:
        # 34,228.34 → 34.228 34 (period then space) → restored
        assert _fix_ocr_numbers("34.228 34") == "34,228.34"

    def test_space_decimal_other_value(self) -> None:
        assert _fix_ocr_numbers("64.827 44") == "64,827.44"

    def test_already_correct_number_unchanged(self) -> None:
        # TCS-style numbers with comma separators are left intact
        assert _fix_ocr_numbers("70,698.00") == "70,698.00"

    def test_plain_decimal_unchanged(self) -> None:
        assert _fix_ocr_numbers("25.3") == "25.3"

    def test_small_number_unchanged(self) -> None:
        assert _fix_ocr_numbers("451.20") == "451.20"

    def test_mixed_period_comma_first_sep_corrupted(self) -> None:
        # 2,16,840.35 → 2.16,840.35 (first comma → period, second OK)
        assert _fix_ocr_numbers("2.16,840.35") == "2,16,840.35"

    def test_mixed_period_comma_second_sep_corrupted(self) -> None:
        # 2,27,296.20 → 2,27.296.20 (second comma → period, first OK)
        # DOUBLE_PERIOD catches "27.296.20" sub-string
        assert _fix_ocr_numbers("2,27.296.20") == "2,27,296.20"

    def test_multiple_values_in_line(self) -> None:
        line = "58.216.04 52.744.07 1.10.960.11"
        result = _fix_ocr_numbers(line)
        assert "58,216.04" in result
        assert "52,744.07" in result
        assert "1,10,960.11" in result

    def test_extract_n_values_handles_ocr(self) -> None:
        # End-to-end: values mangled by OCR should be correctly extracted
        text = "Revenue from operations\n58.216.04\n52.744.07\n53.489.73\n"
        vals = _extract_n_values(text, len("Revenue from operations\n"), n=3)
        assert vals == pytest.approx([58216.04, 52744.07, 53489.73])

    def test_extract_n_values_handles_space_decimal(self) -> None:
        text = "Revenue from operations\n34.228 34\n30.599 10\n32.013.76\n"
        vals = _extract_n_values(text, len("Revenue from operations\n"), n=3)
        assert vals[0] == pytest.approx(34228.34)
        assert vals[2] == pytest.approx(32013.76)


# ---------------------------------------------------------------------------
# Banking-format detection and extraction (regression: SBI validation sprint)
# ---------------------------------------------------------------------------

_BANKING_RESULTS_TEXT = """\
State Bank of India
UNAUDITED FINANCIAL RESULTS FOR THE QUARTER ENDED SEPTEMBER 30, 2025

Standalone        Consolidated
Q2FY26  Q1FY26  Q2FY25    Q2FY26  Q1FY26  Q2FY25

Interest Earned
86,182  85,437  82,049    88,993  88,146  84,652

Other Income
15,325  17,345  15,270    47,457  41,263  42,757

Net Profit for the quarter
20,159  19,160  18,331    21,504  21,626  20,219

CASH FLOWS FROM OPERATING ACTIVITIES
"""

_NON_BANKING_TEXT = """\
Revenue from operations
53,000  50,000  48,000
Net Profit for the quarter
10,000   9,500   9,000
"""


class TestBankingFormatDetection:
    def test_banking_filing_detected(self) -> None:
        assert _is_banking_filing(_BANKING_RESULTS_TEXT) is True

    def test_non_banking_filing_not_detected(self) -> None:
        assert _is_banking_filing(_NON_BANKING_TEXT) is False

    def test_banking_facts_extract_net_profit(self) -> None:
        facts = _extract_banking_facts(_BANKING_RESULTS_TEXT, "2025-09-30", "quarterly")
        pat_facts = [f for f in facts if f.kind == FactKind.FINANCIAL_PAT]
        assert len(pat_facts) >= 1
        assert pat_facts[0].value == pytest.approx(20159.0)

    def test_banking_facts_period_assigned(self) -> None:
        facts = _extract_banking_facts(_BANKING_RESULTS_TEXT, "2025-09-30", "quarterly")
        pat = [f for f in facts if f.kind == FactKind.FINANCIAL_PAT]
        assert pat and pat[0].period == "2025-09-30"

    def test_no_banking_facts_when_no_profit_row(self) -> None:
        text = "Interest Earned\n86,182\nOther Income\n15,325\n"
        facts = _extract_banking_facts(text, "2025-09-30", "quarterly")
        assert facts == []

    def test_cover_letter_bank_name_detected(self) -> None:
        """Regression: heavily OCR-corrupted SBI PDFs have no readable 'Interest
        Earned' text; fallback detects 'Bank' in the cover letter instead."""
        ocr_text = (
            "State Bank of India\nBSE SCRIP Code: 500112\n"
            "lnt€resU dlacounl on advancea\n"  # OCR-corrupted "Interest/discount..."
            "86 182 58\n85 437 92\n"
        )
        assert _is_banking_filing(ocr_text) is True

    def test_non_bank_entity_not_triggered_by_cover_fallback(self) -> None:
        """A non-banking company with no 'Revenue from operations' line (e.g.,
        an NBFC disclosing only interest income without the banking P&L format)
        should NOT be mis-classified via the cover-letter fallback if the word
        'Bank' doesn't appear in the cover."""
        text = (
            "Tata Consultancy Services Ltd\nQ2FY26 Quarterly Results\n"
            "Exceptional items and other disclosures\n"
            "10,000 9,500 9,000\n"
        )
        assert _is_banking_filing(text) is False


class TestBankingFactKindsPresent:
    """Smoke-test that the new banking FactKind members exist in the ontology."""

    def test_nii_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_NET_INTEREST_INCOME")

    def test_nim_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_NET_INTEREST_MARGIN")

    def test_gross_npa_ratio_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_GROSS_NPA_RATIO")

    def test_net_npa_ratio_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_NET_NPA_RATIO")

    def test_pcr_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_PROVISION_COVERAGE_RATIO")

    def test_credit_cost_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_CREDIT_COST")

    def test_casa_ratio_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_CASA_RATIO")

    def test_car_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_CAPITAL_ADEQUACY_RATIO")

    def test_slippage_ratio_kind_exists(self) -> None:
        assert hasattr(FactKind, "FINANCIAL_SLIPPAGE_RATIO")
