from unittest.mock import MagicMock

from atlas.acquisition.connectors.bse import BSEConnector
from atlas.acquisition.connectors.connector import Company, Connector, DiscoveryResult


class TestConnectorProtocol:
    def test_bse_connector_satisfies_protocol(self) -> None:
        http = MagicMock()
        connector = BSEConnector(http=http)
        assert isinstance(connector, Connector)

    def test_object_without_discover_does_not_satisfy_protocol(self) -> None:
        class NoDiscover:
            def fetch_bytes(self, url: str) -> bytes:
                return b""

            def close(self) -> None:
                pass

            def __enter__(self) -> "NoDiscover":
                return self

            def __exit__(self, *args: object) -> None:
                pass

        assert not isinstance(NoDiscover(), Connector)

    def test_object_without_fetch_bytes_does_not_satisfy_protocol(self) -> None:
        class NoFetch:
            def discover(self, company: Company) -> DiscoveryResult:
                return DiscoveryResult(evidence=[])

            def close(self) -> None:
                pass

            def __enter__(self) -> "NoFetch":
                return self

            def __exit__(self, *args: object) -> None:
                pass

        assert not isinstance(NoFetch(), Connector)


class TestCompany:
    def test_default_exchange_identities_is_empty(self) -> None:
        company = Company(id="cmp_1", ticker="TCS")
        assert company.exchange_identities == {}

    def test_exchange_identities_is_mutable(self) -> None:
        company = Company(id="cmp_1", ticker="TCS")
        company.exchange_identities["BSE"] = {"scrip_code": 532540}
        assert company.exchange_identities["BSE"]["scrip_code"] == 532540

    def test_separate_instances_do_not_share_exchange_identities(self) -> None:
        a = Company(id="cmp_1", ticker="TCS")
        b = Company(id="cmp_2", ticker="INFY")
        a.exchange_identities["BSE"] = {"scrip_code": 1}
        assert "BSE" not in b.exchange_identities
