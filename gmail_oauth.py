"""Gmail OAuth (PKCE) for SMTP XOAUTH2 sending."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from dotenv import load_dotenv

from paths import ENV_FILE, GMAIL_TOKENS

load_dotenv(ENV_FILE)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://127.0.0.1:8766/callback"
SCOPE = "https://mail.google.com/"
TOKEN_PATH = GMAIL_TOKENS
REFRESH_BUFFER_SECONDS = 300


class GmailAuthError(RuntimeError):
    pass


def _client_config() -> tuple[str, str]:
    client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET")
    if not client_id:
        raise GmailAuthError("GMAIL_OAUTH_CLIENT_ID is not set in .env")
    if not client_secret:
        raise GmailAuthError(
            "GMAIL_OAUTH_CLIENT_SECRET is not set in .env. Find it in Google Cloud "
            "Console under APIs & Services -> Credentials -> your OAuth client."
        )
    return client_id, client_secret


def _load_tokens() -> dict[str, Any]:
    if not TOKEN_PATH.exists():
        return {}
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def _store_tokens(payload: dict[str, Any]) -> str:
    merged = {**_load_tokens(), **payload}
    now = datetime.now(timezone.utc)
    merged["obtained_at"] = now.isoformat()
    expires_in = int(merged.get("expires_in", 3600))
    merged["expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    TOKEN_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return str(merged["access_token"])


def _is_expired(bundle: dict[str, Any]) -> bool:
    expires_at_str = bundle.get("expires_at")
    if not expires_at_str:
        return True
    expires_at = datetime.fromisoformat(str(expires_at_str))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    buffer = timedelta(seconds=REFRESH_BUFFER_SECONDS)
    return datetime.now(timezone.utc) >= (expires_at - buffer)


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def refresh_access_token() -> str:
    bundle = _load_tokens()
    refresh = bundle.get("refresh_token")
    if not refresh:
        raise GmailAuthError("No Gmail refresh token. Run: python gmail_oauth.py")

    client_id, client_secret = _client_config()
    refreshed = _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": str(refresh),
        }
    )
    return _store_tokens(refreshed)


def ensure_access_token(interactive: bool = True) -> str:
    bundle = _load_tokens()
    if bundle.get("access_token") and not _is_expired(bundle):
        return str(bundle["access_token"])

    if bundle.get("refresh_token"):
        try:
            return refresh_access_token()
        except Exception:
            pass

    if not interactive:
        raise GmailAuthError(
            "Gmail OAuth token missing or expired. Run: python gmail_oauth.py"
        )
    return login()


def login() -> str:
    client_id, client_secret = _client_config()
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(16)
    auth_code: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid state")
                return
            code = params.get("code", [""])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return
            auth_code["code"] = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Gmail auth complete.</h1>"
                b"<p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 8766), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    auth_url = f"{AUTHORIZE_URL}?{params}"
    print("Opening browser for Gmail OAuth login...")
    print(f"If browser does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    thread.join(timeout=180)
    server.server_close()

    if "code" not in auth_code:
        raise GmailAuthError("OAuth login timed out or was cancelled.")

    token_payload = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": auth_code["code"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    )
    access_token = _store_tokens(token_payload)
    print("Gmail OAuth login successful.")
    return access_token


if __name__ == "__main__":
    login()
