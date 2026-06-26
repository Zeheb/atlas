from datetime import datetime, timezone

from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource
from atlas.acquisition.policy import DEFAULT_POLICY, AcquisitionPolicy, KindFilterPolicy


def _make_evidence(evidence_id: str, kind: EvidenceKind) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        company_id="cmp_test",
        source=EvidenceSource.BSE,
        kind=kind,
        title=f"Report {evidence_id}",
        source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        document_url=None,
        file_size_bytes=None,
    )


# ---------------------------------------------------------------------------
# AcquisitionPolicy protocol
# ---------------------------------------------------------------------------


class TestAcquisitionPolicyProtocol:
    def test_kind_filter_policy_satisfies_protocol(self) -> None:
        policy = KindFilterPolicy("test", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert isinstance(policy, AcquisitionPolicy)

    def test_default_policy_satisfies_protocol(self) -> None:
        assert isinstance(DEFAULT_POLICY, AcquisitionPolicy)


# ---------------------------------------------------------------------------
# KindFilterPolicy
# ---------------------------------------------------------------------------


class TestKindFilterPolicy:
    def test_name_returns_configured_name(self) -> None:
        policy = KindFilterPolicy("my-policy", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert policy.name == "my-policy"

    def test_select_returns_only_matching_kinds(self) -> None:
        policy = KindFilterPolicy("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
            _make_evidence("e3", EvidenceKind.FINANCIAL_RESULTS),
        ]
        result = policy.select(evidence)
        assert len(result) == 1
        assert result[0].evidence_id == "e1"

    def test_select_empty_input_returns_empty(self) -> None:
        policy = KindFilterPolicy("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert policy.select([]) == []

    def test_select_no_matching_kinds_returns_empty(self) -> None:
        policy = KindFilterPolicy("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [_make_evidence("e1", EvidenceKind.NEWS)]
        assert policy.select(evidence) == []

    def test_select_does_not_mutate_input(self) -> None:
        policy = KindFilterPolicy("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
        ]
        original_len = len(evidence)
        policy.select(evidence)
        assert len(evidence) == original_len

    def test_select_with_multiple_allowed_kinds(self) -> None:
        policy = KindFilterPolicy(
            "p",
            frozenset({EvidenceKind.ANNUAL_REPORT, EvidenceKind.FINANCIAL_RESULTS}),
        )
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.FINANCIAL_RESULTS),
            _make_evidence("e3", EvidenceKind.NEWS),
        ]
        result = policy.select(evidence)
        assert len(result) == 2
        ids = {e.evidence_id for e in result}
        assert ids == {"e1", "e2"}

    def test_select_all_matching_returns_all(self) -> None:
        policy = KindFilterPolicy(
            "p",
            frozenset({EvidenceKind.ANNUAL_REPORT, EvidenceKind.NEWS}),
        )
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
        ]
        assert len(policy.select(evidence)) == 2


# ---------------------------------------------------------------------------
# DEFAULT_POLICY
# ---------------------------------------------------------------------------


class TestDefaultPolicy:
    def test_name_is_default(self) -> None:
        assert DEFAULT_POLICY.name == "default"

    def test_includes_annual_report(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.ANNUAL_REPORT)]
        assert len(DEFAULT_POLICY.select(ev)) == 1

    def test_includes_financial_results(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.FINANCIAL_RESULTS)]
        assert len(DEFAULT_POLICY.select(ev)) == 1

    def test_includes_earnings_transcript(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.EARNINGS_TRANSCRIPT)]
        assert len(DEFAULT_POLICY.select(ev)) == 1

    def test_includes_investor_presentation(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.INVESTOR_PRESENTATION)]
        assert len(DEFAULT_POLICY.select(ev)) == 1

    def test_excludes_news(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.NEWS)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_excludes_dividend(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.DIVIDEND)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_excludes_agm_notice(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.AGM_NOTICE)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_excludes_brsr(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.BRSR)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_excludes_regulatory_filing(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.REGULATORY_FILING)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_excludes_other(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.OTHER)]
        assert DEFAULT_POLICY.select(ev) == []

    def test_selects_exactly_four_kinds(self) -> None:
        all_evidence = [_make_evidence(f"e{i}", k) for i, k in enumerate(EvidenceKind)]
        result = DEFAULT_POLICY.select(all_evidence)
        assert len(result) == 4
