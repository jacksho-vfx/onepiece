from __future__ import annotations

import json
from typing import Any, AsyncIterator, Mapping

import httpx
from fastapi import HTTPException, Request

from apps.trafalgar.transport import (
    DEFAULT_PIPELINE_API_TIMEOUT,
    resolve_pipeline_api_timeout,
    resolve_pipeline_api_url,
)

_PIPELINE_AUTH_HEADERS = {
    "authorization": "Authorization",
    "x-api-key": "X-API-Key",
    "x-api-secret": "X-API-Secret",
}


class PipelineApiError(RuntimeError):
    """Raised when interactions with the Trafalgar pipeline API fail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PipelineApiClient:
    """Minimal HTTP client for the Trafalgar pipeline API."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str],
        timeout: float = DEFAULT_PIPELINE_API_TIMEOUT,
    ) -> None:
        stripped = base_url.rstrip("/") or "/pipeline"
        self._client = httpx.AsyncClient(
            base_url=stripped + "/",
            headers=dict(headers),
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_pipelines(self) -> Any:
        response = await self._request("GET", "pipelines")
        return response.json()

    async def trigger_run(
        self, pipeline: str, *, parameters: Mapping[str, Any] | None = None
    ) -> Any:
        response = await self._request(
            "POST",
            f"pipelines/{pipeline}/runs",
            json={"parameters": dict(parameters or {})},
        )
        return response.json()

    async def get_run(self, run_id: str) -> Any:
        response = await self._request("GET", f"runs/{run_id}")
        return response.json()

    async def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        try:
            async with self._client.stream("GET", f"runs/{run_id}/events") as response:
                await self._raise_for_status(response)
                events: list[dict[str, Any]] = []
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if not payload:
                        continue
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        continue
                return events
        except httpx.HTTPStatusError as exc:  # pragma: no cover - defensive
            raise self._convert_status_error(exc) from exc
        except httpx.RequestError as exc:
            raise PipelineApiError(503, "Unable to reach pipeline API") from exc

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise PipelineApiError(503, "Unable to reach pipeline API") from exc
        await self._raise_for_status(response)
        return response

    async def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._convert_status_error(exc) from exc

    def _convert_status_error(self, exc: httpx.HTTPStatusError) -> PipelineApiError:
        status_code = exc.response.status_code
        detail = self._extract_detail(exc.response)
        return PipelineApiError(status_code, detail)

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or f"Pipeline API request failed ({response.status_code})."
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, str) and detail:
            return detail
        text = response.text.strip()
        return text or f"Pipeline API request failed ({response.status_code})."


def _extract_pipeline_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header, canonical in _PIPELINE_AUTH_HEADERS.items():
        value = request.headers.get(header)
        if value:
            headers[canonical] = value
    return headers


async def get_pipeline_client(request: Request) -> AsyncIterator[PipelineApiClient]:
    headers = _extract_pipeline_headers(request)
    if not headers:
        raise HTTPException(
            status_code=401,
            detail="Pipeline credentials are required to call this endpoint.",
        )
    client = PipelineApiClient(
        resolve_pipeline_api_url(),
        headers=headers,
        timeout=resolve_pipeline_api_timeout(),
    )
    try:
        yield client
    finally:
        await client.aclose()


__all__ = ["PipelineApiClient", "PipelineApiError", "get_pipeline_client"]
