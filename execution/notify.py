"""
Trade notifications via SMTP email — free.

Sends a short message when the live system trades. The recipient (NOTIFY_TO) can
be either a normal email address OR a carrier **email-to-SMS gateway** address,
which delivers as a regular text at no cost beyond your normal text plan, e.g.:
    Verizon : 5551234567@vtext.com
    AT&T    : 5551234567@txt.att.net
    T-Mobile: 5551234567@tmomail.net
No paid service (Twilio etc.) is used.

All config comes from environment variables (set as GitHub Actions secrets):
    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 587),
    SMTP_USER, SMTP_PASSWORD (a Gmail *app password*), NOTIFY_TO

If SMTP isn't configured the functions no-op — notifications must never break a
trading run.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("rhdm")


def _cfg() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "to": os.getenv("NOTIFY_TO", ""),
    }


def send(subject: str, body: str, to: str | None = None, html: str | None = None) -> bool:
    """
    Send one email. `to` overrides NOTIFY_TO (e.g. a real inbox for HTML
    reports vs. the SMS gateway for trade alerts). `html` adds an HTML
    alternative. No-ops (returns False) if SMTP isn't configured.
    """
    c = _cfg()
    recipient = to or c["to"]
    if not (c["user"] and c["password"] and recipient):
        log.info("Notifications not configured (SMTP_USER/PASSWORD/recipient) — skipping.")
        return False
    msg = EmailMessage()
    msg["From"] = c["user"]
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(c["host"], c["port"], timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(c["user"], c["password"])
            s.send_message(msg)
        log.info("Notification sent to %s", recipient)
        return True
    except Exception as e:  # never let a notification failure crash trading
        log.warning("Notification failed: %s", e)
        return False


def notify_trades(plans, equity: float) -> None:
    """Text/email the full list of orders just submitted (largest first)."""
    if not plans:
        return
    lines = [f"{p.side.upper()} {p.symbol} ${p.notional:,.0f} ({p.reason})"
             for p in sorted(plans, key=lambda x: -x.notional)]
    body = (f"Alpaca paper rebalance: {len(plans)} order(s), equity ${equity:,.0f}\n"
            + "\n".join(lines))
    send(f"Trade alert: {len(plans)} order(s)", body)


def notify_killswitch(equity: float, drawdown: float) -> None:
    send("KILL SWITCH tripped — flattened to cash",
         f"Drawdown {drawdown:.1%} breached the limit. Book flattened. "
         f"Equity ${equity:,.0f}.")
