"""SMTP email delivery with resume attachment (OAuth XOAUTH2 or password)."""

from __future__ import annotations

import base64
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

from paths import ENV_FILE, GMAIL_TOKENS
from resume import SENDER_EMAIL, SENDER_NAME, get_resume_path

load_dotenv(ENV_FILE)


class EmailSendError(RuntimeError):
    pass


def _use_oauth() -> bool:
    return GMAIL_TOKENS.exists() or bool(os.getenv("GMAIL_OAUTH_CLIENT_SECRET"))


def _authenticate(server: smtplib.SMTP, user: str) -> None:
    if _use_oauth():
        from gmail_oauth import GmailAuthError, ensure_access_token

        try:
            token = ensure_access_token(interactive=False)
        except GmailAuthError as exc:
            raise EmailSendError(str(exc)) from exc

        auth_string = f"user={user}\x01auth=Bearer {token}\x01\x01"
        code, response = server.docmd(
            "AUTH", "XOAUTH2 " + base64.b64encode(auth_string.encode()).decode()
        )
        if code != 235:
            raise EmailSendError(
                f"Gmail XOAUTH2 auth failed ({code}): {response.decode(errors='replace')}"
            )
        return

    password = os.getenv("SMTP_PASSWORD")
    if not password:
        raise EmailSendError(
            "No Gmail OAuth tokens and SMTP_PASSWORD is not set. "
            "Run: python gmail_oauth.py"
        )
    server.login(user, password)


def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    attach_resume: bool = True,
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(f"[DRY RUN] To: {to_email}")
        print(f"Subject: {subject}")
        print(body)
        print("---")
        return

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", SENDER_EMAIL)
    sender = os.getenv("SENDER_EMAIL", SENDER_EMAIL)

    message = MIMEMultipart()
    message["From"] = f"{SENDER_NAME} <{sender}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    if attach_resume:
        resume_path = get_resume_path()
        with resume_path.open("rb") as resume_file:
            attachment = MIMEApplication(resume_file.read(), _subtype="pdf")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=resume_path.name,
        )
        message.attach(attachment)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            _authenticate(server, user)
            server.sendmail(sender, [to_email], message.as_string())
    except smtplib.SMTPException as exc:
        raise EmailSendError(f"Failed to send email to {to_email}: {exc}") from exc
