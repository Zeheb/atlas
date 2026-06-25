from atlas.acquisition.evidence import EvidenceKind
from atlas.acquisition.profile import AcquisitionProfile, kinds_for_profile


class TestAcquisitionProfileEnum:
    def test_default_variant_exists(self) -> None:
        assert AcquisitionProfile.DEFAULT.value == "default"


class TestKindsForProfile:
    def test_returns_frozenset(self) -> None:
        result = kinds_for_profile(AcquisitionProfile.DEFAULT)
        assert isinstance(result, frozenset)

    def test_default_includes_annual_report(self) -> None:
        assert EvidenceKind.ANNUAL_REPORT in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_includes_financial_results(self) -> None:
        assert EvidenceKind.FINANCIAL_RESULTS in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_includes_earnings_transcript(self) -> None:
        assert EvidenceKind.EARNINGS_TRANSCRIPT in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_includes_investor_presentation(self) -> None:
        assert EvidenceKind.INVESTOR_PRESENTATION in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_excludes_regulatory_filing(self) -> None:
        assert EvidenceKind.REGULATORY_FILING not in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_excludes_news(self) -> None:
        assert EvidenceKind.NEWS not in kinds_for_profile(AcquisitionProfile.DEFAULT)

    def test_default_excludes_dividend(self) -> None:
        assert EvidenceKind.DIVIDEND not in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_excludes_agm_notice(self) -> None:
        assert EvidenceKind.AGM_NOTICE not in kinds_for_profile(
            AcquisitionProfile.DEFAULT
        )

    def test_default_excludes_brsr(self) -> None:
        assert EvidenceKind.BRSR not in kinds_for_profile(AcquisitionProfile.DEFAULT)

    def test_default_excludes_other(self) -> None:
        assert EvidenceKind.OTHER not in kinds_for_profile(AcquisitionProfile.DEFAULT)

    def test_default_has_exactly_four_kinds(self) -> None:
        assert len(kinds_for_profile(AcquisitionProfile.DEFAULT)) == 4

    def test_result_is_immutable(self) -> None:
        result = kinds_for_profile(AcquisitionProfile.DEFAULT)
        try:
            result.add(EvidenceKind.NEWS)  # type: ignore[attr-defined]
            assert False, "frozenset should not be mutable"
        except AttributeError:
            pass
