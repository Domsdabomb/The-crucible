"""
SMS Service — stub for InvoiceToSMS integration.

TODO: Replace the placeholder URL and add real API credentials via environment
      variables (INVOICETOSMS_API_KEY) before going to production.
      Provider endpoint: https://api.invoicetosms.com/v1/send  (placeholder URL)

Every attempt — successful or failed — is logged to the sms_log table so there
is a full audit trail for customer communications.
"""

import logging
from datetime import datetime, timezone

# urllib.request is stdlib; swap for requests/httpx once added to requirements.
import urllib.request
import urllib.error
import json
import os

from flask import current_app

log = logging.getLogger(__name__)

# TODO: replace with real provider URL once API key is obtained
_PROVIDER_URL = "https://api.invoicetosms.com/v1/send"


def send_sms(phone: str, message: str, job_id: int | None = None,
             customer_id: int | None = None) -> dict:
    """
    Send an SMS and log the attempt to sms_log.

    Args:
        phone:       Recipient phone in E.164 format (e.g. +12505550100).
        message:     Message body (plain text, ≤ 160 chars for single segment).
        job_id:      Associated repair job id (may be None for non-job messages).
        customer_id: Associated customer id.

    Returns:
        dict with keys: success (bool), provider_message_id (str|None),
                        error_message (str|None), sms_log_id (int).
    """
    from app.db import get_db  # local import avoids circular imports at module load

    api_key = os.environ.get("INVOICETOSMS_API_KEY", "")

    payload = json.dumps({
        "to":      phone,
        "message": message,
        "from":    os.environ.get("SMS_SENDER_ID", "TheCrucible"),
    }).encode("utf-8")

    provider_message_id: str | None = None
    error_message: str | None = None
    status = "queued"

    # ── HTTP stub ──────────────────────────────────────────────────────────
    # TODO: add real auth header (Authorization: Bearer <api_key>) and handle
    #       provider-specific response shape once the real API is confirmed.
    try:
        req = urllib.request.Request(
            _PROVIDER_URL,
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            provider_message_id = str(body.get("message_id", ""))
            status = "sent"
            log.info("SMS sent to %s, provider id=%s", phone, provider_message_id)

    except urllib.error.HTTPError as exc:
        error_message = f"HTTP {exc.code}: {exc.reason}"
        status = "failed"
        log.error("SMS HTTPError to %s: %s", phone, error_message)

    except urllib.error.URLError as exc:
        error_message = f"URLError: {exc.reason}"
        status = "failed"
        log.error("SMS URLError to %s: %s", phone, error_message)

    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        status = "failed"
        log.error("SMS unexpected error to %s: %s", phone, error_message)

    # ── Always log to sms_log ──────────────────────────────────────────────
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO sms_log
            (job_id, customer_id, message_body, status,
             provider_message_id, error_message, sent_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            customer_id,
            message,
            status,
            provider_message_id,
            error_message,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        ),
    )
    db.commit()

    return {
        "success":             status == "sent",
        "provider_message_id": provider_message_id,
        "error_message":       error_message,
        "sms_log_id":          cursor.lastrowid,
    }


def sms_intake(phone: str, customer_name: str, job_id: int,
               customer_id: int) -> dict:
    """Convenience wrapper: send the standard intake confirmation."""
    msg = (
        f"Hi {customer_name}, your device has been received at The Crucible "
        f"(Job #{job_id}). We'll update you as work progresses. "
        f"Reply STOP to opt out."
    )
    return send_sms(phone, msg, job_id=job_id, customer_id=customer_id)


def sms_ready(phone: str, customer_name: str, job_id: int,
              customer_id: int) -> dict:
    """Convenience wrapper: notify customer their device is ready for pickup."""
    msg = (
        f"Hi {customer_name}, great news! Your device is ready for pickup "
        f"at The Crucible (Job #{job_id}). See you soon!"
    )
    return send_sms(phone, msg, job_id=job_id, customer_id=customer_id)
