# Webhook Templates

Reference documentation and implementation templates for Aegis `user.verified` webhook integration. This enables tenant sites to automatically provision users when they complete email verification on Aegis.

## Webhook Contract

### Trigger

The `user.verified` event fires when a user clicks the email verification link and Aegis marks them as verified.

### HTTP Request

**Method**: `POST` to the tenant's configured `webhook_url`

**Payload** (compact JSON, no extra whitespace):

```json
{"event_type":"user.verified","site_id":1,"user_id":42,"email":"user@example.com","aegis_role":"user","timestamp":1700000000}
```

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | Always `"user.verified"` for this event |
| `site_id` | integer | The Aegis site ID |
| `user_id` | integer | The Aegis user ID |
| `email` | string | The user's email address |
| `aegis_role` | string | The user's Aegis role (`"user"` or `"admin"`) |
| `timestamp` | integer | Unix timestamp when the event occurred |

### Headers

| Header | Value | Description |
|--------|-------|-------------|
| `Content-Type` | `application/json` | |
| `X-Aegis-Signature` | `sha256=<hmac_hex_digest>` | HMAC-SHA256 signature for verification |
| `X-Aegis-Event` | `user.verified` | Event type for routing |
| `X-Aegis-Timestamp` | `<unix_timestamp>` | Signing timestamp (string) |

### Signing Algorithm

Aegis signs webhooks with HMAC-SHA256 over the string `"{timestamp}.{compact_json_body}"` using the site's `webhook_secret`:

```python
message = f"{timestamp}.{payload_json}"
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
# Sent as: X-Aegis-Signature: sha256={signature}
```

The payload JSON uses compact separators (`(',', ':')`), no extra whitespace.

### Expected Response

Any `2xx` status code is treated as success. The response body is logged but not parsed by Aegis.

### Timeout and Retries

- **Timeout**: 5 seconds
- **Retries**: None — failed deliveries are logged to the `webhook_events` table on the Aegis side but not retried

## Signature Verification

To verify an incoming webhook:

1. Extract `X-Aegis-Signature` and `X-Aegis-Timestamp` headers
2. Recompute the HMAC-SHA256 over `"{X-Aegis-Timestamp}.{raw_request_body}"` using the shared secret
3. Compare the computed digest with the received digest using constant-time comparison
4. **Replay protection**: Reject if `abs(current_time - timestamp) > 300` seconds

### Python (byteforge-aegis-client)

The `byteforge-aegis-client-python` package exports a ready-made verifier:

```python
from byteforge_aegis_client import verify_webhook_signature

is_valid = verify_webhook_signature(
    secret=webhook_secret,           # str: the site's webhook secret
    signature_header=signature,      # str: value of X-Aegis-Signature header
    timestamp=timestamp,             # str: value of X-Aegis-Timestamp header
    body=raw_body,                   # str: raw request body
    tolerance_seconds=300,           # int: max age in seconds (default 300)
)
```

### TypeScript / Node.js (manual)

No TypeScript client package exists yet. Use `crypto.createHmac` directly:

```typescript
import crypto from 'crypto';

function verifyWebhookSignature(
  secret: string,
  signatureHeader: string,
  timestamp: string,
  body: string,
  toleranceSeconds: number = 300
): boolean {
  if (!signatureHeader || !signatureHeader.startsWith('sha256=')) {
    return false;
  }

  const receivedDigest = signatureHeader.slice(7);

  // Check timestamp freshness
  if (toleranceSeconds > 0) {
    const webhookTime = parseInt(timestamp, 10);
    if (isNaN(webhookTime)) return false;
    const now = Math.floor(Date.now() / 1000);
    if (Math.abs(now - webhookTime) > toleranceSeconds) return false;
  }

  // Compute expected signature
  const message = `${timestamp}.${body}`;
  const expectedDigest = crypto
    .createHmac('sha256', secret)
    .update(message)
    .digest('hex');

  return crypto.timingSafeEqual(
    Buffer.from(expectedDigest),
    Buffer.from(receivedDigest)
  );
}
```

## Provisioning Pattern (Backend-Agnostic)

When handling a `user.verified` webhook, use this idempotent 3-branch pattern:

