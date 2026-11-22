"""Respectful HTTP client with robots.txt enforcement and bounded retries.

No authentication is invented or bypassed. Public resources are fetched
without credentials; sources requiring access credentials must be configured
explicitly by their own service integration.
"""
from __future__ import annotations

import email.utils
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx


class RobotsDenied(PermissionError):
    """The target URL is disallowed by the origin's robots.txt."""


class RobotsAwareHTTP:
    def __init__(
        self,
        user_agent: str,
        *,
        contact: str | None = None,
        timeout: float = 30.0,
        min_delay: float = 1.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
    ):
        if not user_agent or any(ch in user_agent for ch in ("\\r", "\\n")):
            raise ValueError("A descriptive, single-line User-Agent is required")
        if timeout <= 0 or min_delay < 0 or not 0 <= max_retries <= 5:
            raise ValueError("Invalid HTTP timeout, delay, or retry count")
        suffix = f" (contact: {contact})" if contact else ""
        self.user_agent = user_agent + suffix
        self.timeout = timeout
        self.min_delay = min_delay
        self.max_retries = max_retries
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
        )
        self._robots: dict[str, RobotFileParser | bool] = {}
        self._last_request: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def _origin(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Only HTTPS source URLs are permitted")
        return f"https://{parsed.netloc}"

    def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        if origin not in self._robots:
            parser = RobotFileParser()
            parser.set_url(origin + "/robots.txt")
            try:
                response = self._client.get(origin + "/robots.txt", headers={"User-Agent": self.user_agent})
                if response.status_code == 404:
                    self._robots[origin] = True
                elif 400 <= response.status_code < 500:
                    # Authentication/authorization and throttling are not
                    # treated as permission to crawl.
                    self._robots[origin] = False
                elif response.status_code >= 500:
                    self._robots[origin] = False
                elif response.is_success:
                    parser.parse(response.text.splitlines())
                    self._robots[origin] = parser
                else:
                    self._robots[origin] = False
            except httpx.HTTPError:
                # Fail closed when robots policy cannot be established.
                self._robots[origin] = False
        policy = self._robots[origin]
        return policy is True or (
            isinstance(policy, RobotFileParser)
            and policy.can_fetch(self.user_agent, url)
        )

    def _throttle(self, origin: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(origin, 0.0)
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last_request[origin] = time.monotonic()

    @staticmethod
    def _retry_delay(value: str | None, attempt: int) -> float:
        if value:
            try:
                return min(60.0, max(0.0, float(value)))
            except ValueError:
                try:
                    dt = email.utils.parsedate_to_datetime(value)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return min(60.0, max(0.0, (dt - datetime.now(timezone.utc)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(30.0, 2.0 ** attempt)

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        current = url
        redirects = 0
        for attempt in range(self.max_retries + 1):
            origin = self._origin(current)
            if not self.allowed(current):
                raise RobotsDenied(f"robots.txt disallows or cannot authorize: {current}")
            self._throttle(origin)
            try:
                response = self._client.get(
                    current, params=params if current == url else None,
                    headers={"User-Agent": self.user_agent},
                )
            except httpx.HTTPError:
                if attempt >= self.max_retries:
                    raise
                time.sleep(self._retry_delay(None, attempt))
                continue
            if response.is_redirect:
                if redirects >= 5:
                    raise RuntimeError("Too many source redirects")
                target = urljoin(current, response.headers.get("location", ""))
                self._origin(target)
                current = target
                redirects += 1
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.max_retries:
                    response.raise_for_status()
                time.sleep(self._retry_delay(response.headers.get("retry-after"), attempt))
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("Source request retry budget exhausted")

    def download(
        self, url: str, destination: Path, *, max_bytes: int = 25_000_000
    ) -> int:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        current = url
        redirects = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        try:
            for attempt in range(self.max_retries + 1):
                origin = self._origin(current)
                if not self.allowed(current):
                    raise RobotsDenied(f"robots.txt disallows or cannot authorize: {current}")
                self._throttle(origin)
                try:
                    with self._client.stream(
                        "GET", current, headers={"User-Agent": self.user_agent}
                    ) as response:
                        if response.is_redirect:
                            if redirects >= 5:
                                raise RuntimeError("Too many source redirects")
                            target = urljoin(current, response.headers.get("location", ""))
                            self._origin(target)
                            current = target
                            redirects += 1
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt >= self.max_retries:
                                response.raise_for_status()
                            time.sleep(self._retry_delay(response.headers.get("retry-after"), attempt))
                            continue
                        response.raise_for_status()
                        length = response.headers.get("content-length")
                        if length and int(length) > max_bytes:
                            raise ValueError(f"Download exceeds configured limit ({max_bytes} bytes)")
                        total = 0
                        with temporary.open("wb") as output:
                            for chunk in response.iter_bytes():
                                total += len(chunk)
                                if total > max_bytes:
                                    raise ValueError(
                                        f"Download exceeds configured limit ({max_bytes} bytes)"
                                    )
                                output.write(chunk)
                        if total == 0:
                            raise ValueError("Source returned an empty document")
                        temporary.replace(destination)
                        return total
                except httpx.HTTPError:
                    if attempt >= self.max_retries:
                        raise
                    time.sleep(self._retry_delay(None, attempt))
            raise RuntimeError("Source download retry budget exhausted")
        finally:
            temporary.unlink(missing_ok=True)

    def get_text(self, url: str, *, max_bytes: int = 50_000_000) -> str:
        response = self.get(url)
        if len(response.content) > max_bytes:
            raise ValueError("Source response exceeds configured size limit")
        return response.text
