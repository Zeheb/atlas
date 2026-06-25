import enum

from atlas.acquisition.evidence import EvidenceKind


class AcquisitionProfile(enum.Enum):
    DEFAULT = "default"


_PROFILE_KINDS: dict[AcquisitionProfile, frozenset[EvidenceKind]] = {
    AcquisitionProfile.DEFAULT: frozenset(
        {
            EvidenceKind.ANNUAL_REPORT,
            EvidenceKind.FINANCIAL_RESULTS,
            EvidenceKind.EARNINGS_TRANSCRIPT,
            EvidenceKind.INVESTOR_PRESENTATION,
        }
    ),
}


def kinds_for_profile(profile: AcquisitionProfile) -> frozenset[EvidenceKind]:
    return _PROFILE_KINDS[profile]