1. **User with this Aegis ID already exists** — Return success, no-op. This makes the handler safe to call multiple times for the same event.

2. **User with this email exists but no Aegis ID** — Link the `aegis_id` to the existing record, return success. This handles cases where the user was created before Aegis integration was added.

3. **New user** — Create a new record with the email, a name derived from the email prefix, any generated credentials (API keys, etc.), and the `aegis_id`. Return success.

The exact database schema, ORM, and provisioning logic are project-specific. The skill provides the pattern, not the implementation.

## Reference: Flask Implementation (NoteForge)

This is the complete NoteForge webhook handler as a concrete example of the provisioning pattern.

### Blueprint (`app/blueprints/aegis_webhook.py`)

```python
"""
Aegis Webhook endpoint for user provisioning.

Handles user.verified events from ByteForge Aegis to automatically
create NoteForge user accounts when users complete email verification.
"""

import logging
import os
import secrets
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from byteforge_aegis_client import verify_webhook_signature
from noteforge_models import User
from .aegis_webhook_schemas import AegisWebhookResponseSchema, AegisWebhookErrorSchema
from ..common import service_manager

logger = logging.getLogger(__name__)

blp = Blueprint(
    'aegis_webhook',
    __name__,
    url_prefix='/api/webhooks',
    description='Aegis Webhook API for user provisioning'
)


@blp.route('/aegis')
class AegisWebhookResource(MethodView):
    @blp.response(200, AegisWebhookResponseSchema)
    @blp.alt_response(400, schema=AegisWebhookErrorSchema)
    @blp.alt_response(401, schema=AegisWebhookErrorSchema)
    @blp.alt_response(500, schema=AegisWebhookErrorSchema)
    def post(self):
        """
        Handle Aegis webhook events for user provisioning.

        Processes user.verified events to create or link NoteForge users.
        Idempotent: safe to call multiple times for the same user.
        """
        webhook_secret = os.environ.get('AEGIS_WEBHOOK_SECRET')
        if not webhook_secret:
            logger.error("AEGIS_WEBHOOK_SECRET not configured")
            abort(500, message="Webhook secret not configured")

        # Verify signature
        signature = request.headers.get('X-Aegis-Signature', '')
        timestamp = request.headers.get('X-Aegis-Timestamp', '')
        body = request.get_data(as_text=True)

        if not verify_webhook_signature(webhook_secret, signature, timestamp, body):
            logger.warning("Invalid Aegis webhook signature")
            abort(401, message="Invalid signature")

        # Check event type
        event_type = request.headers.get('X-Aegis-Event', '')
        if event_type != 'user.verified':
            return {
                'received': True,
                'message': f'Event type {event_type} not processed',
            }

        # Parse payload
        payload = request.get_json()
        if not payload:
            abort(400, message="Invalid JSON payload")

        aegis_user_id = payload.get('user_id')
        email = payload.get('email')

        if not aegis_user_id or not email:
            abort(400, message="Missing required fields: user_id, email")

        logger.info(f"Processing user.verified event for {email} (Aegis ID: {aegis_user_id})")

        db = service_manager.get_database()

        # Branch 1: User with this Aegis ID already exists (idempotent)
        existing_user = db.get_user_by_aegis_id(aegis_user_id)
        if existing_user:
            logger.info(f"User already provisioned: {existing_user.email} (ID: {existing_user.id})")
            return {
                'received': True,
                'message': f'User already provisioned',
                'user_id': existing_user.id,
            }

        # Branch 2: User with this email exists but no Aegis ID (auto-link)
        existing_by_email = db.get_user_by_email(email)
        if existing_by_email:
            logger.info(f"Linking existing user {email} (ID: {existing_by_email.id}) to Aegis ID {aegis_user_id}")
            updated_user = db.update_user_aegis_id(existing_by_email.id, aegis_user_id)
            return {
                'received': True,
                'message': f'Existing user linked to Aegis',
                'user_id': updated_user.id,
            }

        # Branch 3: Create new user
        name = email.split('@')[0]
        api_key = secrets.token_hex(32)

        new_user = User(
            email=email,
            name=name,
            api_key=api_key,
            aegis_id=aegis_user_id,
        )

        created_user = db.create_user(new_user)
        if not created_user:
            logger.error(f"Failed to create user for {email}")
            abort(500, message="Failed to create user")

        logger.info(f"Provisioned new user: {email} (ID: {created_user.id}, Aegis ID: {aegis_user_id})")
        return {
            'received': True,
            'message': f'User provisioned',
            'user_id': created_user.id,
        }
```

