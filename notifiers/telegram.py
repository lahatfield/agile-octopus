"""Format Agile rate slots and post them to a Telegram group.

Takes raw slots from core.octopus and a single price threshold; knows
nothing about how slots were fetched, so a future actuator can reuse the
core without depending on this module.

Two independent "bots" (distinguished by bot_token) consume this module:
  - the "all slots" bot posts every slot for the day, every day.
  - the "alerts" bot posts only plunge/spike slots, and only if any exist.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import requests

from core.octopus import (
    RateSlot,
    VALID_REGIONS,
    categorize_slot,
    filter_negative_slots,
    filter_spike_slots,
)

TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}"
LONDON_TZ = ZoneInfo("Europe/London")

# Slash commands are delivered to bots regardless of group privacy mode,
# unlike plain messages, so no special bot configuration is needed for this.
SET_THRESHOLD_PATTERN = re.compile(r"^/setthreshold(?:@\w+)?\s+(-?\d+(?:\.\d+)?)")
SET_REGION_PATTERN = re.compile(r"^/setregion(?:@\w+)?\s+([A-Za-z])")

EMOJI_BY_CATEGORY = {
    "negative": "💰",
    "ok": "✅",
    "spike": "❌",
}


def _format_time_range(slot: RateSlot) -> str:
    local_from = slot.valid_from.astimezone(LONDON_TZ)
    local_to = slot.valid_to.astimezone(LONDON_TZ)
    return f"{local_from:%H:%M}-{local_to:%H:%M}"


def _format_slot(slot: RateSlot, threshold: float) -> str:
    emoji = EMOJI_BY_CATEGORY[categorize_slot(slot, threshold)]
    return f"{emoji} {_format_time_range(slot)}: {slot.value_inc_vat:.2f}p/kWh"


def _describe_day(slots: list[RateSlot]) -> str:
    """Describe the (single) calendar day `slots` fall on, from a UK-local viewpoint."""
    slot_date = slots[0].valid_from.astimezone(LONDON_TZ).date()
    today = dt.datetime.now(LONDON_TZ).date()
    if slot_date == today:
        return "today"
    if slot_date == today + dt.timedelta(days=1):
        return "tomorrow"
    return f"{slot_date:%a %d %b}"


def _build_message(slots: list[RateSlot], threshold: float, header: str) -> str:
    sorted_slots = sorted(slots, key=lambda slot: slot.valid_from)
    lines = [header] + [_format_slot(slot, threshold) for slot in sorted_slots]
    return "\n".join(lines)


def _post_message(
    text: str,
    *,
    bot_token: str,
    chat_id: str,
    session: requests.Session | None = None,
) -> None:
    session = session or requests.Session()
    url = f"{TELEGRAM_BASE_URL.format(token=bot_token)}/sendMessage"
    response = session.post(url, json={"chat_id": chat_id, "text": text})
    response.raise_for_status()


def send_text(
    text: str,
    *,
    bot_token: str,
    chat_id: str,
    session: requests.Session | None = None,
) -> None:
    """Post an arbitrary plain-text message, e.g. a confirmation reply."""
    _post_message(text, bot_token=bot_token, chat_id=chat_id, session=session)


def check_for_config_updates(
    *,
    bot_token: str,
    chat_id: str,
    offset: int,
    session: requests.Session | None = None,
) -> tuple[float | None, str | None, int]:
    """Check for /setthreshold and /setregion commands sent to `chat_id` since `offset`.

    Returns (new_threshold, new_region, next_offset). Either of the first
    two is None if no valid matching command was found since `offset`; if
    several of the same kind were sent, the most recent one wins. Callers
    should persist `next_offset` and pass it back in as `offset` next time,
    so the same messages aren't reprocessed.
    """
    session = session or requests.Session()
    url = f"{TELEGRAM_BASE_URL.format(token=bot_token)}/getUpdates"
    response = session.get(url, params={"offset": offset, "timeout": 0})
    response.raise_for_status()
    updates = response.json()["result"]

    new_threshold = None
    new_region = None
    next_offset = offset

    for update in updates:
        next_offset = max(next_offset, update["update_id"] + 1)
        message = update.get("message")
        if message is None or str(message["chat"]["id"]) != str(chat_id):
            continue
        text = message.get("text", "")

        threshold_match = SET_THRESHOLD_PATTERN.match(text)
        if threshold_match:
            new_threshold = float(threshold_match.group(1))

        region_match = SET_REGION_PATTERN.match(text)
        if region_match:
            candidate = region_match.group(1).upper()
            if candidate in VALID_REGIONS:
                new_region = candidate

    return new_threshold, new_region, next_offset


def send_all_slots(
    slots: list[RateSlot],
    *,
    threshold: float,
    bot_token: str,
    chat_id: str,
    session: requests.Session | None = None,
) -> None:
    """Post every slot for the day, marked with an emoji per `threshold`."""
    if not slots:
        return
    header = f"Agile prices for {_describe_day(slots)}:\n"
    message = _build_message(slots, threshold, header)
    _post_message(message, bot_token=bot_token, chat_id=chat_id, session=session)


def send_notable_alert(
    slots: list[RateSlot],
    *,
    threshold: float,
    bot_token: str,
    chat_id: str,
    session: requests.Session | None = None,
) -> None:
    """Post only plunge/spike slots (skipping OK ones), if any exist."""
    notable_slots = filter_negative_slots(slots) + filter_spike_slots(slots, threshold)
    if not notable_slots:
        return
    header = f"Agile plunge/spike alert for {_describe_day(notable_slots)}:\n"
    message = _build_message(notable_slots, threshold, header)
    _post_message(message, bot_token=bot_token, chat_id=chat_id, session=session)
