"""Live CPCB CAAQMS adapter.

CPCB's real-time portal (app.cpcbccr.com / sameer.gov.in) exposes undocumented,
frequently-rotating XHR endpoints that are also geo/IP-restricted. Rather than
hard-code a brittle endpoint (which would break silently), this adapter:

  * isolates all HTTP/parse logic behind the ``SourceAdapter`` interface, and
  * parses the *shape* of CPCB payloads (nested pollutant objects keyed by
    ``pollutant_id`` / ``pollutant_avg``) that has been stable across revisions.

It is selected via ``--source live`` or ``AQ_SOURCE=live``. When the live feed
is unreachable, it raises a clear ``SourceUnavailable`` error instead of
silently producing data — the mock is the default for exactly this reason.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from ..config import get_settings
from .base import RawReading, SourceAdapter

log = logging.getLogger(__name__)

# Canonical CPCB pollutant id -> our pollutant key. CPCB uses numeric/string ids
# in its payloads; this map covers the common PM/GAS ids.
CPCB_POLLUTANT_IDS: dict[str, str] = {
    "pm25": "pm25",
    "pm2.5": "pm25",
    "pm_2.5": "pm25",
    "pm10": "pm10",
    "no2": "no2",
    "so2": "so2",
    "co": "co",
    "ozone": "o3",
    "o3": "o3",
}


class SourceUnavailable(RuntimeError):
    """Raised when the live CPCB feed cannot be reached or parsed."""


class LiveCPCBSource(SourceAdapter):
    """Real HTTP adapter for CPCB CAAQMS data. Network-dependent."""

    name = "live"

    def __init__(
        self,
        api_base: Optional[str] = None,
        timeout: float = 15.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_base = api_base or get_settings().cpcb_api_base
        self.timeout = timeout
        self._session = session or requests.Session()

    # ------------------------------------------------------------------ #
    def _post(self, payload: dict[str, Any]) -> Any:
        """POST a CPCB dashboard request and return parsed JSON, or raise."""
        url = f"{self.api_base}/api/aq_dashboard"
        try:
            resp = self._session.post(
                url,
                data=payload,
                timeout=self.timeout,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceUnavailable(f"CPCB request failed: {exc}") from exc
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise SourceUnavailable(f"CPCB returned non-JSON: {exc}") from exc

    @staticmethod
    def _parse_station_block(block: dict[str, Any]) -> dict[str, object]:
        """Extract pollutant values from one CPCB station payload block."""
        out: dict[str, object] = {}
        # Modern shape: block["pollutants"] is a list of {pollutant_id, pollutant_avg}.
        for item in block.get("pollutants", []) or []:
            key = CPCB_POLLUTANT_IDS.get(
                str(item.get("pollutant_id", "")).lower().strip()
            )
            if key:
                out[key] = item.get("pollutant_avg")
        # Fallback: flat keys at the station level (older revisions).
        if not out:
            for raw_key, our_key in CPCB_POLLUTANT_IDS.items():
                if raw_key in block:
                    out.setdefault(our_key, block[raw_key])
        return out

    # ------------------------------------------------------------------ #
    def fetch_latest(self, station_name: str) -> Optional[RawReading]:
        payload = {
            "station": station_name,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        data = self._post(payload)
        # Expect either a list of station blocks or a single dict.
        blocks = data if isinstance(data, list) else [data]
        for blk in blocks:
            if isinstance(blk, dict) and (
                station_name.lower() in str(blk.get("station", "")).lower()
                or "station" not in blk
            ):
                pollutants = self._parse_station_block(blk)
                if pollutants:
                    return RawReading(
                        station_name=station_name,
                        timestamp=datetime.now(timezone.utc),
                        pollutants=pollutants,
                        co_input_unit="mg/m3",
                    )
        log.warning("CPCB: no usable block for station %r", station_name)
        return None

    def fetch_range(
        self, station_name: str, start: datetime, end: datetime
    ) -> list[RawReading]:
        # CPCB's dashboard serves one day at a time; iterate days in the range.
        out: list[RawReading] = []
        day = start.astimezone(timezone.utc).date()
        last = end.astimezone(timezone.utc).date()
        while day <= last:
            payload = {"station": station_name, "date": day.strftime("%Y-%m-%d")}
            try:
                data = self._post(payload)
            except SourceUnavailable as exc:
                log.warning("CPCB: skipping %s (%s)", day, exc)
                day += timedelta(days=1)
                continue
            for slot in data if isinstance(data, list) else [data]:
                if not isinstance(slot, dict):
                    continue
                pollutants = self._parse_station_block(slot)
                ts = self._slot_timestamp(slot, day)
                if pollutants and ts and start <= ts < end:
                    out.append(
                        RawReading(
                            station_name=station_name,
                            timestamp=ts,
                            pollutants=pollutants,
                            co_input_unit="mg/m3",
                        )
                    )
            day += timedelta(days=1)
        return out

    @staticmethod
    def _slot_timestamp(slot: dict[str, Any], day) -> Optional[datetime]:
        raw = slot.get("last_update") or slot.get("time") or slot.get("timestamp")
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%H:%M"):
            try:
                dt = datetime.strptime(str(raw), fmt)
                if fmt == "%H:%M":
                    dt = datetime.combine(day, dt.time())
                # CPCB reports in IST.
                from zoneinfo import ZoneInfo

                return dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            except ValueError:
                continue
        return None
