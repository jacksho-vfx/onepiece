"""Deadline REST API client implementation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import requests  # type: ignore[import-untyped]

from .deadline_errors import (
    DeadlineAuthenticationError,
    DeadlineResponseError,
    DeadlineUnavailableError,
    DeadlineValidationError,
)

REQUEST_TIMEOUT = 10.0


@dataclass
class DeadlineClient:
    """Minimal Deadline REST client used by the adapter."""

    base_url: str
    username: str | None = None
    password: str | None = None
    session_factory: Callable[[], requests.Session] = requests.Session

    def __post_init__(self) -> None:
        self._session: requests.Session | None = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self.session_factory()
        return self._session

    def submit_job(self, payload: Mapping[str, Any]) -> Any:
        """Submit a job payload to Deadline."""

        url = f"{self.base_url.rstrip('/')}/api/jobs"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.post(
                url, json=payload, timeout=REQUEST_TIMEOUT, auth=auth
            )
        except (
            requests.RequestException
        ) as exc:  # pragma: no cover - exercised via DeadlineUnavailableError
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(
                _response_message(response) or "Deadline authentication failed"
            )
        if response.status_code in {400, 422}:
            raise DeadlineValidationError(
                _response_message(response) or "Deadline rejected the job payload"
            )
        if response.status_code == 409:
            raise DeadlineValidationError(
                _response_message(response) or "Deadline refused to queue the job"
            )
        if response.status_code >= 500:
            raise DeadlineUnavailableError(
                _response_message(response) or "Deadline encountered an error"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc

        return data

    def get_job(self, job_id: str) -> Any:
        """Return metadata for the Deadline job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(
                _response_message(response) or "Deadline authentication failed"
            )
        if response.status_code == 404:
            raise DeadlineResponseError(
                _response_message(response) or "Deadline job not found"
            )
        if response.status_code >= 500:
            raise DeadlineUnavailableError(
                _response_message(response) or "Deadline encountered an error"
            )

        if not response.content:
            raise DeadlineResponseError("Deadline returned an empty response")

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc

    def delete_job(self, job_id: str) -> Any:
        """Request cancellation of the Deadline job identified by ``job_id``."""

        url = f"{self.base_url.rstrip('/')}/api/jobs/{job_id}"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.delete(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(
                _response_message(response) or "Deadline authentication failed"
            )
        if response.status_code == 404:
            raise DeadlineResponseError(
                _response_message(response) or "Deadline job not found"
            )
        if response.status_code == 409:
            raise DeadlineValidationError(
                _response_message(response)
                or "Deadline refused to cancel the requested job"
            )
        if response.status_code >= 500:
            raise DeadlineUnavailableError(
                _response_message(response) or "Deadline encountered an error"
            )

        if not response.content:
            return {"status": "cancelled", "message": "Job cancelled"}

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc

    def get_limits(self) -> Any:
        """Return adapter limits advertised by Deadline."""

        url = f"{self.base_url.rstrip('/')}/api/capabilities"
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, auth=auth)
        except (
            requests.RequestException
        ) as exc:  # pragma: no cover - handled by DeadlineUnavailableError
            raise DeadlineUnavailableError("Unable to reach Deadline API") from exc

        if response.status_code >= 500:
            raise DeadlineUnavailableError(
                _response_message(response) or "Deadline capabilities unavailable"
            )
        if response.status_code in {401, 403}:
            raise DeadlineAuthenticationError(
                _response_message(response) or "Deadline authentication failed"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise DeadlineResponseError("Deadline returned invalid JSON") from exc


def _response_message(response: requests.Response) -> str | None:
    """Extract a helpful error message from a Deadline HTTP response."""

    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.text or None

    if isinstance(data, Mapping):
        message = data.get("message") or data.get("Message")
        if isinstance(message, str):
            return message
    return response.text or None


__all__ = ["DeadlineClient", "REQUEST_TIMEOUT"]
