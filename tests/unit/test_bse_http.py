from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from atlas.acquisition.connectors.bse_http import BSEHttpClient
from atlas.config.settings import Settings


def make_client(rate_limit_rps: float = 100.0, max_retries: int = 2) -> BSEHttpClient:
    settings = Settings(
        repository_base_path=Path("."),
        http_rate_limit_rps=rate_limit_rps,
        http_max_retries=max_retries,
        http_timeout_seconds=30,
    )
    return BSEHttpClient(settings)


def ok_response(body: object = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.json.return_value = body if body is not None else {}
    resp.raise_for_status.return_value = None
    return resp


def rate_limit_response() -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 429
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def error_response(status: int = 500) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_warm_up_get_is_called_on_first_use(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = ok_response()
        mock_cls.return_value = session

        client = make_client()
        client._ensure_session()

        session.get.assert_called_once_with("https://www.bseindia.com/", timeout=30)

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_session_created_only_once(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = ok_response()
        mock_cls.return_value = session

        client = make_client()
        client._ensure_session()
        client._ensure_session()

        assert mock_cls.call_count == 1

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_headers_are_set_on_session(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = ok_response()
        mock_cls.return_value = session

        client = make_client()
        client._ensure_session()

        session.headers.update.assert_called_once()
        headers = session.headers.update.call_args[0][0]
        assert headers["Origin"] == "https://www.bseindia.com/"
        assert headers["Referer"] == "https://www.bseindia.com/"

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_close_sets_session_to_none(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = ok_response()
        mock_cls.return_value = session

        client = make_client()
        client._ensure_session()
        client.close()

        assert client._session is None
        session.close.assert_called_once()

    def test_close_on_unused_client_is_safe(self) -> None:
        client = make_client()
        client.close()  # must not raise

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_context_manager_calls_close_on_exit(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = ok_response()
        mock_cls.return_value = session

        with make_client() as client:
            client._ensure_session()

        session.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_json
# ---------------------------------------------------------------------------


class TestGetJson:
    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_returns_parsed_json(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response(), ok_response({"key": "value"})]
        mock_cls.return_value = session

        client = make_client()
        result = client.get_json("SomeEndpoint/w", {})
        assert result == {"key": "value"}

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_raises_on_server_error(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response(), error_response(500)]
        mock_cls.return_value = session

        client = make_client()
        with pytest.raises(requests.HTTPError):
            client.get_json("SomeEndpoint/w", {})

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    @patch("atlas.acquisition.connectors.bse_http.time.sleep")
    def test_retries_on_429_then_succeeds(
        self, mock_sleep: MagicMock, mock_cls: MagicMock
    ) -> None:
        session = MagicMock()
        session.get.side_effect = [
            ok_response(),  # warm-up
            rate_limit_response(),  # attempt 0 → 429
            ok_response({"ok": True}),  # attempt 1 → 200
        ]
        mock_cls.return_value = session

        client = make_client(max_retries=2)
        result = client.get_json("SomeEndpoint/w", {})
        assert result == {"ok": True}
        mock_sleep.assert_called()

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    @patch("atlas.acquisition.connectors.bse_http.time.sleep")
    def test_raises_after_exhausting_retries(
        self, mock_sleep: MagicMock, mock_cls: MagicMock
    ) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response()] + [rate_limit_response()] * 3
        mock_cls.return_value = session

        client = make_client(max_retries=2)
        with pytest.raises(requests.HTTPError):
            client.get_json("SomeEndpoint/w", {})

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_constructs_correct_url(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response(), ok_response()]
        mock_cls.return_value = session

        client = make_client()
        client.get_json("MyEndpoint/w", {"foo": "bar"})

        call_url = session.get.call_args_list[1][0][0]
        assert call_url == "https://api.bseindia.com/BseIndiaAPI/api/MyEndpoint/w"

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_passes_params_to_session_get(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response(), ok_response()]
        mock_cls.return_value = session

        client = make_client()
        client.get_json("Endpoint/w", {"a": 1, "b": "x"})

        call_kwargs = session.get.call_args_list[1][1]
        assert call_kwargs["params"] == {"a": 1, "b": "x"}


# ---------------------------------------------------------------------------
# get_bytes
# ---------------------------------------------------------------------------


class TestGetBytes:
    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_returns_response_content(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.content = b"pdf-bytes"
        session.get.side_effect = [ok_response(), resp]
        mock_cls.return_value = session

        client = make_client()
        result = client.get_bytes("https://example.com/file.pdf")
        assert result == b"pdf-bytes"

    @patch("atlas.acquisition.connectors.bse_http.requests.Session")
    def test_raises_on_error(self, mock_cls: MagicMock) -> None:
        session = MagicMock()
        session.get.side_effect = [ok_response(), error_response(404)]
        mock_cls.return_value = session

        client = make_client()
        with pytest.raises(requests.HTTPError):
            client.get_bytes("https://example.com/missing.pdf")
