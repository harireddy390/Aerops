"""Notification engine. Dashboard + log always work; email (Gmail SMTP) and
webhook adapters are best-effort. Failures are swallowed: notifications must
never break the incident loop."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Notification

log = get_logger("notify")


def email_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_pass and settings.mail_to)


def send_email(subject: str, text: str) -> bool:
    """Send via Gmail SMTP (STARTTLS, app password). Returns delivered or not."""
    if not email_configured():
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.mail_from or settings.smtp_user
        msg["To"] = settings.mail_to
        html = "<pre>" + text.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(f"<h3>{subject}</h3>{html}", "html"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        log.info(f"email failed (non-fatal): {type(exc).__name__}")
        return False


def notify(db: Session, title: str, body: str = "", *, incident_id=None) -> Notification:
    note = Notification(title=title, body=body, incident_id=incident_id,
                        channel="dashboard", delivered=True)
    db.add(note)
    db.flush()
    log.info(f"notify: {title} — {body[:200]}")
    webhook = os.environ.get("ALERT_WEBHOOK", "")
    if webhook:
        try:
            httpx.post(webhook, json={"content": f"**{title}**\n{body[:1500]}"}, timeout=5)
            db.add(Notification(title=title, body=body, incident_id=incident_id,
                                channel="webhook", delivered=True))
        except Exception as exc:
            log.info(f"webhook failed (non-fatal): {exc}")
            db.add(Notification(title=title, body=body, incident_id=incident_id,
                                channel="webhook", delivered=False))
    if email_configured():
        delivered = send_email(f"[AeroOps] {title}", body)
        db.add(Notification(title=title, body=body, incident_id=incident_id,
                            channel="email", delivered=delivered))
    return note
