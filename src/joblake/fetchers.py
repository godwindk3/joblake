import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urlsplit,
    urlunsplit,
)

import requests
from cloakbrowser import launch
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.sync_api import sync_playwright

from joblake.block_detection import (
    detect_block_reason as _detect_block_reason,
)
from joblake.browser_actions import (
    run_browser_actions as _run_browser_actions,
)
from joblake.models import (
    FetchError,
    FetchResult,
    SourceBlockedError,
)


LOGGER = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}


@dataclass(frozen=True, slots=True)
class ProxySettings:
    server: str
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True, slots=True)
class RetrySettings:
    max_attempts: int = 1
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 60.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_retry_settings(config: dict) -> RetrySettings:
    retry_config = config.get("retry", {})

    settings = RetrySettings(
        max_attempts=int(
            retry_config.get("max_attempts", 1)
        ),
        base_delay_seconds=float(
            retry_config.get("base_delay_seconds", 5)
        ),
        max_delay_seconds=float(
            retry_config.get("max_delay_seconds", 60)
        ),
    )

    if settings.max_attempts < 1:
        raise ValueError(
            "retry.max_attempts must be at least 1"
        )

    if settings.base_delay_seconds < 0:
        raise ValueError(
            "retry.base_delay_seconds cannot be negative"
        )

    if (
        settings.max_delay_seconds
        < settings.base_delay_seconds
    ):
        raise ValueError(
            "retry.max_delay_seconds must be greater "
            "than or equal to retry.base_delay_seconds"
        )

    return settings


def _load_proxy(config: dict) -> ProxySettings | None:
    proxy_config = config.get("proxy", {})

    if not proxy_config.get("enabled", False):
        return None

    server_env = proxy_config.get("server_env")
    username_env = proxy_config.get("username_env")
    password_env = proxy_config.get("password_env")

    server = os.getenv(server_env) if server_env else None
    username = os.getenv(username_env) if username_env else None
    password = os.getenv(password_env) if password_env else None

    if not server:
        raise ValueError(
            "Proxy is enabled but proxy server is missing"
        )

    return ProxySettings(
        server=server,
        username=username,
        password=password,
    )


def _build_url(
    url: str,
    params: dict | None,
) -> str:
    if not params:
        return url

    parts = urlsplit(url)

    query_items = list(
        parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
    )

    query_items.extend(params.items())

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_items, doseq=True),
            parts.fragment,
        )
    )


def _build_requests_proxy_url(
    proxy: ProxySettings,
) -> str:
    if not proxy.username:
        return proxy.server

    parsed = urlsplit(proxy.server)

    username = quote(proxy.username, safe="")
    password = quote(proxy.password or "", safe="")

    hostname = parsed.hostname or ""

    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"

    netloc = f"{username}:{password}@{hostname}"

    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _build_browser_proxy(
    proxy: ProxySettings,
) -> dict:
    proxy_options = {
        "server": proxy.server,
    }

    if proxy.username:
        proxy_options["username"] = proxy.username

    if proxy.password:
        proxy_options["password"] = proxy.password

    return proxy_options


def _build_context_options(
    config: dict,
    *,
    include_location: bool = True,
) -> dict:
    context_options = {}

    if config.get("user_agent"):
        context_options["user_agent"] = (
            config["user_agent"]
        )

    if include_location and config.get("locale"):
        context_options["locale"] = config["locale"]

    if (
        include_location
        and config.get("timezone_id")
    ):
        context_options["timezone_id"] = (
            config["timezone_id"]
        )

    if config.get("viewport") is not None:
        context_options["viewport"] = config["viewport"]

    storage_state_path = config.get(
        "storage_state_path"
    )

    if (
        storage_state_path
        and Path(storage_state_path).is_file()
    ):
        context_options["storage_state"] = (
            storage_state_path
        )

    return context_options


def _persist_storage_state(
    context,
    storage_state_path: str | None,
) -> None:
    if not storage_state_path:
        return

    state_path = Path(storage_state_path)
    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    context.storage_state(path=str(state_path))


