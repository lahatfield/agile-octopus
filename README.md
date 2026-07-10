# Agile Octopus Telegram Notifications

A Python bot that watches [Octopus Energy's Agile](https://octopus.energy/smart/agile/) half-hourly
electricity tariff and posts alerts to a Telegram group when prices go negative, drop to a
cheap/"ok" level, or spike above a configurable threshold. Runs daily via a scheduled
GitHub Actions workflow.

## How it works

Each day (after Octopus publishes the next day's rates, ~4pm UK time), the bot:

1. Looks up the current Agile product code (these roll over periodically, so it's looked
   up dynamically rather than hard-coded).
2. Fetches tomorrow's half-hourly rates for your region.
3. Checks for `/setthreshold` or `/setregion` commands sent in the Telegram group since
   the last run, and applies any changes.
4. Categorises every slot as **negative** (💰 you're paid to use electricity), **ok**
   (✅ at or below your threshold), or **spike** (❌ above it).
5. Posts two messages: one bot lists every slot for the day; a second bot posts only the
   negative/spike ones, and only if any exist.

## Architecture

| Path | Purpose |
| --- | --- |
| `notifiers/telegram.py` | Formats slots and talks to the Telegram Bot API. Sends alerts, reads incoming `/setthreshold` and `/setregion` commands. |
| `scripts/telegram_alerts.py` | The daily job: reads state, fetches rates, checks for Telegram commands, sends alerts. Run via GitHub Actions. |
| `scripts/setup_region.py` | One-time (or one-off update) interactive script that sets your default region. |
| `scripts/check_env.py` | Reports which required environment variables are set, without printing their actual values. |

Rate fetching/categorizing (`octopus_core`) lives in a separate repo,
[agile-octopus-core](https://github.com/lahatfield/agile-octopus-core), and is pulled in
as a regular dependency (see `pyproject.toml`).

### Configuration and state

- **`.env`** (gitignored, never committed) holds secrets and one-time seed defaults.
  Copy `.env.example` to `.env` and fill in real values.
- **`state/state_default.json`** (tracked in git) holds the default DNO region
  (Distribution Network Operator) - Octopus's single-letter code (A–P) for your regional
  electricity distributor.
- **`state/state_telegram.json`** (tracked in git) is the Telegram bot's own sandboxed
  state, including its current region, threshold, and a cursor tracking which Telegram messages
  it has already processed. Seeded once from `state_default.json` and `.env`, then fully
  independent. `/setregion` and `/setthreshold` only ever change *this* file, so a
  Telegram-triggered change can't silently affect some other future consumer of this
  repo that reads `state_default.json` instead.

## Setup

### 1. Install dependencies

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync --group dev
```

This creates `.venv` and installs everything pinned in `uv.lock` (runtime deps plus
`pytest`, for running tests).

### 2. Create two Telegram bots

Via [@BotFather](https://t.me/BotFather): `/newbot`, twice, giving you two tokens — one
for the "all slots" bot, one for the "alerts" bot. Add both to a Telegram group with your
household. Disable **privacy mode** for the alerts bot (BotFather → `/mybots` → select
the bot → Bot Settings → Group Privacy → Turn off, then remove and re-add it to the
group) so it can see every message, not just ones that `@mention` it or are commands.

To find your group's chat ID: send any message in the group, then visit
`https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and look for the `chat.id`
field (a negative number for groups).

### 3. Configure secrets

```sh
cp .env.example .env
```
Fill in `TELEGRAM_CHAT_ID`, `TELEGRAM_ALL_SLOTS_BOT_TOKEN`, and
`TELEGRAM_ALERTS_BOT_TOKEN` in `.env`. `REGION` and `THRESHOLD` are optional one-time
seed defaults (see [Configuration and state](#configuration-and-state) above).

Run `uv run python -m scripts.check_env` any time to confirm which required variables
are set, without ever printing their actual values.

### 4. Set your region

```sh
uv run python -m scripts.setup_region
```

### 5. Run it

```sh
uv run python -m scripts.telegram_alerts
```

## Telegram commands

Sent as a message in the group:

- `/setthreshold 25` — prices at or below 25p/kWh count as "ok"; above that, "spike".
- `/setregion C` — switch to a different DNO region.

Both take effect on the *next* scheduled run (not instantly), since the bot only checks
for new commands once a day, as part of the same run that sends that day's alerts — this
keeps the whole thing running on a free scheduled GitHub Action rather than needing an
always-on server.

## Running tests

```sh
uv run python -m pytest
```

## Deployment

Runs daily via a scheduled GitHub Actions workflow (see `.github/workflows/`).