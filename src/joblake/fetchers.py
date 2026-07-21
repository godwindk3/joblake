import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.sync_api import sync_playwright

from joblake.models import (
    FetchError,
    FetchResult,
    SourceBlockedError,
)


@dataclass(frozen=True, slots=True)
class ProxySettings:
    server: str
    username: str | None = None
    password: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _is_cloudflare_challenge(
    status_code: int | None,
    html: str,
) -> bool:
    html_preview = html[:200_000].lower()

    return (
        status_code == 403
        and (
            "<title>just a moment" in html_preview
            or "challenges.cloudflare.com" in html_preview
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


class RequestsFetcher:

    def __init__(self, config: dict):
        self.timeout_seconds = config["timeout_seconds"]
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
    ) -> FetchResult:
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise FetchError(str(exc)) from exc

        html = response.text

        if _is_cloudflare_challenge(
            response.status_code,
            html,
        ):
            raise SourceBlockedError(
                "Cloudflare challenge detected"
            )

        if response.status_code >= 400:
            raise FetchError(
                f"HTTP status {response.status_code}: "
                f"{response.url}"
            )

        return FetchResult(
            requested_url=url,
            final_url=response.url,
            status_code=response.status_code,
            content_type=response.headers.get(
                "content-type"
            ),
            fetched_at=_utc_now(),
            html=html,
        )

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PlaywrightFetcher:

    def __init__(self, config: dict):
        self.timeout_ms = (
            config["timeout_seconds"] * 1_000
        )

        self.playwright = sync_playwright().start()

        launch_options = {
            "headless": config.get("headless", True),
        }

        proxy = _load_proxy(config)

        if proxy:
            proxy_options = {
                "server": proxy.server,
            }

            if proxy.username:
                proxy_options["username"] = proxy.username

            if proxy.password:
                proxy_options["password"] = proxy.password

            launch_options["proxy"] = proxy_options

        self.browser = self.playwright.chromium.launch(
            **launch_options
        )

        context_options = {}

        if config.get("user_agent"):
            context_options["user_agent"] = config["user_agent"]

        if config.get("locale"):
            context_options["locale"] = config["locale"]

        self.context = self.browser.new_context(
            **context_options
        )

        self.page = self.context.new_page()

    def fetch(
        self,
        url: str,
        params: dict | None = None,
    ) -> FetchResult:
        final_request_url = _build_url(
            url=url,
            params=params,
        )

        try:
            response = self.page.goto(
                final_request_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise FetchError(
                f"Timeout: {final_request_url}"
            ) from exc

        html = self.page.content()

        status_code = (
            response.status
            if response is not None
            else None
        )

        if _is_cloudflare_challenge(
            status_code,
            html,
        ):
            raise SourceBlockedError(
                "Cloudflare challenge detected"
            )

        if status_code is not None and status_code >= 400:
            raise FetchError(
                f"HTTP status {status_code}: "
                f"{self.page.url}"
            )

        content_type = None

        if response is not None:
            content_type = response.headers.get(
                "content-type"
            )

        return FetchResult(
            requested_url=final_request_url,
            final_url=self.page.url,
            status_code=status_code,
            content_type=content_type,
            fetched_at=_utc_now(),
            html=html,
        )

    def close(self) -> None:
        self.context.close()
        self.browser.close()
        self.playwright.stop()

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

class CloakBrowserFetcher:

    def __init__(self, config: dict):
        self.timeout_ms = (
            config["timeout_seconds"] * 1_000
        )

        launch_options = {
            "headless": config.get("headless", True),
        }

        proxy = _load_proxy(config)

        if proxy:
            proxy_options = {
                "server": proxy.server,
            }

            if proxy.username:
                proxy_options["username"] = proxy.username

            if proxy.password:
                proxy_options["password"] = proxy.password

            launch_options["proxy"] = proxy_options

        if config.get("geoip") is not None:
            launch_options["geoip"] = config["geoip"]

        if config.get("humanize") is not None:
            launch_options["humanize"] = config["humanize"]

        if config.get("browser_args"):
            launch_options["args"] = config["browser_args"]

        self.browser = launch(**launch_options)

        context_options = {}

        if config.get("user_agent"):
            context_options["user_agent"] = config["user_agent"]

        if config.get("locale"):
            context_options["locale"] = config["locale"]

        if config.get("timezone_id"):
            context_options["timezone_id"] = (
                config["timezone_id"]
            )

        self.context = self.browser.new_context(
            **context_options
        )

        self.page = self.context.new_page()

    def fetch(
        self,
        url: str,
        params: dict | None = None,
    ) -> FetchResult:
        final_request_url = _build_url(
            url=url,
            params=params,
        )

        try:
            response = self.page.goto(
                final_request_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise FetchError(
                f"Timeout: {final_request_url}"
            ) from exc

        html = self.page.content()

        status_code = (
            response.status
            if response is not None
            else None
        )

        if _is_cloudflare_challenge(
            status_code,
            html,
        ):
            raise SourceBlockedError(
                "Cloudflare challenge detected"
            )

        if status_code is not None and status_code >= 400:
            raise FetchError(
                f"HTTP status {status_code}: "
                f"{self.page.url}"
            )

        content_type = None

        if response is not None:
            content_type = response.headers.get(
                "content-type"
            )

        return FetchResult(
            requested_url=final_request_url,
            final_url=self.page.url,
            status_code=status_code,
            content_type=content_type,
            fetched_at=_utc_now(),
            html=html,
        )

    def close(self) -> None:
        self.context.close()
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()