### Response Schemas (`app/blueprints/aegis_webhook_schemas.py`)

```python
from marshmallow import Schema, fields


class AegisWebhookResponseSchema(Schema):
    """Response schema for successful Aegis webhook processing."""
    received = fields.Boolean(required=True, metadata={'description': 'Whether the event was received'})
    message = fields.String(required=True, metadata={'description': 'Status message'})
    user_id = fields.Integer(load_default=None, metadata={'description': 'Tenant user ID if provisioned'})


class AegisWebhookErrorSchema(Schema):
    """Response schema for Aegis webhook errors."""
    error = fields.String(required=True, metadata={'description': 'Error message'})
```

## Reference: Next.js API Route (Skeleton)

A minimal starting point for handling Aegis webhooks in a Next.js API route. This is **not a complete implementation** — you will need to add your own database logic and user model.

### `app/api/webhooks/aegis/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';

const WEBHOOK_SECRET = process.env.AEGIS_WEBHOOK_SECRET || '';

function verifySignature(secret: string, signatureHeader: string, timestamp: string, body: string): boolean {
  if (!signatureHeader || !signatureHeader.startsWith('sha256=')) return false;

  const receivedDigest = signatureHeader.slice(7);
  const now = Math.floor(Date.now() / 1000);
  const webhookTime = parseInt(timestamp, 10);

  if (isNaN(webhookTime) || Math.abs(now - webhookTime) > 300) return false;

  const message = `${timestamp}.${body}`;
  const expectedDigest = crypto.createHmac('sha256', secret).update(message).digest('hex');

  return crypto.timingSafeEqual(Buffer.from(expectedDigest), Buffer.from(receivedDigest));
}

export async function POST(request: NextRequest) {
  if (!WEBHOOK_SECRET) {
    return NextResponse.json({ error: 'Webhook secret not configured' }, { status: 500 });
  }

  const signature = request.headers.get('X-Aegis-Signature') || '';
  const timestamp = request.headers.get('X-Aegis-Timestamp') || '';
  const body = await request.text();

  if (!verifySignature(WEBHOOK_SECRET, signature, timestamp, body)) {
    return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
  }

  const eventType = request.headers.get('X-Aegis-Event') || '';
  if (eventType !== 'user.verified') {
    return NextResponse.json({ received: true, message: `Event ${eventType} not processed` });
  }

  const payload = JSON.parse(body);
  const { user_id: aegisUserId, email } = payload;

  if (!aegisUserId || !email) {
    return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
  }

  // TODO: Implement the 3-branch provisioning pattern:
  // 1. Check if user with this Aegis ID exists → return success (no-op)
  // 2. Check if user with this email exists → link aegis_id, return success
  // 3. Create new user with email, derived name, credentials → return success

  return NextResponse.json({ received: true, message: 'User provisioned' });
}
```

**Note**: This route uses Node.js `crypto` and must NOT run in Edge Runtime. Ensure your Next.js config does not force this route to the edge.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AEGIS_WEBHOOK_SECRET` | Shared secret for HMAC signature verification. Provided by Aegis when configuring the site's webhook URL. |

Add to `.env.example`:
```
AEGIS_WEBHOOK_SECRET=            # Webhook secret from Aegis admin (for user provisioning)
```

## Aegis Admin Setup

The webhook URL and secret are configured via the Aegis admin API:

- **Create site**: `POST /api/sites` with `webhook_url` field
- **Update site**: `PUT /api/sites/<id>` with `webhook_url` field

When a `webhook_url` is provided, Aegis auto-generates a `webhook_secret` (64-character hex string) and returns it in the response. Store this secret in your backend's environment as `AEGIS_WEBHOOK_SECRET`.

If you need to rotate the secret, update the site's `webhook_url` (even to the same value) — Aegis will generate a new secret.
