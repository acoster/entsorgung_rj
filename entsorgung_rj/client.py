"""Sync and async API clients for the Entsorgung RJ REST backend."""

from __future__ import annotations

import http
import json
from typing import TYPE_CHECKING, Any, TypeVar

from entsorgung_rj.models import (
    ApiError,
    ClientIdentity,
    DistrictSchedule,
    filter_schedules,
    resolve_district,
)
from entsorgung_rj.transport import (
    DEFAULT_TIMEOUT,
    AsyncTransport,
    FetchTransport,
    HttpClientTransport,
    HttpRequest,
    HttpResponse,
    SyncTransport,
)

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Awaitable, Callable

BASE_URL = "https://wastedisposalschedule-be.adaptit.ch/api/v1/"
USER_AGENT = "Dart/3.1 (dart:io)"

_REREGISTER_STATUSES = frozenset(
    {http.HTTPStatus.BAD_REQUEST, http.HTTPStatus.UNAUTHORIZED},
)
_T = TypeVar("_T")


class _BaseEntsorgungClient:
    """Shared request-building and response-parsing logic (no I/O)."""

    def __init__(
        self,
        identity: ClientIdentity,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.identity = identity
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self._needs_registration = identity.is_new
        self._registered = False

    @property
    def anonymous_user_id(self) -> str:
        """Client anonymous UUID sent in auth headers and payloads."""
        return self.identity.anonymous_user_id

    @property
    def device_token(self) -> str:
        """Client device token sent in auth headers and payloads."""
        return self.identity.device_token

    def _auth_payload(self) -> dict[str, str]:
        return {
            "device-token": self.device_token,
            "anonymous-user-id": self.anonymous_user_id,
        }

    @staticmethod
    def _extract_error_message(body: str, fallback: str) -> str:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return fallback
        if isinstance(parsed, dict) and parsed.get("message"):
            return str(parsed["message"])
        return fallback

    def _build_request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> HttpRequest:
        url = self.base_url + endpoint.lstrip("/")
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if authenticated:
            headers["anonymous-user-id"] = self.anonymous_user_id
            headers["device-token"] = self.device_token

        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        return HttpRequest(
            method=method,
            url=url,
            headers=headers,
            body=data,
            timeout=self.timeout,
        )

    def _parse_response(
        self,
        method: str,
        endpoint: str,
        response: HttpResponse,
    ) -> dict[str, Any]:
        if response.status >= http.HTTPStatus.BAD_REQUEST:
            msg = self._extract_error_message(response.body, response.reason)
            raise ApiError(
                response.status,
                f"{method} {endpoint} -> {msg}",
                response.body,
            )

        if not response.body:
            return {}
        try:
            parsed = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ApiError(
                response.status,
                f"{method} {endpoint} -> invalid JSON response",
                response.body,
            ) from exc
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    @staticmethod
    def _parse_regions(resp: dict[str, Any]) -> list[dict[str, Any]]:
        data = resp.get("data", [])
        return data if isinstance(data, list) else []

    @staticmethod
    def _parse_schedules(resp: dict[str, Any]) -> dict[str, Any]:
        data = resp.get("data", {})
        if isinstance(data, list):
            return {"data": data}
        return data if isinstance(data, dict) else {}


class EntsorgungClient(_BaseEntsorgungClient):
    """Synchronous client for the Entsorgung RJ REST API (defaults to `http.client`)."""

    def __init__(
        self,
        identity: ClientIdentity,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: SyncTransport | None = None,
    ) -> None:
        super().__init__(identity, base_url=base_url, timeout=timeout)
        self._transport: SyncTransport = transport or HttpClientTransport()

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        req = self._build_request(
            method,
            endpoint,
            payload,
            authenticated=authenticated,
        )
        resp = self._transport.send(req)
        return self._parse_response(method, endpoint, resp)

    def _run_authenticated(self, action: Callable[[], _T]) -> _T:
        if self._needs_registration and not self._registered:
            self.register_device()
        try:
            return action()
        except ApiError as exc:
            if exc.status in _REREGISTER_STATUSES and not self._registered:
                self.register_device()
                return action()
            raise

    def register_device(self) -> dict[str, Any]:
        """POST /api/v1/register-device."""
        resp = self._request(
            "POST",
            "register-device",
            payload=self._auth_payload(),
            authenticated=False,
        )
        self._registered = True
        self._needs_registration = False
        return resp

    def get_regions(self) -> list[dict[str, Any]]:
        """GET /api/v1/regions -> list of {"id": int, "name": str}."""
        return self._parse_regions(
            self._request("GET", "regions", authenticated=True),
        )

    def set_region(self, region_id: int) -> dict[str, Any]:
        """POST /api/v1/set-region-preference."""
        return self._request(
            "POST",
            "set-region-preference",
            payload={**self._auth_payload(), "region-id": region_id},
            authenticated=True,
        )

    def get_schedules(self) -> dict[str, Any]:
        """GET /api/v1/collection-schedule -> schedule window dict."""
        return self._parse_schedules(
            self._request("GET", "collection-schedule", authenticated=True),
        )

    def list_regions(self) -> list[dict[str, Any]]:
        """List available districts, registering or re-registering if needed."""
        return self._run_authenticated(self.get_regions)

    def get_district_schedule(
        self,
        district: str | int,
        *,
        upcoming: bool = False,
        category: str | None = None,
        today: dt.date | None = None,
    ) -> DistrictSchedule:
        """Resolve a district, select it server-side, and return filtered schedules."""
        regions = self.list_regions()
        region = resolve_district(district, regions)
        self._run_authenticated(lambda: self.set_region(int(region["id"])))
        schedule_resp = self.get_schedules()
        schedules = filter_schedules(
            schedule_resp.get("data", []),
            upcoming=upcoming,
            category=category,
            today=today,
        )
        return DistrictSchedule(
            district=region,
            schedules=schedules,
            start_date=schedule_resp.get("start_date"),
            end_date=schedule_resp.get("end_date"),
        )


class AsyncEntsorgungClient(_BaseEntsorgungClient):
    """Asynchronous client for Cloudflare Python Workers and async runtimes.

    The upstream API stores the active district server-side per `device-token`.
    In concurrent environments (such as a Cloudflare Worker serving multiple
    districts simultaneously), construct a client with a distinct `ClientIdentity`
    per request or per district (e.g. `generate_identity()`) so concurrent requests
    do not overwrite each other's active district.
    """

    def __init__(
        self,
        identity: ClientIdentity,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: AsyncTransport | None = None,
    ) -> None:
        super().__init__(identity, base_url=base_url, timeout=timeout)
        self._transport: AsyncTransport = transport or FetchTransport()

    async def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        req = self._build_request(
            method,
            endpoint,
            payload,
            authenticated=authenticated,
        )
        resp = await self._transport.send(req)
        return self._parse_response(method, endpoint, resp)

    async def _run_authenticated(self, action: Callable[[], Awaitable[_T]]) -> _T:
        if self._needs_registration and not self._registered:
            await self.register_device()
        try:
            return await action()
        except ApiError as exc:
            if exc.status in _REREGISTER_STATUSES and not self._registered:
                await self.register_device()
                return await action()
            raise

    async def register_device(self) -> dict[str, Any]:
        """POST /api/v1/register-device."""
        resp = await self._request(
            "POST",
            "register-device",
            payload=self._auth_payload(),
            authenticated=False,
        )
        self._registered = True
        self._needs_registration = False
        return resp

    async def get_regions(self) -> list[dict[str, Any]]:
        """GET /api/v1/regions -> list of {"id": int, "name": str}."""
        return self._parse_regions(
            await self._request("GET", "regions", authenticated=True),
        )

    async def set_region(self, region_id: int) -> dict[str, Any]:
        """POST /api/v1/set-region-preference."""
        return await self._request(
            "POST",
            "set-region-preference",
            payload={**self._auth_payload(), "region-id": region_id},
            authenticated=True,
        )

    async def get_schedules(self) -> dict[str, Any]:
        """GET /api/v1/collection-schedule -> schedule window dict."""
        return self._parse_schedules(
            await self._request("GET", "collection-schedule", authenticated=True),
        )

    async def list_regions(self) -> list[dict[str, Any]]:
        """List available districts, registering or re-registering if needed."""
        return await self._run_authenticated(self.get_regions)

    async def get_district_schedule(
        self,
        district: str | int,
        *,
        upcoming: bool = False,
        category: str | None = None,
        today: dt.date | None = None,
    ) -> DistrictSchedule:
        """Resolve a district, select it server-side, and return filtered schedules."""
        regions = await self.list_regions()
        region = resolve_district(district, regions)
        region_id = int(region["id"])
        await self._run_authenticated(lambda: self.set_region(region_id))
        schedule_resp = await self.get_schedules()
        schedules = filter_schedules(
            schedule_resp.get("data", []),
            upcoming=upcoming,
            category=category,
            today=today,
        )
        return DistrictSchedule(
            district=region,
            schedules=schedules,
            start_date=schedule_resp.get("start_date"),
            end_date=schedule_resp.get("end_date"),
        )
