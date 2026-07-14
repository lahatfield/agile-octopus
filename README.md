# Agile Octopus Telegram Notifications

A Python bot that watches [Octopus Energy's Agile](https://octopus.energy/smart/agile/) half-hourly
electricity tariff and posts alerts to Telegram when prices go negative, drop to a
cheap/"ok" level, or spike above a configurable threshold.

## How it works

Each day (after Octopus publishes the next day's rates, ~4pm UK time), a scheduled job:

1. Looks up the current Agile product code (these roll over periodically, so it's looked
   up dynamically rather than hard-coded).
2. Fetches tomorrow's half-hourly rates for every region any registered chat uses.
3. Categorises every slot as **negative** (💰 you're paid to use electricity), **ok**
   (✅ at or below that chat's threshold), or **spike** (❌ above it).
4. Sends each chat the message type(s) it's configured for (see `/setmode` below).

A separate job polls Telegram every few minutes for commands, so config changes and
on-demand requests (`/today`, `/tomorrow`) take effect within a few minutes rather than
waiting for the next scheduled daily run.

## For Users: Running on GitHub Actions

1. Create your own Telegram bot via [@BotFather](https://t.me/BotFather): `/newbot`. No
   privacy-mode changes needed.

2. Add the bot to any Telegram chats you want alerts in (group chat or DMs). The bot only
   ever reacts to slash commands, which Telegram delivers to bots regardless of privacy
   mode, so leave privacy mode on (the default) and it'll never see ordinary chat messages.

3. Make your own copy of this repository and upload it to GitHub. 

4. Create another empty and private GitHub repository and obtain a PAT (Personal Access Token) with 
   read and write permissions. Give it a first commit (e.g. tick "Add a README" on creation)
   so GitHub Actions has something to check out.

5. Under Settings → Secrets and variables → Actions, create two repository secrets:

   - `STATE_REPO_TOKEN`: The PAT for the empty repository you just created.
   - `TELEGRAM_BOT_TOKEN`: The bot token for your Telegram bot, used as a secret to
     communicate with the Telegram API.

6. Register your Telegram chat by sending `/start` (or any other valid command, see below).

There are two scheduled GitHub Actions workflows (see `.github/workflows/`):

- `daily-rundown.yml` 
  Once a day (`30 16 * * *`), sends every registered chat its
  configured alerts. Read-only against state, so it only needs the default
  (read-only) `GITHUB_TOKEN` permissions.
- `poll-commands.yml`
  Every five minutes, handles all commands and registers new
  chats. The only workflow that writes `state_telegram.json`, committing and pushing it
  to the separate state repo using the `STATE_REPO_TOKEN` secret.

Note GitHub disables scheduled workflows in a repo after 60 days with no commits (not
runs). If notifications silently stop, check whether they've been auto-disabled in the
Actions tab.

## Telegram commands

Sent as a message in any chat the bot is in:

  | Message | Purpose |
| --- | --- |
| `/start` | Registers the chat (if new) and replies with this command list. |
| `/setregion C` | Switch this chat to a different DNO region. |
| `/setthreshold 25` | Prices at or below 25p/kWh count as "ok"; above that, "spike". |
| `/setmode all/alerts/both/off` | Which daily messages this chat receives: every slot, only plunge/spike alerts, both, or nothing. |
| `/today` | Send today's remaining slots right now. |
| `/tomorrow` | Send tomorrow's slots right now, or a "not published yet" reply if Octopus hasn't published them (before ~4pm UK). |

`/setregion`, `/setthreshold` and `/setmode` take effect within a few minutes (on GitHub Actions, the
command-polling job runs on a `*/5 * * * *` schedule). `/today` and `/tomorrow` reply on that same poll.

## Architecture

| Path | Purpose |
| --- | --- |
| `notifiers/telegram.py` | Formats slots and talks to the Telegram Bot API. Also sends messages and parses incoming commands across all chats. |
| `scripts/chat_state.py` | Loads/saves `state/state_telegram.json` (see more below).|
| `scripts/rate_windows.py` | Computes the UK-local-calendar UTC windows ("today remaining", "tomorrow") passed to `octopus_core.fetch_agile_rates`. |
| `scripts/telegram_alerts.py` | Sends every registered chat its configured alerts daily. Read-only against state. Run via GitHub Actions. |
| `scripts/poll_commands.py` | Polls continuously (every 5 mins on GitHub Actions) to register new chats and handle all commands, including `/today`/`/tomorrow`. The only job that writes state. |
| `scripts/setup_region.py` | One-time (or one-off update) interactive script that sets the default region seeded to newly self-registered chats. |
| `scripts/check_env.py` | Reports which required environment variables are set, without printing their actual values. |

Rate fetching/categorizing (`octopus_core`) lives in a separate repo,
[agile-octopus-core](https://github.com/lahatfield/agile-octopus-core), and is pulled in
as a regular dependency (see `pyproject.toml`).

### Configuration and state

- **`.env`** (gitignored, never committed) holds secrets and seed defaults for running locally.
  Copy `.env.example` to `.env` and fill in real values.
- **`state/state_default.json`** (tracked in git) holds the default DNO region
  (Distribution Network Operator) - Octopus's single-letter code (A–P) for your regional
  electricity distributor - seeded to any chat the moment it first messages the bot.
- **`state_telegram.json`** holds every registered chat's own region, threshold and mode,
  plus a single cursor tracking which Telegram messages have already been processed
  (Telegram's `getUpdates` cursor is bot-wide, not per-chat). Since it contains chat IDs,
  it's tracked in a separate private repo rather than this one - see
  [For Users](#for-users-running-on-github-actions) above. Locally it defaults to
  `state/state_telegram.json` in this repo (gitignored) unless `TELEGRAM_STATE_DIR` is set.

  Example json:
  ```json
  {
    "offset": 384437557,
    "chats": {
      "<chat_id>": {"region": "P", "threshold": 30.0, "mode": "both"}
    }
  }
  ```
  Only `scripts/poll_commands.py` ever writes this file. This project is intended for a
  handful of your own chats, not as a public multi-tenant service. Every chat_id
  committed here belongs to a chat you administer.

## For Developers: Installing and Running Locally

### 1. Install dependencies

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync --group dev
```

This creates `.venv` and installs everything pinned in `uv.lock` (runtime deps plus
`pytest`, for running tests).

### 2. Configure secrets

```sh
cp .env.example .env
```
Fill in `TELEGRAM_BOT_TOKEN` in `.env`. `REGION` and `THRESHOLD` are optional seed
defaults used the moment a new chat registers itself (see
[Configuration and state](#configuration-and-state) above).

Run `uv run python -m scripts.check_env` any time to confirm which required variables
are set, without ever printing their actual values.

### 3. Set the default region

```sh
uv run python -m scripts.setup_region
```

### 4. Run it

```sh
uv run python -m scripts.poll_commands     # registers chats, handles commands
uv run python -m scripts.telegram_alerts   # sends that day's alerts
```

## Running tests

```sh
uv run python -m pytest
```
