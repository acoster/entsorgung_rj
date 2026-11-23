"""Unit tests for `entsorgung_rj.transport`."""

from __future__ import annotations

import unittest
from unittest import mock

from entsorgung_rj.transport import (
    FetchTransport,
    HttpClientTransport,
    HttpRequest,
    HttpResponse,
)


class TestHttpClientTransport(unittest.TestCase):
    def test_https_request_with_query_and_body(self) -> None:
        fake_resp = mock.MagicMock()
        fake_resp.status = 200
        fake_resp.reason = "OK"
        fake_resp.read.return_value = b'{"ok": true}'

        fake_conn = mock.MagicMock()
        fake_conn.getresponse.return_value = fake_resp

        with mock.patch(
            "http.client.HTTPSConnection",
            return_value=fake_conn,
        ) as mock_https:
            transport = HttpClientTransport()
            resp = transport.send(
                HttpRequest(
                    method="POST",
                    url="https://example.com:8443/api/v1/test?foo=bar",
                    headers={"Accept": "application/json"},
                    body=b'{"a": 1}',
                    timeout=7.5,
                ),
            )

        mock_https.assert_called_once_with("example.com:8443", timeout=7.5)
        fake_conn.request.assert_called_once_with(
            "POST",
            "/api/v1/test?foo=bar",
            body=b'{"a": 1}',
            headers={"Accept": "application/json"},
        )
        fake_conn.close.assert_called_once()
        self.assertEqual(
            resp, HttpResponse(status=200, reason="OK", body='{"ok": true}')
        )

    def test_http_scheme_uses_http_connection_and_closes_on_error(self) -> None:
        fake_conn = mock.MagicMock()
        fake_conn.request.side_effect = OSError("connection refused")

        with mock.patch(
            "http.client.HTTPConnection",
            return_value=fake_conn,
        ) as mock_http:
            transport = HttpClientTransport()
            with self.assertRaises(OSError):
                transport.send(
                    HttpRequest(
                        method="GET",
                        url="http://localhost:8000/regions",
                        headers={},
                    ),
                )

        mock_http.assert_called_once_with("localhost:8000", timeout=15.0)
        fake_conn.close.assert_called_once()


class TestFetchTransport(unittest.IsolatedAsyncioTestCase):
    async def test_workers_fetch_style_response_with_text(self) -> None:
        captured: dict[str, object] = {}

        class FakeWorkersResponse:
            status = 200
            statusText = "OK"

            async def text(self) -> str:
                return '{"data": []}'

        async def fake_fetch(url: str, **kwargs: object) -> FakeWorkersResponse:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeWorkersResponse()

        transport = FetchTransport(fetch_fn=fake_fetch)
        resp = await transport.send(
            HttpRequest(
                method="POST",
                url="https://example.com/api/v1/register-device",
                headers={"Content-Type": "application/json"},
                body=b'{"x":1}',
            ),
        )

        self.assertEqual(captured["url"], "https://example.com/api/v1/register-device")
        self.assertEqual(
            captured["kwargs"],
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": '{"x":1}',
            },
        )
        self.assertEqual(
            resp, HttpResponse(status=200, reason="OK", body='{"data": []}')
        )

    async def test_pyfetch_style_response_with_string_and_reason_fallback(self) -> None:
        class FakePyfetchResponse:
            status = 404

            async def string(self) -> str:
                return '{"message": "missing"}'

        async def fake_pyfetch(url: str, **kwargs: object) -> FakePyfetchResponse:
            self.assertNotIn("body", kwargs)
            return FakePyfetchResponse()

        transport = FetchTransport(fetch_fn=fake_pyfetch)
        resp = await transport.send(
            HttpRequest(
                method="GET",
                url="https://example.com/api/v1/regions",
                headers={"Accept": "application/json"},
            ),
        )
        self.assertEqual(
            resp,
            HttpResponse(status=404, reason="Not Found", body='{"message": "missing"}'),
        )

    async def test_unsupported_response_object_raises_type_error(self) -> None:
        class BrokenResponse:
            status = 200

        async def fake_fetch(url: str, **kwargs: object) -> BrokenResponse:
            return BrokenResponse()

        transport = FetchTransport(fetch_fn=fake_fetch)
        with self.assertRaises(TypeError):
            await transport.send(
                HttpRequest(method="GET", url="https://example.com", headers={}),
            )

    async def test_missing_default_fetch_raises_runtime_error(self) -> None:
        transport = FetchTransport()
        with self.assertRaises(RuntimeError) as ctx:
            await transport.send(
                HttpRequest(method="GET", url="https://example.com", headers={}),
            )
        self.assertIn("No async fetch implementation found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
