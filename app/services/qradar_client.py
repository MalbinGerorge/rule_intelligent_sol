"""
Production-hardened HTTP client for the QRadar endpoints this project
uses: rules_with_data, rules_offense_contributions, building_blocks,
rules, log source types/instances, and the MITRE coverage app-proxy
endpoint.

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
    # CONFIRMED BUG FIX: had a leading space before "/config/..." in an
    # earlier version -- self.base_url + path would have produced a
    # malformed URL ("https://host /config/..."), silently breaking
    # every call to fetch_log_source_types(). Also missing the "/api"
    # prefix every other endpoint here has.
    "log_source_types": "/api/config/event_sources/log_source_management/log_source_types",
    "log_sources": "/api/config/event_sources/log_source_management/log_sources",
    "reference_sets": "/api/reference_data_collections/sets",
    "reference_set_entries": "/api/reference_data_collections/set_entries",
    # DSM field extraction data -- confirmed real field shapes from
    # QRadar's own API docs (pasted directly by the user). One parent
    # (regex_properties), seven children -- each child is a different
    # extraction MECHANISM depending on the log source's raw payload
    # format. See app/services/custom_property_sync.py for how these
    # get combined into two Postgres tables.
    "regex_properties": "/api/config/event_sources/custom_properties/regex_properties",
    "property_expressions": "/api/config/event_sources/custom_properties/property_expressions",
    "property_json_expressions": "/api/config/event_sources/custom_properties/property_json_expressions",
    "property_xml_expressions": "/api/config/event_sources/custom_properties/property_xml_expressions",
    "property_cef_expressions": "/api/config/event_sources/custom_properties/property_cef_expressions",
    "property_leef_expressions": "/api/config/event_sources/custom_properties/property_leef_expressions",
    "property_nvp_expressions": "/api/config/event_sources/custom_properties/property_nvp_expressions",
    "property_aql_expressions": "/api/config/event_sources/custom_properties/property_aql_expressions",
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

    def fetch_log_source_types(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["log_source_types"], accept="application/json"))

    def fetch_log_sources(self) -> list[str]:
        """GET /config/event_sources/log_source_management/log_sources —
        confirmed real shape includes id, name, type_id, enabled,
        status.status, last_event_time, average_eps, description (see
        project notes: description is analyst-entered and NOT reliably
        kept current -- treat as a hint, never as confirmed fact).
        No server-side type_id filter used here (unconfirmed whether
        this endpoint supports a `filter` query param) -- callers
        filter client-side. Worth revisiting if a real console confirms
        filter=type_id=X works, to avoid pulling the full log source
        list on every call."""
        return list(self._paginate_text(ENDPOINTS["log_sources"], accept="application/json"))

    def fetch_reference_sets(self) -> list[str]:
        """GET /reference_data_collections/sets — confirmed real shape
        from a live console includes id (the collection ID -- used to
        cross-reference entries), name, namespace, number_of_entries,
        entry_type, creation_time, time_to_live, expiry_type."""
        return list(self._paginate_text(ENDPOINTS["reference_sets"], accept="application/json"))

    def fetch_reference_set_entries(self) -> list[str]:
        """GET /reference_data_collections/set_entries — returns ALL
        entries across EVERY reference set on the console in one call;
        confirmed real shape includes collection_id (matches a set's
        own id from fetch_reference_sets), value, source, first_seen,
        last_seen. Callers filter client-side by collection_id -- no
        confirmed server-side filter for this endpoint, same tradeoff
        as fetch_log_sources()."""
        return list(self._paginate_text(ENDPOINTS["reference_set_entries"], accept="application/json"))

    def fetch_regex_properties(self) -> list[str]:
        """GET /config/event_sources/custom_properties/regex_properties
        -- the parent list of every custom event property (name,
        property_type, owner). Extraction logic lives in the 7
        expression endpoints below, not here."""
        return list(self._paginate_text(ENDPOINTS["regex_properties"], accept="application/json"))

    def fetch_property_expressions(self) -> list[str]:
        """Regex-based extraction expressions."""
        return list(self._paginate_text(ENDPOINTS["property_expressions"], accept="application/json"))

    def fetch_property_json_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_json_expressions"], accept="application/json"))

    def fetch_property_xml_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_xml_expressions"], accept="application/json"))

    def fetch_property_cef_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_cef_expressions"], accept="application/json"))

    def fetch_property_leef_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_leef_expressions"], accept="application/json"))

    def fetch_property_nvp_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_nvp_expressions"], accept="application/json"))

    def fetch_property_aql_expressions(self) -> list[str]:
        return list(self._paginate_text(ENDPOINTS["property_aql_expressions"], accept="application/json"))

    def _post(self, path: str, accept: str, data: dict) -> requests.Response:
        """POST counterpart to _get -- same retry/error handling, used
        only for the Ariel search lifecycle (create search, cancel
        search). No pagination concept applies to POST here."""
        headers = {"Accept": accept, "SEC": self.token}
        url = f"{self.base_url}{path}"

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            if self.request_delay:
                time.sleep(self.request_delay)
            try:
                resp = requests.post(
                    url, headers=headers, data=data, timeout=self.timeout, verify=self.verify_ssl
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt > self.max_retries:
                    raise QRadarAPIError(f"Network error after {attempt} attempts: {exc}", url=url) from exc
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                continue

            if resp.status_code in (200, 201):
                return resp

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt <= self.max_retries:
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                continue

            raise QRadarAPIError(
                f"POST {url} failed with {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                url=url,
            )
        raise QRadarAPIError(f"Exhausted retries for {url}: {last_exc}", url=url)  # pragma: no cover

    def create_ariel_search(self, aql_query: str) -> dict:
        """POST /ariel/searches -- starts an ASYNC search, returns
        immediately with search metadata (including some kind of
        search identifier and an initial status). NEEDS LIVE
        VERIFICATION: the exact response field name for the search
        identifier ("search_id" vs "cursor_id" vs "id") is NOT
        confirmed against a real response -- built from QRadar's
        general documented pattern, not a real sample like the
        reference_data_collections endpoints were. run_ariel_search()
        below tries several likely field names defensively, but this
        should be confirmed with one real test call before being
        fully trusted."""
        return self._post(
            "/api/ariel/searches", accept="application/json", data={"query_expression": aql_query}
        ).json()

    def get_ariel_search_status(self, search_id: str) -> dict:
        """GET /ariel/searches/{search_id} -- poll until status is
        COMPLETED (or ERROR/CANCELED)."""
        return self._get(f"/api/ariel/searches/{search_id}", accept="application/json").json()

    def get_ariel_search_results(self, search_id: str) -> dict:
        """GET /ariel/searches/{search_id}/results -- only meaningful
        once status == COMPLETED."""
        return self._get(f"/api/ariel/searches/{search_id}/results", accept="application/json").json()

    def cancel_ariel_search(self, search_id: str) -> None:
        """POST /ariel/searches/{search_id} with status=CANCELED --
        confirmed as a real, documented QRadar capability. Used by
        run_ariel_search() to explicitly stop a search that's taking
        too long, rather than leaving it running orphaned server-side
        after our own code gives up waiting."""
        try:
            self._post(f"/api/ariel/searches/{search_id}", accept="application/json", data={"status": "CANCELED"})
        except QRadarAPIError:
            pass  # best-effort -- we're already in a failure path, don't raise a second error over this

    def run_ariel_search(
        self, aql_query: str, max_poll_attempts: int = 20, poll_interval: float = 2.0
    ) -> dict:
        """Runs the FULL async search lifecycle in one call: create ->
        poll status until COMPLETED/ERROR/CANCELED -> fetch results.
        Bounded by max_poll_attempts so a stuck/slow QRadar search
        can't hang our own code forever -- if it hasn't completed
        within that many polls, it's explicitly CANCELED and a
        QRadarAPIError is raised, rather than hanging indefinitely or
        leaving an orphaned still-running search server-side."""
        search = self.create_ariel_search(aql_query)
        # Defensive: try the field names QRadar's documented API
        # patterns commonly use, since the exact one isn't confirmed
        # against a real response yet -- see create_ariel_search's docstring.
        search_id = search.get("search_id") or search.get("cursor_id") or search.get("id")
        if search_id is None:
            raise QRadarAPIError(f"Could not find a search identifier in the response: {search}")

        for _ in range(max_poll_attempts):
            time.sleep(poll_interval)
            status_resp = self.get_ariel_search_status(search_id)
            status = status_resp.get("status")
            if status == "COMPLETED":
                return self.get_ariel_search_results(search_id)
            if status in ("ERROR", "CANCELED"):
                raise QRadarAPIError(f"Ariel search {search_id} ended with status {status}: {status_resp}")

        self.cancel_ariel_search(search_id)
        raise QRadarAPIError(
            f"Ariel search {search_id} did not complete within "
            f"{max_poll_attempts * poll_interval:.0f}s and was canceled."
        )