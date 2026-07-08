"""Entry point: wires the core fetch/filter logic together with the Telegram notifier.

Run daily (via GitHub Actions) after Octopus publishes next-day rates (~4pm UK).
Run as a module from the project root: python -m scripts.telegram_alerts
"""

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from core.octopus import fetch_agile_rates, get_current_agile_product_code
from notifiers.telegram import (
    check_for_config_updates,
    send_all_slots,
    send_notable_alert,
    send_text,
)

PROJECT_ROOT = Path(__file__).parent.parent
STATE_DIR = PROJECT_ROOT / "state"
# Canonical region, protected from Telegram commands. This script only ever
# READS it (to seed state_telegram.json the first time), never writes it.
SHARED_STATE_PATH = STATE_DIR / "state_default.json"
# Telegram's own sandboxed state (region + threshold + offset). The only
# file /setregion and /setthreshold are allowed to change.
TELEGRAM_STATE_PATH = STATE_DIR / "state_telegram.json"
LONDON_TZ = ZoneInfo("Europe/London")

load_dotenv(PROJECT_ROOT / ".env")  # no-op locally if .env doesn't exist; harmless in CI too


def _default_telegram_state() -> dict:
    if SHARED_STATE_PATH.exists():
        region = json.loads(SHARED_STATE_PATH.read_text())["region"]
    else:
        region = os.environ.get("REGION")
    if not region:
        raise RuntimeError(
            "No state/state_default.json and REGION isn't set. "
            "Run `python -m scripts.setup_region` first, or set REGION."
        )
    return {
        "region": region,
        "threshold": float(os.environ.get("THRESHOLD", "30.0")),
        "telegram_offset": 0,
    }


def _load_telegram_state() -> dict:
    if not TELEGRAM_STATE_PATH.exists():
        return _default_telegram_state()
    return json.loads(TELEGRAM_STATE_PATH.read_text())


def _save_telegram_state(state: dict) -> None:
    TELEGRAM_STATE_PATH.write_text(json.dumps(state, indent=2))


def _tomorrows_utc_window() -> tuple[dt.datetime, dt.datetime]:
    """Return (period_from, period_to) in UTC spanning tomorrow, UK local time."""
    today_local = dt.datetime.now(LONDON_TZ).date()
    tomorrow_local = today_local + dt.timedelta(days=1)
    start = dt.datetime(tomorrow_local.year, tomorrow_local.month, tomorrow_local.day, 0, 0, tzinfo=LONDON_TZ)
    end = start + dt.timedelta(days=1)
    start_utc = start.astimezone(dt.timezone.utc)
    end_utc = end.astimezone(dt.timezone.utc)

    return (start_utc, end_utc)


def main() -> None:
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    state = _load_telegram_state()

    new_threshold, new_region, next_offset = check_for_config_updates(
        bot_token=os.environ["TELEGRAM_ALERTS_BOT_TOKEN"],
        chat_id=chat_id,
        offset=state["telegram_offset"],
    )
    state["telegram_offset"] = next_offset

    confirmations = []
    if new_threshold is not None:
        state["threshold"] = new_threshold
        confirmations.append(f"Threshold updated to {new_threshold}p.")
    if new_region is not None:
        state["region"] = new_region
        confirmations.append(f"Region updated to {new_region}.")

    _save_telegram_state(state)

    if confirmations:
        message = " ".join(confirmations)
        print(message)
        send_text(
            message,
            bot_token=os.environ["TELEGRAM_ALERTS_BOT_TOKEN"],
            chat_id=chat_id,
        )

    region = state["region"]
    threshold = state["threshold"]

    product_code = get_current_agile_product_code()
    period_from, period_to = _tomorrows_utc_window()
    slots = fetch_agile_rates(product_code, region, period_from, period_to)

    print(f"Product code: {product_code}")
    print(f"Got {len(slots)} slots, threshold {threshold}p")

    send_all_slots(
        slots,
        threshold=threshold,
        bot_token=os.environ["TELEGRAM_ALL_SLOTS_BOT_TOKEN"],
        chat_id=chat_id,
    )
    send_notable_alert(
        slots,
        threshold=threshold,
        bot_token=os.environ["TELEGRAM_ALERTS_BOT_TOKEN"],
        chat_id=chat_id,
    )
    print("Done.")


if __name__ == "__main__":
    main()