def _retry_after_seconds(headers) -> float | None:
    if not headers:
        return None

    raw_value = headers.get("retry-after")

    if raw_value is None:
        raw_value = headers.get("Retry-After")

    if raw_value is None:
        return None

    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(
                raw_value
            )

            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(
                    tzinfo=timezone.utc
                )

            return max(
                0.0,
                (
                    retry_at
                    - datetime.now(timezone.utc)
                ).total_seconds(),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def _sleep_before_retry(
    *,
    attempt: int,
    settings: RetrySettings,
    url: str,
    reason: str,
    retry_after_seconds: float | None = None,
) -> None:
    if retry_after_seconds is not None:
        delay = retry_after_seconds

        if delay > settings.max_delay_seconds:
            raise SourceBlockedError(
                f"{reason}: server requested a "
                f"{delay:.0f}s cooldown for {url}"
            )
    else:
        delay = min(
            settings.max_delay_seconds,
            settings.base_delay_seconds
            * (2 ** (attempt - 1)),
        )

        delay *= random.uniform(0.8, 1.2)

    LOGGER.warning(
        "Fetch attempt %s/%s failed (%s); "
        "retrying %s after %.1fs",
        attempt,
        settings.max_attempts,
        reason,
        url,
        delay,
    )

    time.sleep(delay)


def _should_retry(
    attempt: int,
    settings: RetrySettings,
) -> bool:
    return attempt < settings.max_attempts


def _settle_page(page, config: dict) -> None:
    ready_selector = config.get("ready_selector")

    if ready_selector:
        ready_state = config.get(
            "ready_state",
            "attached",
        )

        if ready_state not in {
            "attached",
            "detached",
            "visible",
            "hidden",
        }:
            raise ValueError(
                "ready_state must be attached, detached, "
                "visible, or hidden"
            )

        ready_timeout_ms = int(
            config.get(
                "ready_timeout_seconds",
                config["timeout_seconds"],
            )
            * 1_000
        )

        page.wait_for_selector(
            ready_selector,
            state=ready_state,
            timeout=ready_timeout_ms,
        )

    settle_config = config.get("settle_seconds", {})

    if settle_config:
        min_seconds = float(
            settle_config.get("min", 0)
        )
        max_seconds = float(
            settle_config.get("max", min_seconds)
        )

        if min_seconds < 0 or max_seconds < min_seconds:
            raise ValueError(
                "settle_seconds must define "
                "0 <= min <= max"
            )

        time.sleep(
            random.uniform(min_seconds, max_seconds)
        )


def _fetch_browser_page(
    *,
    page,
    url: str,
    params: dict | None,
    referer: str | None,
    config: dict,
    retry_settings: RetrySettings,
    recover_page=None,
) -> FetchResult:
    final_request_url = _build_url(
        url=url,
        params=params,
    )
    timeout_ms = config["timeout_seconds"] * 1_000

    for attempt in range(
        1,
        retry_settings.max_attempts + 1,
    ):
        try:
            goto_options = {
                "wait_until": "domcontentloaded",
                "timeout": timeout_ms,
            }

            if referer:
                goto_options["referer"] = referer

            response = page.goto(
                final_request_url,
                **goto_options,
            )

            html = page.content()
            status_code = (
                response.status
                if response is not None
                else None
            )
            response_headers = (
                response.headers
                if response is not None
                else {}
            )

            if status_code == 429:
                if _should_retry(
                    attempt,
                    retry_settings,
                ):
                    _sleep_before_retry(
                        attempt=attempt,
                        settings=retry_settings,
                        url=final_request_url,
                        reason="HTTP 429 rate limited",
                        retry_after_seconds=(
                            _retry_after_seconds(
                                response_headers
                            )
                        ),
                    )
                    continue

                raise SourceBlockedError(
                    "HTTP 429 rate limited: "
                    f"{page.url}"
                )

            block_reason = _detect_block_reason(
                status_code,
                html,
            )

            if block_reason:
                raise SourceBlockedError(
                    f"{block_reason}: {page.url}"
                )

            if status_code in RETRYABLE_STATUS_CODES:
                if _should_retry(
                    attempt,
                    retry_settings,
                ):
                    _sleep_before_retry(
                        attempt=attempt,
                        settings=retry_settings,
                        url=final_request_url,
                        reason=f"HTTP {status_code}",
                        retry_after_seconds=(
                            _retry_after_seconds(
                                response_headers
                            )
                        ),
                    )
                    continue

                raise FetchError(
                    f"HTTP status {status_code}: "
                    f"{page.url}"
                )

            if (
                status_code is not None
                and status_code >= 400
            ):
                raise FetchError(
                    f"HTTP status {status_code}: "
                    f"{page.url}"
                )

            _settle_page(page, config)
            _run_browser_actions(page, config)

            html = page.content()
            block_reason = _detect_block_reason(
                status_code,
                html,
            )

            if block_reason:
                raise SourceBlockedError(
                    f"{block_reason}: {page.url}"
                )

            content_type = (
                response_headers.get("content-type")
                if response is not None
                else None
            )

            return FetchResult(
                requested_url=final_request_url,
                final_url=page.url,
                status_code=status_code,
                content_type=content_type,
                fetched_at=_utc_now(),
                html=html,
            )

        except PlaywrightTimeoutError as exc:
            if _should_retry(
                attempt,
                retry_settings,
            ):
                _sleep_before_retry(
                    attempt=attempt,
                    settings=retry_settings,
                    url=final_request_url,
                    reason="browser timeout",
                )
                continue

            raise FetchError(
                f"Timeout after "
                f"{retry_settings.max_attempts} "
                f"attempt(s): {final_request_url}"
            ) from exc

        except PlaywrightError as exc:
            if _should_retry(
                attempt,
                retry_settings,
            ):
                if (
                    recover_page is not None
                    and _browser_page_is_unusable(
                        page,
                        exc,
                    )
                ):
                    try:
                        page = recover_page()
                    except Exception as recovery_exc:
                        raise FetchError(
                            "Unable to recover browser after "
                            f"error for {final_request_url}: "
                            f"{recovery_exc}"
                        ) from recovery_exc

                _sleep_before_retry(
                    attempt=attempt,
                    settings=retry_settings,
                    url=final_request_url,
                    reason="browser navigation error",
                )
                continue

            raise FetchError(
                f"Browser error after "
                f"{retry_settings.max_attempts} "
                f"attempt(s): {final_request_url}: "
                f"{exc}"
            ) from exc

    raise FetchError(
        f"Unable to fetch: {final_request_url}"
    )


def _browser_page_is_unusable(
    page,
    error: Exception,
) -> bool:
    try:
        if page.is_closed():
            return True
    except Exception:
        return True

    message = str(error).lower()

    return any(
        marker in message
        for marker in (
            "target closed",
            "target page, context or browser has been closed",
            "browser has been closed",
            "context has been closed",
        )
    )


class RequestsFetcher:

    def __init__(self, config: dict):
        self.timeout_seconds = config["timeout_seconds"]
        self.retry_settings = _load_retry_settings(
            config
        )
        self.session = requests.Session()

        user_agent = config.get("user_agent")

        if user_agent:
            self.session.headers.update({
                "User-Agent": user_agent,
            })

        proxy = _load_proxy(config)

        if proxy:
            proxy_url = _build_requests_proxy_url(proxy)

            self.session.proxies.update({
                "http": proxy_url,
                "https": proxy_url,
            })

    def fetch(
        self,
        url: str,
        params: dict | None = None,
        referer: str | None = None,
    ) -> FetchResult:
        for attempt in range(
            1,
            self.retry_settings.max_attempts + 1,
        ):
            try:
                headers = (
                    {"Referer": referer}
                    if referer
                    else None
                )
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except (
                requests.ConnectionError,
                requests.Timeout,
            ) as exc:
                if _should_retry(
                    attempt,
                    self.retry_settings,
                ):
                    _sleep_before_retry(
                        attempt=attempt,
                        settings=self.retry_settings,
                        url=url,
                        reason=type(exc).__name__,
                    )
                    continue

                raise FetchError(str(exc)) from exc
            except requests.RequestException as exc:
                raise FetchError(str(exc)) from exc

            html = response.text

            if response.status_code == 429:
                if _should_retry(
                    attempt,
                    self.retry_settings,
                ):
                    _sleep_before_retry(
                        attempt=attempt,
                        settings=self.retry_settings,
                        url=response.url,
                        reason="HTTP 429 rate limited",
                        retry_after_seconds=(
                            _retry_after_seconds(
                                response.headers
                            )
                        ),
                    )
                    continue

                raise SourceBlockedError(
                    "HTTP 429 rate limited: "
                    f"{response.url}"
                )

            block_reason = _detect_block_reason(
                response.status_code,
                html,
            )

            if block_reason:
                raise SourceBlockedError(
                    f"{block_reason}: {response.url}"
                )

            if (
                response.status_code
                in RETRYABLE_STATUS_CODES
            ):
                if _should_retry(
                    attempt,
                    self.retry_settings,
                ):
                    _sleep_before_retry(
                        attempt=attempt,
                        settings=self.retry_settings,
                        url=response.url,
                        reason=(
                            f"HTTP {response.status_code}"
                        ),
                        retry_after_seconds=(
                            _retry_after_seconds(
                                response.headers
                            )
                        ),
                    )
                    continue

            if response.status_code >= 400:
                raise FetchError(
                    f"HTTP status "
                    f"{response.status_code}: "
                    f"{response.url}"
                )

            return FetchResult(
                requested_url=(
                    response.request.url or url
                ),
                final_url=response.url,
                status_code=response.status_code,
                content_type=response.headers.get(
                    "content-type"
                ),
                fetched_at=_utc_now(),
                html=html,
            )

        raise FetchError(f"Unable to fetch: {url}")

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PlaywrightFetcher:

    def __init__(self, config: dict):
        self.config = config
        self.retry_settings = _load_retry_settings(
            config
        )
        self.storage_state_path = config.get(
            "storage_state_path"
        )
        self.blocked = False
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.launch_options = {
            "headless": config.get("headless", True),
        }

        proxy = _load_proxy(config)

        if proxy:
            self.launch_options["proxy"] = (
                _build_browser_proxy(proxy)
            )

        self._start_browser()

    def _start_browser(self) -> None:
        self.playwright = sync_playwright().start()

        try:
            self.browser = (
                self.playwright.chromium.launch(
                    **self.launch_options
                )
            )
            self.context = self.browser.new_context(
                **_build_context_options(self.config)
            )
            self.page = self.context.new_page()
        except Exception:
            self._shutdown(persist_state=False)
            raise

    def _shutdown(self, *, persist_state: bool) -> None:
        if persist_state and self.context is not None:
            try:
                _persist_storage_state(
                    self.context,
                    self.storage_state_path,
                )
            except Exception as exc:
                LOGGER.warning(
                    "Unable to persist browser state: %s",
                    exc,
                )

        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass

        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass

        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception:
                pass

        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

    def _recover_page(self):
        LOGGER.warning(
            "Browser page is unusable; restarting "
            "Playwright context"
        )
        self._shutdown(persist_state=False)
        self._start_browser()
        return self.page

    def fetch(
        self,
        url: str,
        params: dict | None = None,
        referer: str | None = None,
    ) -> FetchResult:
        try:
            return _fetch_browser_page(
                page=self.page,
                url=url,
                params=params,
                referer=referer,
                config=self.config,
                retry_settings=self.retry_settings,
                recover_page=self._recover_page,
            )
        except SourceBlockedError:
            self.blocked = True
            raise

    def close(self) -> None:
        self._shutdown(
            persist_state=not self.blocked
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class CloakBrowserFetcher:

    def __init__(self, config: dict):
        self.config = config
        self.retry_settings = _load_retry_settings(
            config
        )
        self.storage_state_path = config.get(
            "storage_state_path"
        )
        self.blocked = False
        self.browser = None
        self.context = None
        self.page = None

        self.launch_options = {
            "headless": config.get("headless", True),
        }

        proxy = _load_proxy(config)

        if proxy:
            self.launch_options["proxy"] = (
                _build_browser_proxy(proxy)
            )

        if config.get("geoip") is not None:
            self.launch_options["geoip"] = (
                config["geoip"]
            )

        if not config.get("geoip", False):
            if config.get("locale"):
                self.launch_options["locale"] = (
                    config["locale"]
                )

            if config.get("timezone_id"):
                self.launch_options["timezone"] = (
                    config["timezone_id"]
                )

        if config.get("humanize") is not None:
            self.launch_options["humanize"] = (
                config["humanize"]
            )

        if config.get("browser_args"):
            self.launch_options["args"] = (
                config["browser_args"]
            )

        self._start_browser()

    def _start_browser(self) -> None:
        try:
            self.browser = launch(
                **self.launch_options
            )
            self.context = self.browser.new_context(
                **_build_context_options(
                    self.config,
                    include_location=False,
                )
            )
            self.page = self.context.new_page()
        except Exception:
            self._shutdown(persist_state=False)
            raise

    def _shutdown(self, *, persist_state: bool) -> None:
        if persist_state and self.context is not None:
            try:
                _persist_storage_state(
                    self.context,
                    self.storage_state_path,
                )
            except Exception as exc:
                LOGGER.warning(
                    "Unable to persist browser state: %s",
                    exc,
                )

        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass

        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass

        self.page = None
        self.context = None
        self.browser = None

    def _recover_page(self):
        LOGGER.warning(
            "Browser page is unusable; restarting "
            "CloakBrowser context"
        )
        self._shutdown(persist_state=False)
        self._start_browser()
        return self.page

    def fetch(
        self,
        url: str,
        params: dict | None = None,
        referer: str | None = None,
    ) -> FetchResult:
        try:
            return _fetch_browser_page(
                page=self.page,
                url=url,
                params=params,
                referer=referer,
                config=self.config,
                retry_settings=self.retry_settings,
                recover_page=self._recover_page,
            )
        except SourceBlockedError:
            self.blocked = True
            raise

    def close(self) -> None:
        self._shutdown(
            persist_state=not self.blocked
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def create_fetcher(config: dict):
    transport = config["transport"]

    if transport == "requests":
        return RequestsFetcher(config)

    if transport == "playwright":
        return PlaywrightFetcher(config)

    if transport == "cloakbrowser":
        return CloakBrowserFetcher(config)

    raise ValueError(
        f"Unsupported transport: {transport}"
    )
