"""Bounded, opt-in evidence collection for browser timeouts."""

import json
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


LOGGER = logging.getLogger(__name__)


def _redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if re.search(
            r"token|password|secret|cookie|authorization|email|phone", key, re.I
        ) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _safe_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


class BrowserDiagnostics:
    @classmethod
    def from_config(cls, page, config):
        return cls(
            page, config.get("diagnostics_dir"),
            enabled=config.get("diagnostics_enabled", True),
            capture_success=config.get("diagnostics_capture_success", False),
            retention_days=config.get("diagnostics_retention_days", 7),
            max_captures=config.get("diagnostics_max_captures", 100),
        )

    def __init__(self, page, directory, *, enabled=True, capture_success=False,
                 retention_days=7, max_captures=100):
        if isinstance(retention_days, bool) or not isinstance(retention_days, (int, float)) or not 0 < retention_days <= 3650:
            raise ValueError("diagnostics_retention_days must be between 0 and 3650 (exclusive of 0)")
        if isinstance(max_captures, bool) or not isinstance(max_captures, int) or max_captures < 1:
            raise ValueError("diagnostics_max_captures must be a positive integer")
        self.page = page
        self.directory = directory if enabled else None
        self.capture_success = capture_success
        self.retention_days = retention_days
        self.max_captures = max_captures
        self.events = deque(maxlen=50)
        self.console_events = deque(maxlen=50)
        self.listeners = []
        self.started = time.perf_counter()
        self.requests = {}
        self.completed = deque(maxlen=30)
        self.dropped_requests = 0
        if self.directory:
            self._cleanup()
            for event, callback in (
                ("request", self._request),
                ("requestfinished", self._finished),
                ("requestfailed", self._failed),
                ("response", self._response),
                ("pageerror", self._pageerror),
                ("console", self._console),
            ):
                page.on(event, callback)
                self.listeners.append((event, callback))

    def _cleanup(self, reserve=0):
        """Remove only our flat evidence folders, never recurse into user data."""
        root = Path(self.directory).resolve()
        if not root.is_dir():
            return
        removed = 0
        try:
            captures = []
            for folder in root.iterdir():
                if (re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{12}", folder.name)
                        and not folder.is_symlink() and folder.is_dir()
                        and folder.resolve().parent == root):
                    captures.append(folder)
            captures.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            cutoff = time.time() - self.retention_days * 86400
            for index, folder in enumerate(captures):
                if index < self.max_captures - reserve and folder.stat().st_mtime >= cutoff:
                    continue
                children = list(folder.iterdir())
                if any(p.name not in {"page.html", "page.png", "diagnostics.json"}
                       or p.is_symlink() or not p.is_file()
                       or p.resolve().parent != folder.resolve() for p in children):
                    continue
                for child in children:
                    child.unlink()
                folder.rmdir()
                removed += 1
            baseline = root / "latest_success.json"
            if baseline.is_file() and not baseline.is_symlink():
                previous = json.loads(baseline.read_text(encoding="utf-8"))
                if baseline.stat().st_mtime < cutoff or not Path(previous.get("file", "")).is_file():
                    baseline.unlink()
        except (OSError, ValueError, TypeError):
            LOGGER.warning("Unable to prune browser diagnostics in %s", root, exc_info=True)
        if removed:
            LOGGER.info("Pruned %s expired/excess browser evidence folders in %s", removed, root)

    def _request(self, request):
        if request.resource_type not in {"xhr", "fetch", "document", "script"}:
            return
        if len(self.requests) >= 300:
            self.dropped_requests += 1
            return
        self.requests[request] = {
            "url": _safe_url(request.url), "method": request.method,
            "resource_type": request.resource_type, "state": "pending_response",
            "started_ms": round((time.perf_counter() - self.started) * 1000),
        }

    def _finished(self, request):
        record = self.requests.get(request)
        if record is None:
            return
        record["state"] = "finished"
        record["finished_ms"] = round((time.perf_counter() - self.started) * 1000)
        if request.resource_type in {"xhr", "fetch"}:
            self.completed.append((request, record))

    def _failed(self, request):
        if request in self.requests:
            self.requests[request].update(state="failed", failure=request.failure)
        self.events.append({"event": "requestfailed", "url": _safe_url(request.url),
                            "resource_type": request.resource_type,
                            "failure": request.failure})

    def _response(self, response):
        record = self.requests.get(response.request)
        if record is not None:
            record.update(status=response.status, state="pending_body",
                          response_ms=round((time.perf_counter() - self.started) * 1000))
        if response.status >= 400:
            self.events.append({"event": "http_error", "url": _safe_url(response.url),
                                "status": response.status,
                                "resource_type": response.request.resource_type})

    def _pageerror(self, error):
        self.console_events.append({"event": "pageerror", "message": str(error)[:4000],
                                    "at_ms": round((time.perf_counter()-self.started)*1000)})

    def _console(self, message):
        if message.type in {"warning", "error"}:
            location = dict(message.location)
            if location.get("url"):
                location["url"] = _safe_url(location["url"])
            self.console_events.append({"event": "console", "level": message.type,
                                        "message": message.text[:4000], "location": location,
                                        "at_ms": round((time.perf_counter()-self.started)*1000)})

    def capture(self, **metadata):
        if not self.directory or (metadata.get("outcome") == "success" and not self.capture_success):
            return
        try:
            self._cleanup(reserve=1)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            folder = Path(self.directory) / f"{stamp}-{uuid4().hex[:12]}"
            folder.mkdir(parents=True, exist_ok=False)
            metadata["events"] = list(self.events)
            metadata["console_events"] = list(self.console_events)
            metadata["outcome"] = metadata.get("outcome", "timeout")
            elapsed = round((time.perf_counter() - self.started) * 1000)
            metadata["elapsed_ms"] = elapsed
            metadata["dropped_requests"] = self.dropped_requests
            metadata["requests"] = [dict(record, age_ms=elapsed-record["started_ms"])
                                    for record in self.requests.values()]
            metadata["pending_requests"] = [record for record in metadata["requests"]
                                            if record["state"].startswith("pending")]
            # Read bodies only after requestfinished: pending response bodies can hang.
            bodies = []
            for request, record in list(self.completed):
                entry = {"url": record["url"], "status": record.get("status")}
                try:
                    response = request.response()
                    headers = response.headers
                    content_type = headers.get("content-type", "")
                    if "json" not in content_type:
                        continue
                    if not 0 < int(headers.get("content-length", "0")) <= 262144:
                        entry["body_omitted"] = "Unknown or excessive Content-Length"
                    elif headers.get("content-encoding", "identity") != "identity":
                        entry["body_omitted"] = "Compressed body may exceed size limit"
                    else:
                        body = response.body()
                        if len(body) > 262144:
                            entry["body_omitted"] = "Body exceeds 256 KiB"
                        else:
                            preview = json.dumps(_redact(json.loads(body)), ensure_ascii=False)
                            entry["json_preview"] = preview[:12000]
                            entry["preview_truncated"] = len(preview) > 12000
                except Exception as exc:
                    entry["body_error"] = str(exc)
                bodies.append(entry)
            metadata["completed_api_responses"] = bodies
            baseline = Path(self.directory) / "latest_success.json"
            if metadata["outcome"] == "timeout" and baseline.is_file():
                try:
                    previous = json.loads(baseline.read_text(encoding="utf-8"))
                    current_urls = {r["url"] for r in metadata["requests"]
                                    if r["resource_type"] in {"xhr", "fetch"}}
                    metadata["comparison"] = {
                        "baseline_file": previous["file"],
                        "baseline_url": previous["url"],
                        "baseline_captured_at": previous["captured_at"],
                        "api_urls_only_in_success": sorted(set(previous["api_urls"])-current_urls),
                        "api_urls_only_in_timeout": sorted(current_urls-set(previous["api_urls"])),
                    }
                except Exception as exc:
                    metadata["comparison_error"] = str(exc)
            LOGGER.warning("Browser diagnostics: tracked=%s pending=%s dropped=%s",
                           len(self.requests), len(metadata["pending_requests"]),
                           self.dropped_requests)
            for name, action in (
                ("html", lambda: (folder / "page.html").write_text(
                    self.page.content(), encoding="utf-8")),
                ("screenshot", lambda: self.page.screenshot(
                    path=str(folder / "page.png"), timeout=5000)),
            ):
                try:
                    action()
                except Exception as exc:
                    metadata[f"{name}_error"] = str(exc)
            (folder / "diagnostics.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            if metadata["outcome"] == "success":
                baseline.write_text(json.dumps({
                    "file": str((folder / "diagnostics.json").resolve()),
                    "url": metadata.get("requested_url"), "captured_at": stamp,
                    "api_urls": sorted({r["url"] for r in metadata["requests"]
                                        if r["resource_type"] in {"xhr", "fetch"}}),
                }), encoding="utf-8")
            LOGGER.warning("Browser %s evidence saved: %s", metadata["outcome"], folder.resolve())
        except Exception:
            LOGGER.warning("Unable to save browser evidence", exc_info=True)

    def close(self):
        for event, callback in self.listeners:
            try:
                self.page.remove_listener(event, callback)
            except Exception:
                pass
        self.listeners.clear()
        self.requests.clear()
        self.completed.clear()
        self.events.clear()
        self.console_events.clear()
        self.page = None
