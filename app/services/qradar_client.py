"""
Production-hardened HTTP client for the QRadar endpoints this project
uses: rules_with_data, rules_offense_contributions, building_blocks,
rules, and the MITRE coverage app-proxy endpoint.

One client instance = one customer's QRadar console (multi-tenant: host
and token come from the `customers` / `customer_credentials` tables,
never hardcoded here).

CONFIRMED against a real QRadar console (found through direct debugging
against Cotecna's environment — see project chat history for the trail):
  - Auth: `SEC` header (API token). No `Version` or `Content-Type` header needed.
  - `Range` (e.g. "items=0-49") is a QUERY PARAMETER, not a header.
  - `Allow-Hidden: true` header is required on rules_with_data, rules,
    building_blocks, AND the MITRE coverage endpoint — without it,
    hidden/SYSTEM-owned objects are silently omitted.
  - MITRE coverage is a PER-RULE lookup keyed by each rule's "identifier"
    field (from rules_with_data), not one bulk call.
  - Each request MUST use a fresh connection (plain requests.get, NOT a
    reused requests.Session). A persistent session caused intermittent
    403s once hundreds of sequential requests were made — almost
    certainly something in front of the console (load balancer / proxy /
    WAF) mishandling a reused keep-alive connection. Do not reintroduce
    Session-based connection pooling without re-verifying against a real
    console first.

Production hardening in this version:
  - Retries with exponential backoff on transient failures only
    (connection errors, timeouts, 429, and 5xx). 401/403/404 are NEVER
    retried — those are real signals (auth/permission/not-found) and
    retrying just delays surfacing the actual problem.
  - Optional per-request delay (`request_delay`), useful for the MITRE
    loop which fires one request per rule — can be hundreds/thousands
    of calls against a real environment.
  - Raises a typed QRadarAPIError instead of leaking raw requests
    exceptions, with the status code and URL attached for easier
    handling upstream.
  - Never logs the token.
"""
from __future__ import annotations

import logging
import time

import requests
import urllib3

log = logging.getLogger("qradar_client")

# QRadar consoles commonly use self-signed certs; when verify_ssl=False is
# explicitly chosen (per-customer, from the customers table), suppress the
# resulting warning rather than spamming logs for an intentional choice.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENDPOINTS = {
    "rules_with_data": "/api/analytics/rules_with_data",
    "rules_offense_contributions": "/api/analytics/rules_offense_contributions",
    "building_blocks": "/api/analytics/building_blocks",
    "rules": "/api/analytics/rules",
}
MITRE_APP_PROXY_BASE = "/console/plugins/app_proxy:UseCaseManager_Service"

DEFAULT_PAGE_SIZE = 50
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.5  # seconds; roughly doubles each retry

# Confirmed needed for rules_with_data; applied to the other /analytics/*
# list endpoints too since they're the same family of QRadar objects —
# harmless if a given endpoint ignores it.
ALLOW_HIDDEN_ENDPOINTS = {
    ENDPOINTS["rules_with_data"],
    ENDPOINTS["rules"],
    ENDPOINTS["building_blocks"],
}

# Transient/server-side — worth retrying. 401/403/404 are deliberately
# excluded: retrying an auth or permission failure doesn't fix it, it
# just burns time before the real error surfaces.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class QRadarAPIError(Exception):
    """Raised when a QRadar API call fails (after retries, for transient
    failures; immediately, for non-retryable ones like 403)."""

    def __init__(self, message: str, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class QRadarClient:
    def __init__(
        self,
        host: str,
        token: str,
        verify_ssl: bool = False,
        scheme: str = "https",
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        request_delay: float = 0.0,
    ):
        if not host or not token:
            raise ValueError("host and token are required")
        self.base_url = f"{scheme}://{host}"
        self.token = token
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.request_delay = request_delay

    def _get(
        self,
        path: str,
        accept: str,
        range_value: str | None = None,
        allow_hidden: bool = False,
    ) -> requests.Response:
        headers = {"Accept": accept, "SEC": self.token}
        if allow_hidden:
            headers["Allow-Hidden"] = "true"
        params = {}
        if range_value:
            params["Range"] = range_value  # QRadar wants this as a query param, not a header
        url = f"{self.base_url}{path}"

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):  # +1 to include the initial try
            if self.request_delay:
                time.sleep(self.request_delay)
            try:
                # Deliberately a fresh connection per call (requests.get,
                # not a Session) — see module docstring for why.
                resp = requests.get(
                    url, headers=headers, params=params, timeout=self.timeout, verify=self.verify_ssl
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt > self.max_retries:
                    raise QRadarAPIError(f"Network error after {attempt} attempts: {exc}", url=url) from exc
                wait = self.backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "GET %s failed (%s), retrying in %.1fs (attempt %d/%d)",
                    url, exc, wait, attempt, self.max_retries,
                )
                time.sleep(wait)
                continue

            if resp.status_code in (200, 206):
                return resp

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt <= self.max_retries:
                wait = self.backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "GET %s -> %s, retrying in %.1fs (attempt %d/%d)",
                    url, resp.status_code, wait, attempt, self.max_retries,
                )
                time.sleep(wait)
                continue

            # Non-retryable failure (401/403/404/etc.), or retries exhausted
            log.error("GET %s -> %s: %s", url, resp.status_code, resp.text[:500])
            raise QRadarAPIError(
                f"GET {url} failed with {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                url=url,
            )

        raise QRadarAPIError(f"Exhausted retries for {url}: {last_exc}", url=url)  # pragma: no cover

    def _paginate_text(self, path: str, accept: str, page_size: int = DEFAULT_PAGE_SIZE):
        """Yields raw response bodies page by page, following QRadar's
        Range/Content-Range pagination convention. Stops on a plain 200
        (no more data) or once Content-Range says we've covered the total."""
        allow_hidden = path in ALLOW_HIDDEN_ENDPOINTS
        start = 0
        while True:
            end = start + page_size - 1
            resp = self._get(
                path, accept=accept, range_value=f"items={start}-{end}", allow_hidden=allow_hidden
            )
            yield resp.text
            content_range = resp.headers.get("Content-Range", "")
            if resp.status_code == 200 or not content_range:
                break
            try:
                total = int(content_range.split("/")[-1])
            except ValueError:
                break
            start = end + 1
            if start >= total:
                break

    # -- rules_with_data (confirmed JSON, not XML) ----------------------

    def fetch_rules_with_data(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["rules_with_data"], accept="application/json"))

    def fetch_rules_offense_contributions(self) -> list[str]:
        """GET /analytics/rules_offense_contributions — JSON.
        Fields (per QRadar docs): id, rule_id, rule_name, rule_type,
        offense_id, event_count, first_event, last_event (epoch ms)."""
        return list(
            self._paginate_text(ENDPOINTS["rules_offense_contributions"], accept="application/json")
        )

    # -- MITRE mapping (app proxy) --------------------------------------
    # Confirmed: this is a PER-RULE lookup, not one bulk call. Each rule
    # from rules_with_data has an "identifier" field; that identifier is
    # what goes in the URL here.

    def fetch_mitre_mapping(self, identifier: str) -> dict:
        path = f"{MITRE_APP_PROXY_BASE}/api/mitre/mitre_coverage/{identifier}"
        return self._get(path, accept="application/json", allow_hidden=True).json()

    # -- Validation / reference endpoints --------------------------------

    def fetch_building_blocks(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["building_blocks"], accept="application/json"))

    def fetch_rules(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["rules"], accept="application/json"))