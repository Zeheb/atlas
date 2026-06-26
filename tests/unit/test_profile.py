from datetime import datetime, timezone

from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource
from atlas.acquisition.profile import (
    DEFAULT_PROFILE,
    AcquisitionProfile,
    KindFilterProfile,
)


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
# AcquisitionProfile protocol
# ---------------------------------------------------------------------------


class TestAcquisitionProfileProtocol:
    def test_kind_filter_profile_satisfies_protocol(self) -> None:
        profile = KindFilterProfile("test", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert isinstance(profile, AcquisitionProfile)

    def test_default_profile_satisfies_protocol(self) -> None:
        assert isinstance(DEFAULT_PROFILE, AcquisitionProfile)


# ---------------------------------------------------------------------------
# KindFilterProfile
# ---------------------------------------------------------------------------


class TestKindFilterProfile:
    def test_name_returns_configured_name(self) -> None:
        profile = KindFilterProfile("my-profile", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert profile.name == "my-profile"

    def test_select_returns_only_matching_kinds(self) -> None:
        profile = KindFilterProfile("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
            _make_evidence("e3", EvidenceKind.FINANCIAL_RESULTS),
        ]
        result = profile.select(evidence)
        assert len(result) == 1
        assert result[0].evidence_id == "e1"

    def test_select_empty_input_returns_empty(self) -> None:
        profile = KindFilterProfile("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        assert profile.select([]) == []

    def test_select_no_matching_kinds_returns_empty(self) -> None:
        profile = KindFilterProfile("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [_make_evidence("e1", EvidenceKind.NEWS)]
        assert profile.select(evidence) == []

    def test_select_does_not_mutate_input(self) -> None:
        profile = KindFilterProfile("p", frozenset({EvidenceKind.ANNUAL_REPORT}))
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
        ]
        original_len = len(evidence)
        profile.select(evidence)
        assert len(evidence) == original_len

    def test_select_with_multiple_allowed_kinds(self) -> None:
        profile = KindFilterProfile(
            "p",
            frozenset({EvidenceKind.ANNUAL_REPORT, EvidenceKind.FINANCIAL_RESULTS}),
        )
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.FINANCIAL_RESULTS),
            _make_evidence("e3", EvidenceKind.NEWS),
        ]
        result = profile.select(evidence)
        assert len(result) == 2
        ids = {e.evidence_id for e in result}
        assert ids == {"e1", "e2"}

    def test_select_all_matching_returns_all(self) -> None:
        profile = KindFilterProfile(
            "p",
            frozenset({EvidenceKind.ANNUAL_REPORT, EvidenceKind.NEWS}),
        )
        evidence = [
            _make_evidence("e1", EvidenceKind.ANNUAL_REPORT),
            _make_evidence("e2", EvidenceKind.NEWS),
        ]
        assert len(profile.select(evidence)) == 2


# ---------------------------------------------------------------------------
# DEFAULT_PROFILE
# ---------------------------------------------------------------------------


class TestDefaultProfile:
    def test_name_is_default(self) -> None:
        assert DEFAULT_PROFILE.name == "default"

    def test_includes_annual_report(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.ANNUAL_REPORT)]
        assert len(DEFAULT_PROFILE.select(ev)) == 1

    def test_includes_financial_results(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.FINANCIAL_RESULTS)]
        assert len(DEFAULT_PROFILE.select(ev)) == 1

    def test_includes_earnings_transcript(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.EARNINGS_TRANSCRIPT)]
        assert len(DEFAULT_PROFILE.select(ev)) == 1

    def test_includes_investor_presentation(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.INVESTOR_PRESENTATION)]
        assert len(DEFAULT_PROFILE.select(ev)) == 1

    def test_excludes_news(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.NEWS)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_excludes_dividend(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.DIVIDEND)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_excludes_agm_notice(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.AGM_NOTICE)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_excludes_brsr(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.BRSR)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_excludes_regulatory_filing(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.REGULATORY_FILING)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_excludes_other(self) -> None:
        ev = [_make_evidence("e1", EvidenceKind.OTHER)]
        assert DEFAULT_PROFILE.select(ev) == []

    def test_selects_exactly_four_kinds(self) -> None:
        all_evidence = [_make_evidence(f"e{i}", k) for i, k in enumerate(EvidenceKind)]
        result = DEFAULT_PROFILE.select(all_evidence)
        assert len(result) == 4
