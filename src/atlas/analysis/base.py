"""Core types shared by all evidence analyzers.

Every analyzer returns an AnalysisResult. The envelope is identical across
evidence kinds; variation lives in which FactKind values appear in `facts`
and which keys appear in `excerpts`.

Design principles:
- FactKind replaces free-form dotted strings: invalid kinds are NameErrors.
- FactUnit is a closed vocabulary; None signals categorical or textual facts.
- Provenance is structured so char_offset and page numbers can be added later.
- confidence lives on individual facts AND on the result. Fact-level confidence
  reflects extraction certainty for that specific value. Result-level confidence
  is set by the analyzer to reflect how well the PRIMARY facts for that document
  type were found — it is not a mechanical aggregation.
- Lists of things (segments, risks) are multiple AnalysisFact instances with
  the same kind, not list-valued facts. Every fact is scalar.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from atlas.knowledge.entities import Entity


class FactKind(enum.Enum):
    """All extractable fact types across all evidence kinds.

    Groups:
      REPORT_*      — filing identity and period metadata
      FINANCIAL_*   — P&L statement line items (quantitative)
      CAPITAL_*     — capital allocation events (quantitative + categorical)
      SEGMENT_*     — business segment data (categorical + quantitative)
      RISK_*        — risk factors (textual)
      STRATEGY_*    — strategic priorities and management guidance (textual)
      AUDIT_*       — auditor details and opinion (categorical)
      EXCEPTIONAL_* — one-off items that affect period comparability
      GOVERNANCE_*  — board and director data (categorical)
    """

    # Filing identity
    REPORT_PERIOD_END = "report_period_end"       # ISO date of period end
    REPORT_PERIOD_TYPE = "report_period_type"     # "quarterly" | "half_yearly" | "annual"
    REPORT_BASIS = "report_basis"                 # "consolidated" | "standalone"

    # P&L line items (all quantitative, unit=CRORE_INR unless noted)
    FINANCIAL_REVENUE = "financial_revenue"
    FINANCIAL_OTHER_INCOME = "financial_other_income"
    FINANCIAL_TOTAL_INCOME = "financial_total_income"
    FINANCIAL_EMPLOYEE_COST = "financial_employee_cost"
    FINANCIAL_EQUIPMENT_SOFTWARE_COST = "financial_equipment_software_cost"
    FINANCIAL_FINANCE_COST = "financial_finance_cost"
    FINANCIAL_DEPRECIATION = "financial_depreciation"
    FINANCIAL_OTHER_EXPENSES = "financial_other_expenses"
    FINANCIAL_TOTAL_EXPENSES = "financial_total_expenses"
    FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL = "financial_profit_before_exceptional"
    FINANCIAL_PROFIT_BEFORE_TAX = "financial_profit_before_tax"
    FINANCIAL_CURRENT_TAX = "financial_current_tax"
    FINANCIAL_DEFERRED_TAX = "financial_deferred_tax"
    FINANCIAL_TOTAL_TAX = "financial_total_tax"
    FINANCIAL_PAT = "financial_pat"               # "Profit for the period" in Ind AS
    FINANCIAL_EPS_BASIC = "financial_eps_basic"   # unit=RUPEES
    FINANCIAL_EPS_DILUTED = "financial_eps_diluted"

    # Capital allocation events
    CAPITAL_DIVIDEND_PER_SHARE = "capital_dividend_per_share"    # unit=RUPEES_PER_SHARE
    CAPITAL_DIVIDEND_TYPE = "capital_dividend_type"              # "interim" | "final" | ...
    CAPITAL_DIVIDEND_RECORD_DATE = "capital_dividend_record_date"  # ISO date
    CAPITAL_DIVIDEND_PAYMENT_DATE = "capital_dividend_payment_date"
    CAPITAL_BUYBACK_AMOUNT = "capital_buyback_amount"            # unit=CRORE_INR
    CAPITAL_BUYBACK_PRICE_PER_SHARE = "capital_buyback_price_per_share"  # unit=RUPEES_PER_SHARE
    CAPITAL_BUYBACK_SHARES_OFFERED = "capital_buyback_shares_offered"    # max shares targeted; unit=COUNT
    CAPITAL_BUYBACK_RECORD_DATE = "capital_buyback_record_date"          # eligibility cut-off; unit=ISO_DATE
    CAPITAL_BUYBACK_SHARES_BOUGHT = "capital_buyback_shares_bought"      # shares actually extinguished; unit=COUNT

    # M&A and subsidiary events (capital deployment)
    CAPITAL_ACQ_TARGET_NAME = "capital_acq_target_name"          # entity name as stated in filing; unit=None
    CAPITAL_ACQ_CONSIDERATION_TYPE = "capital_acq_consideration_type"  # "cash"|"share_swap"|"subscription"
    CAPITAL_ACQ_ENTERPRISE_VALUE = "capital_acq_enterprise_value"  # numeric; unit=USD_MILLION|USD_BILLION|CRORE_INR
    CAPITAL_ACQ_STAKE_PCT = "capital_acq_stake_pct"              # unit=PERCENT
    CAPITAL_ACQ_EXPECTED_COMPLETION = "capital_acq_expected_completion"  # ISO date; unit=ISO_DATE

    # Subsidiary investment / external fundraise events
    CAPITAL_INVEST_TARGET_NAME = "capital_invest_target_name"  # subsidiary receiving the investment; unit=None
    CAPITAL_INVEST_AMOUNT = "capital_invest_amount"            # committed capital; unit=CRORE_INR|USD_BILLION

    # Board-approved equity / debt fundraising (QIP, rights, preferential, NCD)
    CAPITAL_FUNDRAISE_TYPE   = "capital_fundraise_type"    # "QIP"|"rights_issue"|"preferential_allotment"|"NCD"; unit=None
    CAPITAL_FUNDRAISE_AMOUNT = "capital_fundraise_amount"  # max amount authorised; unit=CRORE_INR

    # Business segment data
    SEGMENT_NAME = "segment_name"                 # textual; one fact per segment
    SEGMENT_GROWTH_PCT = "segment_growth_pct"     # unit=PERCENT
    SEGMENT_REVENUE = "segment_revenue"           # unit=CRORE_INR
    SEGMENT_EBIT = "segment_ebit"                 # Ind AS 108 segment result (EBIT); unit=CRORE_INR; period=quarter/year end

    # Risk factors (textual, one fact per risk)
    RISK_FACTOR = "risk_factor"

    # Strategy and management guidance (textual)
    STRATEGY_PRIORITY = "strategy_priority"
    STRATEGY_GUIDANCE = "strategy_guidance"
    STRATEGY_ASPIRATION = "strategy_aspiration"   # company-level strategic vision; unit=None
    STRATEGY_CSAT = "strategy_csat"               # customer satisfaction score; unit=PERCENT; period=half-year end

    # Audit
    AUDIT_OPINION = "audit_opinion"               # "unmodified" | "qualified" | ...
    AUDIT_FIRM = "audit_firm"
    AUDIT_KAM_TITLE = "audit_kam_title"           # Key Audit Matter title text; unit=None; textual

    # Exceptional items
    EXCEPTIONAL_DESCRIPTION = "exceptional_description"   # textual
    EXCEPTIONAL_AMOUNT = "exceptional_amount"             # unit=CRORE_INR

    # Governance — board and director data
    # Director / KMP changes (grouped by section "director_change_N" in board_outcome)
    GOVERNANCE_DIRECTOR             = "governance_director"               # full name; unit=None
    GOVERNANCE_DIRECTOR_CHANGE_TYPE = "governance_director_change_type"  # "appointment"|"reappointment"|"resignation"; unit=None
    GOVERNANCE_DIRECTOR_CHANGE_ROLE = "governance_director_change_role"  # role string; unit=None

    # AGM voting results (one fact per resolution; period=AGM date; section="resolution_N")
    GOVERNANCE_RESOLUTION_TITLE   = "governance_resolution_title"    # agenda text; unit=None
    GOVERNANCE_RESOLUTION_TYPE    = "governance_resolution_type"     # "ordinary" | "special"; unit=None
    GOVERNANCE_RESOLUTION_OUTCOME = "governance_resolution_outcome"  # "passed" | "not_passed"; unit=None
    GOVERNANCE_VOTE_PCT_FOR       = "governance_vote_pct_for"        # % votes in favour on polled; unit=PERCENT
    GOVERNANCE_VOTE_PCT_AGAINST   = "governance_vote_pct_against"    # % votes against on polled; unit=PERCENT

    # Related-party disclosures (M-P3.3, ADR-0012). One fact per disclosed row;
    # period=as-at date; section="rpt_row_N" (same row-grouping discipline as
    # "resolution_N"/"director_change_N"). GOVERNANCE_RPT_BALANCE_AMOUNT only
    # -- the flow-side counterpart (per-counterparty transaction amounts) is
    # NOT extracted in this milestone: the source table has an open-ended,
    # not-fully-observed category vocabulary and a variable value-count per
    # row, and the same counterparty recurs under different categories in the
    # same period (a real collision risk without reliable category tracking).
    # Deferred rather than shipped on an untested scanner -- see ADR-0012.
    GOVERNANCE_RPT_BALANCE_AMOUNT = "governance_rpt_balance_amount"   # aggregate related-party balance (e.g. "Loans to related parties"); unit=CRORE_INR
    GOVERNANCE_RPT_CATEGORY       = "governance_rpt_category"        # the disclosed line's own label text; unit=None

    # Ownership structure (shareholding pattern — all at quarter-end; unit=PERCENT unless noted)
    OWNERSHIP_TOTAL_SHARES = "ownership_total_shares"               # unit=COUNT
    OWNERSHIP_PROMOTER_PCT = "ownership_promoter_pct"               # promoter + promoter group
    OWNERSHIP_PROMOTER_PLEDGED_PCT = "ownership_promoter_pledged_pct"  # % of promoter shares pledged
    OWNERSHIP_FPI_PCT = "ownership_fpi_pct"                         # foreign portfolio investors (all categories)
    OWNERSHIP_DII_PCT = "ownership_dii_pct"                         # domestic institutional investors
    OWNERSHIP_MF_PCT = "ownership_mf_pct"                           # mutual funds / UTI
    OWNERSHIP_INSURANCE_PCT = "ownership_insurance_pct"             # insurance companies
    OWNERSHIP_PUBLIC_PCT = "ownership_public_pct"                   # public (non-promoter) total
    OWNERSHIP_RETAIL_PCT = "ownership_retail_pct"                   # retail individuals (nominal ≤ ₹2L)
    OWNERSHIP_HNI_PCT = "ownership_hni_pct"                         # HNI individuals (nominal > ₹2L)
    OWNERSHIP_NRI_PCT = "ownership_nri_pct"                         # non-resident Indians

    # Credit / ESG ratings (one CREDIT_AGENCY per document; one row of
    # CREDIT_INSTRUMENT/RATING/ACTION/OUTLOOK/AMOUNT per rated instrument)
    CREDIT_AGENCY      = "credit_agency"      # text; "CRISIL", "ICRA", "NSE Sustainability"
    CREDIT_INSTRUMENT  = "credit_instrument"  # text; "Long-term Bank Facilities" | "Commercial Paper" | "ESG"
    CREDIT_AMOUNT      = "credit_amount"      # unit=CRORE_INR; rated ceiling — absent for ESG / unsolicited
    CREDIT_RATING      = "credit_rating"      # text; "AAA" | "A1+" | "73" | "CRISIL ESG 74"
    CREDIT_OUTLOOK     = "credit_outlook"     # text; "stable"|"positive"|"negative"|"watch"|"leader"|"leadership"
    CREDIT_ACTION      = "credit_action"      # text; "assigned"|"reaffirmed"|"upgraded"|"downgraded"|"withdrawn"

    # Earnings call transcript metrics (spoken data not directly in XBRL)
    FINANCIAL_TCV              = "financial_tcv"              # Total Contract Value; unit=USD_BILLION; quarterly
    FINANCIAL_OPERATING_MARGIN = "financial_operating_margin" # operating margin %; unit=PERCENT
    FINANCIAL_NET_MARGIN       = "financial_net_margin"       # net income margin %; unit=PERCENT
    FINANCIAL_ROE              = "financial_roe"              # return on equity; unit=PERCENT; period=fiscal year end
    FINANCIAL_FCF              = "financial_fcf"              # management-defined FCF after all investments; unit=CRORE_INR; period=fiscal year end

    # Balance sheet items (annual financial results only; period = fiscal year end)
    FINANCIAL_CASH_AND_EQUIVALENTS = "financial_cash_and_equivalents"  # GAAP cash and cash equivalents; unit=CRORE_INR
    FINANCIAL_TOTAL_DEBT           = "financial_total_debt"            # total borrowings; unit=CRORE_INR; absent for debt-free companies
    FINANCIAL_TOTAL_EQUITY         = "financial_total_equity"          # equity attributable to parent shareholders (excl. NCI); unit=CRORE_INR
    # Working-capital items (M-P3.1, ADR-0012). Current-assets/liabilities
    # only; unit=CRORE_INR. Absence = not extracted, not zero (same
    # convention as every other balance-sheet fact above).
    FINANCIAL_INVENTORIES          = "financial_inventories"           # current-assets Inventories line
    FINANCIAL_TRADE_RECEIVABLES    = "financial_trade_receivables"     # billed/invoiced trade receivables only (the sub-line, when a Billed/Unbilled split is disclosed; the single reported figure otherwise) — never includes FINANCIAL_UNBILLED_REVENUE, kept additive/non-overlapping
    FINANCIAL_TRADE_PAYABLES       = "financial_trade_payables"        # sum of MSME + non-MSME outstanding-dues sub-lines (Schedule III mandatory split)
    FINANCIAL_UNBILLED_REVENUE     = "financial_unbilled_revenue"      # contract-asset / unbilled revenue; disclosed separately from trade receivables where a Billed/Unbilled split exists (IT-services specific — will not fire for most companies, same class as FINANCIAL_TCV)

    # Cash flow statement items (annual financial results only; period = fiscal year end)
    FINANCIAL_OPERATING_CASH_FLOW = "financial_operating_cash_flow"   # net cash from operating activities; unit=CRORE_INR
    FINANCIAL_CAPEX               = "financial_capex"                  # PP&E purchases only; unit=CRORE_INR; absolute value
    FINANCIAL_CASH_TAX_PAID       = "financial_cash_tax_paid"          # "Taxes paid (net of refunds)" from the cash flow statement; unit=CRORE_INR; absolute value — the cash-basis counterpart to FINANCIAL_TOTAL_TAX/FINANCIAL_CURRENT_TAX (book basis)

    # Notes-to-accounts items (M-P3.2, ADR-0012). unit=CRORE_INR. Absence =
    # not extracted, not zero, same convention as every balance-sheet fact.
    FINANCIAL_INTANGIBLE_ASSETS   = "financial_intangible_assets"      # net intangible assets (incl. "Other intangible assets"); excludes goodwill
    FINANCIAL_GROSS_BLOCK         = "financial_gross_block"            # gross (pre-depreciation) carrying value of property, plant and equipment, whole-company total — from the annual report's PPE movement schedule or financial-highlights table, not the financial_results balance sheet

    # Banking / NBFC financial metrics (broadly applicable across financial sector)
    # Period conventions: quarterly KPIs use quarter-end date; annual KPIs use
    # fiscal year-end date.  Ratio facts use unit=PERCENT; stock/flow facts use
    # unit=CRORE_INR.
    FINANCIAL_NET_INTEREST_INCOME     = "financial_net_interest_income"      # NII = interest income − interest expense; unit=CRORE_INR
    FINANCIAL_NET_INTEREST_MARGIN     = "financial_net_interest_margin"      # NIM = NII / avg earning assets; unit=PERCENT
    FINANCIAL_GROSS_NPA_RATIO         = "financial_gross_npa_ratio"          # Gross NPA / Gross Advances; unit=PERCENT
    FINANCIAL_NET_NPA_RATIO           = "financial_net_npa_ratio"            # Net NPA / Net Advances; unit=PERCENT
    FINANCIAL_PROVISION_COVERAGE_RATIO = "financial_provision_coverage_ratio" # provisions held / gross NPA; unit=PERCENT
    FINANCIAL_CREDIT_COST             = "financial_credit_cost"              # provisioning expense / avg advances; unit=PERCENT
    FINANCIAL_CASA_RATIO              = "financial_casa_ratio"               # (current + savings deposits) / total deposits; unit=PERCENT
    FINANCIAL_CAPITAL_ADEQUACY_RATIO  = "financial_capital_adequacy_ratio"   # CRAR / CAR (Basel III Tier1+Tier2); unit=PERCENT
    FINANCIAL_SLIPPAGE_RATIO          = "financial_slippage_ratio"           # fresh NPA additions / opening standard advances; unit=PERCENT

    # Physical operating volumes (industrial / manufacturing companies)
    # Cross-sector concept: any company reporting bulk physical output (steel,
    # cement, aluminium, etc.) discloses these in investor presentations even
    # when the financial_results filing carries only rupee figures.
    FINANCIAL_PRODUCTION_VOLUME = "financial_production_volume"  # physical output produced; unit=MILLION_TONNES|COUNT
    FINANCIAL_DELIVERY_VOLUME   = "financial_delivery_volume"    # physical volume sold/delivered; unit=MILLION_TONNES|COUNT

    # ESG — environmental, social, governance sustainability facts (BRSR source)
    # All yearly metrics: period = Indian fiscal year end ("YYYY-03-31")
    # All commitment facts: period = target year fiscal year end
    ESG_GHG_SCOPE1                     = "esg_ghg_scope1"                      # Scope 1 direct GHG; unit=TCO2E
    ESG_GHG_SCOPE2                     = "esg_ghg_scope2"                      # Scope 2 indirect GHG (market-based); unit=TCO2E
    ESG_GHG_SCOPE3                     = "esg_ghg_scope3"                      # Scope 3 value-chain GHG; unit=TCO2E
    ESG_ENERGY_TOTAL_MJ                = "esg_energy_total_mj"                 # Total energy consumption; unit=MEGAJOULE
    ESG_ENERGY_RENEWABLE_PCT           = "esg_energy_renewable_pct"            # Renewable fraction of total energy; unit=PERCENT
    ESG_WATER_CONSUMED_KL              = "esg_water_consumed_kl"               # Total water consumed; unit=KILOLITRE
    ESG_WASTE_GENERATED_MT             = "esg_waste_generated_mt"              # Total waste generated; unit=METRIC_TONNE
    ESG_WASTE_RECOVERY_PCT             = "esg_waste_recovery_pct"              # Waste recovered (recycled + reused) %; unit=PERCENT
    ESG_WORKFORCE_HEADCOUNT            = "esg_workforce_headcount"             # Total employees (permanent + other); unit=COUNT
    ESG_WORKFORCE_FEMALE_PCT           = "esg_workforce_female_pct"            # Female employees as % of total; unit=PERCENT
    ESG_WORKFORCE_FEMALE_WAGE_PCT      = "esg_workforce_female_wage_pct"       # Female gross wages as % of total wages; unit=PERCENT
    ESG_WORKFORCE_ATTRITION_PCT        = "esg_workforce_attrition_pct"         # Voluntary attrition rate for permanent employees; unit=PERCENT
    ESG_SAFETY_LTIFR                   = "esg_safety_ltifr"                    # Lost Time Injury Frequency Rate per million person-hours; unit=None
    ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT = "esg_climate_sbti_scope12_reduction_pct"  # SBTi Scope1+2 reduction target %; period=target FY end; unit=PERCENT
    ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT  = "esg_climate_sbti_scope3_reduction_pct"   # SBTi Scope3 reduction target %; period=target FY end; unit=PERCENT
    # ESG_CSR_SPEND: reserved — Companies Act s.135 mandatory CSR expenditure; unit=CRORE_INR;
    # primary source = annual_report Director's Report; populated when annual_report.py is built
    ESG_CSR_SPEND = "esg_csr_spend"


class FactUnit(enum.Enum):
    """Measurement units for quantitative facts. None for categorical/textual."""

    CRORE_INR = "crore_inr"
    RUPEES_PER_SHARE = "rupees_per_share"
    RUPEES = "rupees"
    PERCENT = "percent"
    COUNT = "count"
    ISO_DATE = "iso_date"
    USD_MILLION = "usd_million"
    USD_BILLION = "usd_billion"
    # ESG physical measurement units
    TCO2E = "tco2e"             # metric tonnes of CO2 equivalent (GHG emissions)
    MEGAJOULE = "megajoule"     # MJ — energy consumption
    KILOLITRE = "kilolitre"     # KL — water consumption
    METRIC_TONNE = "metric_tonne"  # MT — waste mass
    MILLION_TONNES = "million_tonnes"  # bulk production/delivery volume (steel, cement, etc.)


@dataclass
class Provenance:
    """Structured origin of one extracted fact.

    section:     Logical document section where the fact was found.
                 Examples: "P&L table", "cover letter", "segment paragraph",
                 "risk section", "EPS table".
    char_offset: Byte offset in the extracted text where the evidence starts.
                 Populated by extractors that track position; None otherwise.
    excerpt:     Short verbatim snippet (≤120 chars) that confirms the extraction.
                 This is a micro-proof, not the full section body. The full body
                 lives in AnalysisResult.excerpts.
    """

    section: str
    char_offset: int | None = None
    excerpt: str | None = None


@dataclass(frozen=True)
class EntityMention:
    """A resolved entity as it appeared in one document, with the context
    observed at that mention (ADR-0014, M-P1.2).

    Composes a knowledge-layer ``Entity`` (identity only — ADR-0013) with the
    analysis-context attributes that are NOT part of identity: the ``role`` the
    entity played here, the ``affiliation`` stated here, and the ``provenance``
    of the mention. Per ADR-0009 these attributes live on this wrapper, never on
    the shared ``Entity``. This is the payload of ``AnalysisResult.entities`` —
    the envelope's third output category, beside ``facts`` and ``excerpts``.

    entity:      The resolved identity (kind, canonical_name, aliases).
    role:        Role in this appearance ("analyst", "CFO", ...). None if unknown.
    affiliation: Organization stated for the entity here (an analyst's
                 institution). Free text in M-P1.2; org-entity resolution later.
    identifier:  A structured EXTERNAL identifier for the entity as stated here
                 (M-P1.4) — e.g. a director's DIN. Distinct from an alias (a
                 name variant) and from affiliation/role: it participates in
                 identity but is not a name. Optional; None for every mention
                 that carries no such identifier.
    question_text: The bounded verbatim text of the analyst's question turn
                 (M-P2.8), when this mention is an analyst's Q&A appearance.
                 A transport field only, carrying the builder its one required
                 value for that one case — not a general "quote" concept for
                 arbitrary attributed speech; None for every other mention.
    provenance:  Where in the document the mention was found.
    """

    entity: Entity
    role: str | None = None
    affiliation: str | None = None
    identifier: str | None = None
    question_text: str | None = None
    provenance: Provenance | None = None


@dataclass
class AnalysisFact:
    """A single extracted fact from one evidence document.

    kind:        What this fact represents. Consumers branch on kind, never
                 isinstance-check value.
    value:       The extracted value. Always scalar. Lists of things (multiple
                 segments, multiple risks) are multiple AnalysisFact instances
                 with the same kind, one per item.
    unit:        Measurement unit for quantitative facts. None for categorical
                 facts (AUDIT_OPINION, REPORT_BASIS) and textual facts
                 (RISK_FACTOR, STRATEGY_PRIORITY).
    period:      ISO date of the period this fact describes. Conventions:
                 - Annual report facts → fiscal year end date ("2024-03-31")
                 - Quarterly P&L facts → quarter end date ("2024-09-30")
                 - Timeless facts (auditor name, director) → None
    confidence:  How certain the extractor is that this value is correct.
                 "high"   — unambiguous match from structured content
                 "medium" — matched but relied on a pattern that could mismatch
                 "low"    — heuristic extraction; verify before using
    provenance:  Where in the document this fact was found.
    """

    kind: FactKind
    value: str | int | float | None
    unit: FactUnit | None
    period: str | None
    confidence: Literal["high", "medium", "low"]
    provenance: Provenance


@dataclass
class AnalysisResult:
    """Complete output of one analyzer run on one evidence document.

    The envelope is identical for every evidence kind. Evidence-specific
    variation lives entirely in which FactKind values appear in `facts`
    and which section names appear in `excerpts`.

    evidence_id:      Matches KnowledgeBase / catalog entry.
    kind:             EvidenceKind.value string.
    analyzer_version: Bump when extraction logic changes in a way that would
                      produce different facts from the same document. Lets a
                      future Facts layer detect stale cached results.
    confidence:       Result-level summary set EXPLICITLY by the analyzer.
                      Reflects how well the PRIMARY facts for this document
                      type were found — not a mechanical aggregate of fact
                      confidences. Set to "low" as the conservative default
                      if the analyzer doesn't set it.
    source_date:      When the document was filed or published (from the
                      catalog / KnowledgeBase). Distinct from analyzed_at.
                      Needed to temporally order event-based facts (dividends,
                      acquisitions) where AnalysisFact.period is None.
    warnings:         Non-fatal extraction issues. Empty on a clean run.
    facts:            All extracted structured facts. Each carries its own
                      confidence and provenance.
    excerpts:         Verbatim section bodies keyed by section name.
                      Kept for LLM reasoning and human review. Values are
                      substantial (hundreds to thousands of characters).
    analyzed_at:      UTC timestamp of extraction.
    """

    evidence_id: str
    kind: str
    analyzer_version: str
    confidence: Literal["high", "medium", "low"]
    source_date: datetime
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = field(default_factory=list)
    facts: list[AnalysisFact] = field(default_factory=list)
    excerpts: dict[str, str] = field(default_factory=dict)
    # ADR-0014 (M-P1.2): resolved entities surfaced by this analyzer — the
    # envelope's third output category, beside facts and excerpts. Empty for
    # every analyzer that does not emit entities; never serialized (AnalysisResult
    # is transient — CompanyStore persists only a provenance stub).
    entities: list["EntityMention"] = field(default_factory=list)


def _snip(text: str, offset: int = 0, length: int = 120) -> str:
    """Return a ≤length-char Provenance.excerpt snippet from text starting at offset."""
    start = max(0, offset)
    return text[start : start + length].replace("\n", " ").strip()


def _fact(
    kind: FactKind,
    value: str | float | int | None,
    unit: FactUnit | None,
    section: str,
    text: str,
    offset: int,
    confidence: Literal["high", "medium", "low"] = "high",
) -> AnalysisFact:
    """Construct an event-based AnalysisFact (period=None) with a Provenance excerpt."""
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=None,
        confidence=confidence,
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=_snip(text, offset),
        ),
    )
