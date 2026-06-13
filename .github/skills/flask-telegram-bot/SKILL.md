---
name: flask-telegram-bot
description: Add a Telegram bot webhook endpoint to a Flask service using the byteforge-telegram library. Use when wiring up a Flask app to receive Telegram bot updates, validating the Telegram secret token, routing commands, and sending notifications back through the Bot API.
---

# Flask + Telegram Bot Webhook

This skill wires Telegram bot support into a Flask service using the public `byteforge-telegram` library. The result is a Flask server with:

- A `/health` endpoint for orchestration/monitoring probes
- A `/telegram/webhook` endpoint that validates the Telegram secret token, routes `/commands` to handler methods, and replies via `TelegramResponse`
- An outbound notification helper for sending messages to chat IDs from anywhere in the app
- Instructions for registering the webhook with Telegram using the `setup-telegram-webhook` CLI bundled in `byteforge-telegram`

## When to Use This Skill

Use this skill when:
- You have (or are building) a Flask app that needs to receive Telegram bot updates
- You want webhook delivery (not long-polling) for production reliability
- You need a structured pattern for routing slash commands to handler methods
- You want to send outbound Telegram notifications from other parts of the app
- You want Telegram's `secret_token` header validated on every webhook request

This skill **does not**:
- Dockerize the app (use `flask-docker-deployment`)
- Set up logging (use `byteforge-loki-logging`)
- Configure metrics (use `byteforge-prometheus-metrics`)
- Set up a database (use `postgres-setup`)
- Build OpenAPI docs (use `flask-smorest-api`)

It composes cleanly with all of those.

## What This Skill Creates

1. **`{app_name}_server.py`** (or edits the existing Flask entrypoint) — adds `/telegram/webhook` route with secret-token validation, plus a `/health` route if missing
2. **`src/telegram_webhook_handler.py`** — `TelegramWebhookHandler` class that routes slash commands to methods and returns `TelegramResponse` objects
3. **`src/telegram_notifier.py`** — Thin wrapper around `TelegramBotController` for sending outbound notifications from anywhere in the app
4. **`requirements.txt` updates** — adds `byteforge-telegram`, `flask`, `gunicorn`
5. **`example.env` updates** — adds bot token, webhook secret, optional admin chat ID
6. **Webhook registration instructions** — how to run `setup-telegram-webhook --url https://...` once the app is deployed

## Why the secret token matters

Telegram's `setWebhook` API accepts a `secret_token`. When set, every webhook delivery includes that token in the `X-Telegram-Bot-Api-Secret-Token` header. Without this check, **anyone on the internet who guesses your webhook URL can POST fake updates** and trigger your bot's command handlers. The validation must use `hmac.compare_digest` to avoid timing attacks.

## Step 1: Gather Project Information

**IMPORTANT**: Before making changes, ask the user these questions:

1. **"What is the name of your Flask server file?"** (e.g., `app.py`, `my_server.py`)
   - If a Flask app entrypoint already exists, the skill edits it. Otherwise it creates `{app_name}_server.py`.

2. **"What is your application tag/name?"** (e.g., `my-bot`, `support-bot`)
   - Used to namespace env vars: `{APP_TAG}_TELEGRAM_BOT_TOKEN`, `{APP_TAG}_TELEGRAM_WEBHOOK_SECRET`
   - Convert to UPPER_SNAKE_CASE for env vars (e.g., `my-bot` → `MY_BOT`)

3. **"What slash commands should the bot support?"** (e.g., `/start`, `/help`, `/register`)
   - Default to `/start` and `/help` if unspecified
   - For each command, ask what it should do

4. **"What port should the Flask server use?"**
   - Pick a port above 5000 (e.g., 5678, 6100, 7200) — avoid well-known ports

