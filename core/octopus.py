"""Fetch and filter Octopus Agile electricity unit rates.

Pure fetch/filter core: nothing here knows about Telegram or any other
consumer, so future actuators (GPU jobs, smart plugs) can reuse it too.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import requests

BASE_URL = "https://api.octopus.energy/v1"
DEFAULT_PAGE_SIZE = 1500  # Octopus's max page size; fetch_agile_rates isn't limited to one day

VALID_REGIONS = {
    "A": "East England",
    "B": "East Midlands",
    "C": "London",
    "D": "North Wales, Merseyside & Cheshire",
    "E": "West Midlands",
    "F": "North East England",
    "G": "North West England",
    "H": "Southern England",
    "J": "South East England",
    "K": "South Wales",
    "L": "South West England",
    "M": "Yorkshire",
    "N": "South Scotland",
    "P": "North Scotland",
}


@dataclasses.dataclass(frozen=True)
class RateSlot:
    valid_from: dt.datetime
    valid_to: dt.datetime
    value_inc_vat: float
    value_exc_vat: float


def get_current_agile_product_code(*, session: requests.Session | None = None) -> str:
    """Look up the currently active Agile *import* product code.

    Octopus rolls the Agile product code over periodically (e.g. AGILE-24-10-01),
    so we query the products list instead of hard-coding a code.
    """
    session = session or requests.Session()

    # Fetch Octopus's full product catalogue; `results` is a list of product dicts.
    response = session.get(f"{BASE_URL}/products/", params={"brand": "OCTOPUS_ENERGY"})
    response.raise_for_status()
    results = response.json()["results"]

    # Keep only currently-active Agile import products.
    candidates = []
    now = dt.datetime.now(dt.timezone.utc)

    for product in results:
        is_agile = product["code"].startswith("AGILE-")
        is_import = product["direction"] == "IMPORT"
        available_from = _parse_iso(product["available_from"])
        available_to = None if product["available_to"] is None else _parse_iso(product["available_to"])
        active = (available_from <= now) and (available_to is None or available_to >= now)

        if is_agile and is_import and active:
            candidates.append(product)

    if not candidates:
        raise LookupError("No active Agile product found.")

    # Products can briefly overlap during a rollover; use the most recent.
    candidates.sort(key=lambda product: _parse_iso(product["available_from"]), reverse=True)
    return candidates[0]["code"]


def fetch_agile_rates(
    product_code: str,
    region: str,
    period_from: dt.datetime,
    period_to: dt.datetime,
    *,
    session: requests.Session | None = None,
) -> list[RateSlot]:
    """Fetch half-hourly unit rates for a region between two UTC datetimes."""
    session = session or requests.Session()
    tariff_code = f"E-1R-{product_code}-{region}"
    url = (
        f"{BASE_URL}/products/{product_code}/electricity-tariffs/"
        f"{tariff_code}/standard-unit-rates/"
    )
    params = {
        "period_from": _format_iso(period_from),
        "period_to": _format_iso(period_to),
        "page_size": DEFAULT_PAGE_SIZE,
    }

    # Follow `next` across all pages; results come back newest-first.
    slots = []
    next_url = url

    while next_url is not None:
        response = session.get(next_url, params=params)
        response.raise_for_status()
        payload = response.json()

        for result in payload["results"]:
            slot = RateSlot(
                valid_from=_parse_iso(result["valid_from"]),
                valid_to=_parse_iso(result["valid_to"]),
                value_inc_vat=result["value_inc_vat"],
                value_exc_vat=result["value_exc_vat"],
                )
            slots.append(slot)

        next_url = payload.get("next")
        params = None  # `next` already has the query string baked in

    return slots


def categorize_slot(slot: RateSlot, threshold: float) -> str:
    """Categorize a slot as "negative", "ok", or "spike" relative to `threshold`.

    Single source of truth for the plunge/ok/spike boundaries: every filter
    below, and any consumer (e.g. a notifier) that needs a per-slot label
    rather than a filtered list, derives from this.
    """
    if slot.value_inc_vat < 0:
        return "negative"
    if slot.value_inc_vat > threshold:
        return "spike"
    return "ok"


def filter_negative_slots(slots: list[RateSlot]) -> list[RateSlot]:
    """Return slots with a strictly negative price (you're paid to use electricity)."""
    return [slot for slot in slots if slot.value_inc_vat < 0]


def filter_ok_slots(slots: list[RateSlot], threshold: float) -> list[RateSlot]:
    """Return non-negative slots priced at or below `threshold` (pence/kWh, inc. VAT)."""
    return [slot for slot in slots if categorize_slot(slot, threshold) == "ok"]


def filter_spike_slots(slots: list[RateSlot], threshold: float) -> list[RateSlot]:
    """Return slots priced strictly above `threshold` (pence/kWh, inc. VAT)."""
    return [slot for slot in slots if categorize_slot(slot, threshold) == "spike"]


def _parse_iso(value: str) -> dt.datetime:
    """Parse an Octopus API timestamp (e.g. '2025-01-01T00:00:00Z') to a datetime."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_iso(value: dt.datetime) -> str:
    """Format a datetime as the ISO string the Octopus API expects, e.g. '2025-01-01T00:00:00Z'."""
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