5. **"Do you need a database connection in the handler?"** (yes/no)
   - If yes, the handler accepts a database object in its constructor (caller's responsibility to wire up)
   - If no, the handler is standalone

## Step 2: Update requirements.txt

Add these lines (or merge with existing entries):

```txt
flask
gunicorn
byteforge-telegram
```

`byteforge-telegram` is a public package on PyPI — no `CR_PAT` token needed.

Install:

```bash
source bin/activate && pip install -r requirements.txt
```

## Step 3: Create the Webhook Handler

Create `src/telegram_webhook_handler.py`:

```python
"""
Telegram webhook handler for {app_tag}.

Processes incoming Telegram updates and routes slash commands to handler methods.
"""

import logging
from typing import Dict, Any, Optional

from byteforge_telegram import TelegramResponse

logger = logging.getLogger(__name__)


class TelegramWebhookHandler:
    """Routes Telegram webhook updates to command handlers."""

    def process_update(self, update: Dict[str, Any]) -> Optional[TelegramResponse]:
        """
        Process an incoming Telegram update.

        Args:
            update: Raw Telegram update dictionary (from request.get_json())

        Returns:
            TelegramResponse to send back as the webhook response body,
            or None if no response should be sent.
        """
        message = update.get('message')
        if not message:
            logger.debug("Update has no message, ignoring")
            return None

        text = message.get('text', '')
        chat_id = message.get('chat', {}).get('id')
        user = message.get('from', {})
        username = user.get('username', 'unknown')

        if not text or not chat_id:
            logger.debug("Message missing text or chat_id, ignoring")
            return None

        logger.info(f"Received message from {username} (chat_id: {chat_id}): {text}")

        # Route slash commands
        if text.startswith('/start'):
            return self._handle_start(chat_id, username)
        elif text.startswith('/help'):
            return self._handle_help(chat_id)
        # Add additional command handlers here:
        # elif text.startswith('/register'):
        #     return self._handle_register(chat_id, username, text)
        else:
            return self._handle_unknown_command(chat_id)

    def _handle_start(self, chat_id: int, username: str) -> TelegramResponse:
        """Handle /start command."""
        logger.info(f"User {username} started bot (chat_id: {chat_id})")

        message = (
            "👋 <b>Welcome!</b>\n\n"
            "Use /help to see what I can do."
        )
        return TelegramResponse(
            method='sendMessage',
            chat_id=chat_id,
            text=message,
        )

    def _handle_help(self, chat_id: int) -> TelegramResponse:
        """Handle /help command."""
        message = (
            "<b>Available commands:</b>\n"
            "/start - Get started\n"
            "/help - Show this message"
        )
        return TelegramResponse(
            method='sendMessage',
            chat_id=chat_id,
            text=message,
        )

    def _handle_unknown_command(self, chat_id: int) -> TelegramResponse:
        """Handle unknown commands."""
        return TelegramResponse(
            method='sendMessage',
            chat_id=chat_id,
            text="❓ Unknown command. Use /help for a list of commands.",
        )
```

### If the handler needs a database

Pass it through the constructor — the Flask entrypoint constructs it once at startup:

```python
class TelegramWebhookHandler:
    def __init__(self, database: YourDatabase) -> None:
        self.db = database
```

### Command handler conventions

Each command handler should:
- Be a method named `_handle_{command}` taking `(self, chat_id, username, text)` (drop unused params)
- Return a `TelegramResponse` (or `None` if no reply)
- Log entry with `username` and `chat_id` for traceability
- Validate inputs before touching shared state — never trust webhook payloads
- Use `parse_mode='HTML'` (the default) and HTML escape any user-supplied substrings before interpolating

## Step 4: Create the Outbound Notifier

Create `src/telegram_notifier.py`:

```python
"""
Outbound Telegram notifications via byteforge-telegram.

Wraps TelegramBotController to provide a single import point for sending
notifications to users from anywhere in the app.
"""

import logging
import os
from typing import Optional

from byteforge_telegram import TelegramBotController

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends outbound Telegram notifications."""

    def __init__(self, bot_token: Optional[str] = None) -> None:
        """
        Initialize the notifier.

        Args:
            bot_token: Telegram bot token. If None, reads from
                {APP_TAG}_TELEGRAM_BOT_TOKEN env var.
        """
        token = bot_token or os.environ.get('{APP_TAG}_TELEGRAM_BOT_TOKEN')
        if not token:
            logger.warning(
                "Telegram bot token not configured; outbound notifications disabled"
            )
            self.bot: Optional[TelegramBotController] = None
        else:
            self.bot = TelegramBotController(token)

    def send_message(self, chat_id: str, text: str) -> bool:
        """
        Send a plain text message.

        Args:
            chat_id: Target Telegram chat ID (string)
            text: Message body (HTML formatting allowed by default)

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        if not self.bot:
            logger.debug(f"Skipping notification to {chat_id}: bot not configured")
            return False

        try:
            results = self.bot.send_message_sync(text=text, chat_ids=[chat_id])
            return bool(results.get(chat_id, False))
        except Exception as exc:
            logger.error(f"Failed to send Telegram message to {chat_id}: {exc}")
            return False
```

**CRITICAL Replacements:**
- `{APP_TAG}` → UPPER_SNAKE_CASE app tag (e.g., `MY_BOT`)

## Step 5: Wire the Webhook Route into the Flask App

Edit `{app_name}_server.py` (or create it if no Flask entrypoint exists):

```python
#!/usr/bin/env python3
"""
{app_tag} server — Flask app with Telegram webhook.
"""

import hmac
import logging
import os

from flask import Flask, jsonify, request

from src.telegram_webhook_handler import TelegramWebhookHandler

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024  # 1 MB cap on webhook bodies

PORT = int(os.environ.get('PORT', '{port}'))

telegram_handler = TelegramWebhookHandler()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for orchestration probes."""
    return jsonify({'status': 'healthy'}), 200


@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """
    Telegram webhook endpoint.

    Telegram POSTs updates here. The X-Telegram-Bot-Api-Secret-Token header
    is validated against {APP_TAG}_TELEGRAM_WEBHOOK_SECRET to reject forged
    requests.
    """
    secret = os.environ.get('{APP_TAG}_TELEGRAM_WEBHOOK_SECRET')
    if not secret:
        # Fail-closed: never accept unauthenticated webhook traffic, even in dev.
        # A forgotten env var in prod would otherwise silently expose every
        # handler to anyone who finds the URL.
        logger.warning(
            "{APP_TAG}_TELEGRAM_WEBHOOK_SECRET not set — rejecting webhook"
        )
        return jsonify({'status': 'error'}), 503

    request_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if not request_token or not hmac.compare_digest(request_token, secret):
        logger.warning("Webhook rejected: invalid or missing secret token")
        return jsonify({'status': 'error'}), 401

    try:
        update = request.get_json()
        if not update:
            logger.warning("Empty webhook update")
            return jsonify({'status': 'error', 'message': 'No update data'}), 400

        logger.debug(f"Received Telegram update: {update}")

        response = telegram_handler.process_update(update)
        if response:
            logger.info(f"Sending response to chat {response.chat_id}")
            return jsonify(response.to_dict()), 200

        return jsonify({'status': 'ok'}), 200

    except Exception as exc:
        logger.error(f"Error processing Telegram webhook: {exc}", exc_info=True)
        return jsonify({'status': 'error'}), 500


if __name__ == '__main__':
    logger.info(f"Starting {app_tag} server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT)
```

**CRITICAL Replacements:**
- `{app_tag}` → user-supplied app tag (e.g., `my-bot`)
- `{APP_TAG}` → UPPER_SNAKE_CASE app tag (e.g., `MY_BOT`)
- `{port}` → user-supplied port (e.g., `5678`)

### If the Flask entrypoint already exists

Do **not** rewrite it. Instead, edit it surgically:

1. Add `import hmac` and the `from flask import request` imports if missing
2. Construct `telegram_handler = TelegramWebhookHandler(...)` once at module scope
3. Add the `@app.route('/telegram/webhook', methods=['POST'])` route from the snippet above (the secret is read from the env var inside the handler — no module-level state needed)

Match the file's existing import order, indentation, and logging conventions.

## Step 6: Update example.env

Add (or merge with existing entries):

```bash
# ---------------------------------------------------------------------------
# Telegram bot
# ---------------------------------------------------------------------------

# Bot token from BotFather
{APP_TAG}_TELEGRAM_BOT_TOKEN=

# Webhook secret token for validating incoming requests.
# Generate with: openssl rand -hex 32
# Required when registering a webhook via setup-telegram-webhook --url
{APP_TAG}_TELEGRAM_WEBHOOK_SECRET=

# Optional: admin chat ID for outbound alerts
# {APP_TAG}_TELEGRAM_ADMIN_CHAT_ID=
```

## Step 7: Register the Webhook with Telegram

After deploying behind HTTPS (Telegram requires HTTPS for webhooks), register the webhook URL using the CLI bundled with `byteforge-telegram`. Pass the bot token explicitly via `--token` so there's no ambiguity about which env var the CLI reads:

```bash
source bin/activate

setup-telegram-webhook \
    --token "$MY_BOT_TELEGRAM_BOT_TOKEN" \
    --url https://your-domain.example.com/telegram/webhook
```

Replace `MY_BOT_TELEGRAM_BOT_TOKEN` with the env var name you chose in Step 1 (e.g., `SUPPORT_BOT_TELEGRAM_BOT_TOKEN`).

The webhook secret is read from `TELEGRAM_WEBHOOK_SECRET` (the CLI's expected env var) — alias your app-specific var for the call:

```bash
export TELEGRAM_WEBHOOK_SECRET="$MY_BOT_TELEGRAM_WEBHOOK_SECRET"

setup-telegram-webhook \
    --token "$MY_BOT_TELEGRAM_BOT_TOKEN" \
    --url https://your-domain.example.com/telegram/webhook
```

If your installed version of `byteforge-telegram` doesn't include the CLI, instantiate `WebhookManager` from a one-off Python script — see the byteforge-telegram README.

**Verify the registration:**

```bash
setup-telegram-webhook --token "$MY_BOT_TELEGRAM_BOT_TOKEN" --info
```

You should see your webhook URL listed and `pending_update_count: 0`.

**Delete the webhook** (useful when migrating environments or during debugging):

```bash
setup-telegram-webhook --token "$MY_BOT_TELEGRAM_BOT_TOKEN" --delete
```

## Step 8: Verify End-to-End

1. **Health check:**
   ```bash
   curl http://localhost:{port}/health
   # → {"status":"healthy"}
   ```

2. **Reject unauthenticated webhook calls** (expected 401):
   ```bash
   curl -X POST http://localhost:{port}/telegram/webhook \
        -H 'Content-Type: application/json' \
        -d '{"message":{"text":"/start","chat":{"id":1},"from":{"username":"x"}}}'
   # → {"status":"error"}  (HTTP 401 if secret env var is set, HTTP 503 if not)
   ```

3. **Accept properly authenticated webhook calls:**
   ```bash
   curl -X POST http://localhost:{port}/telegram/webhook \
        -H 'Content-Type: application/json' \
        -H "X-Telegram-Bot-Api-Secret-Token: $YOUR_WEBHOOK_SECRET" \
        -d '{"message":{"text":"/start","chat":{"id":1},"from":{"username":"x"}}}'
   # → {"method":"sendMessage","chat_id":1,"text":"👋 ...","parse_mode":"HTML"}
   ```

4. **Talk to the bot on Telegram:** send `/start` to the bot from any Telegram client. You should see the welcome message back, and a log line on the server.

## Security Notes

1. **The webhook is fail-closed: no secret = 503 on every request.** The route refuses traffic when `{APP_TAG}_TELEGRAM_WEBHOOK_SECRET` is unset, in every environment including local dev. Fail-open ("missing secret means accept everything") is too easy to ship to prod by accident — a forgotten env var would silently expose every command handler to the internet. If you need to test the route without a real Telegram registration, set the env var to any value and pass it in the `X-Telegram-Bot-Api-Secret-Token` header from curl.

2. **Use `hmac.compare_digest`, never `==`.** A naive comparison leaks timing information that lets an attacker recover the secret byte by byte.

3. **HTTPS is mandatory.** Telegram refuses to register HTTP webhooks. Terminate TLS at your reverse proxy (nginx, Cloudflare, etc.) and forward to the Flask app over the internal network.

4. **Validate every untrusted input.** Webhook payloads are user-controlled. HTML-escape any substring you echo back, and never interpolate raw text into shell commands, SQL, or filesystem paths.

5. **Rate-limit if exposed publicly.** Telegram retries failed deliveries — if a handler crashes, you may get hammered. A reverse-proxy rate limit (or a simple in-process token bucket) prevents one user from DoS'ing the bot.

6. **Don't log secrets.** Avoid logging the full update body at INFO in production — Telegram messages may contain sensitive content. Use DEBUG instead and keep DEBUG off in production.

## Reply Methods Beyond `sendMessage`

`TelegramResponse(method=...)` accepts any Bot API method. Common ones:

- `sendMessage` — text reply (default)
- `sendPhoto` — image reply (use with `photo` field)
- `editMessageText` — edit an existing message
- `answerCallbackQuery` — respond to inline keyboard callbacks

When using methods beyond `sendMessage`, you may need to attach extra fields to the response dict manually after `to_dict()`.

## Integration with Other Skills

### flask-docker-deployment
Dockerize the resulting server. The Flask entrypoint pattern from this skill matches what `flask-docker-deployment` expects (`{module}:app`).

### byteforge-loki-logging
Add structured logging — set up `configure_logging(application_tag='{app_tag}')` at the top of the server file. Use the same tag value here and there so log/metric correlation works.

### byteforge-prometheus-metrics
The Flask server is already a normal Flask app — the metrics skill adds `prometheus_flask_exporter` on top without conflict. Make sure the `/metrics` endpoint is whitelisted at your reverse proxy and **not** exposed publicly alongside `/telegram/webhook`.

### gatekeeper-nginx-setup
If you're using ByteForge Gatekeeper as the reverse proxy, the `/telegram/webhook` path should be exposed publicly (Telegram needs to reach it) but everything else (including `/health` and `/metrics`) should remain whitelisted or auth-gated. The webhook secret is your only public-facing authentication.

### postgres-setup
If the bot stores per-user state (registrations, chat IDs, etc.), pair this skill with `postgres-setup` and pass the database into the `TelegramWebhookHandler` constructor.

## Common Pitfalls

| Symptom | Likely cause |
|---|---|
| Webhook returns 401 for every request | `TELEGRAM_WEBHOOK_SECRET` env var differs between what Telegram has registered and what the server has loaded. Re-run `setup-telegram-webhook --url ...` with the matching secret. |
| Webhook returns 503 for every request, even with valid header | `{APP_TAG}_TELEGRAM_WEBHOOK_SECRET` env var is unset — the route fails closed when the secret is missing. Set the env var and restart. |
| Telegram's `getWebhookInfo` shows `last_error_message: SSL` | The server's TLS cert isn't trusted by Telegram. Use a public CA (Let's Encrypt) — Telegram won't trust private/self-signed CAs. |
| Bot never responds even though logs show the update arrived | The handler returned `None` (no response needed) but you expected a reply. Make sure `_handle_*` methods return a `TelegramResponse`. |
| Bot replies appear unformatted (raw `<b>` tags visible) | `parse_mode` was set to something other than `'HTML'`, or the receiving client doesn't render HTML — switch to `parse_mode='MarkdownV2'` if needed. |
| Webhook works in dev but Telegram's `getWebhookInfo` shows `pending_update_count` climbing in prod | The server is returning non-2xx responses. Check for unhandled exceptions in handlers — every code path must return a JSON response, including error cases. |
| `setup-telegram-webhook` not found after `pip install` | Activate the venv: `source bin/activate`. The script is installed into the venv's bin dir, not the system one. |

## Design Principles

1. **Webhook over polling** — webhooks scale better, latency is lower, and there's no idle traffic
2. **Secret-token validation by default** — every request authenticated, no exceptions
3. **Command routing via dispatch table** — each command is a single method, easy to test in isolation
4. **TelegramResponse as the return value** — type-safe, no manual dict construction in handlers
5. **Outbound notifier as a separate concern** — webhook handlers reply via the response; arbitrary code paths use `TelegramNotifier` to push
6. **No private dependencies** — `byteforge-telegram` is public on PyPI; this skill doesn't introduce any auth tokens beyond Telegram's own

## Report Back

After running the skill, report:
- The file(s) created or edited
- The env vars added to `example.env`
- The command the user should run to register the webhook (with the literal env var names filled in)
- Any pre-existing routes that conflict and how they were resolved
