"""Clay OAuth (PKCE) authentication for MCP access."""

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
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key

load_dotenv()

AUTH_SERVER = "https://api.clay.com"
AUTHORIZE_URL = "https://app.clay.com/oauth/authorize"
TOKEN_URL = f"{AUTH_SERVER}/oauth/token"
REGISTER_URL = f"{AUTH_SERVER}/oauth/register"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPE = "mcp"
ENV_PATH = Path(__file__).parent / ".env"
TOKEN_PATH = Path(__file__).parent / ".clay_tokens.json"
CLIENT_PATH = Path(__file__).parent / ".clay_oauth_client.json"
REFRESH_BUFFER_SECONDS = 300


class ClayAuthError(RuntimeError):
    pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def get_or_register_client() -> str:
    cached = _load_json(CLIENT_PATH)
    client_id = cached.get("client_id")
    if client_id:
        return str(client_id)

    registration = _http_json(
        "POST",
        REGISTER_URL,
        {
            "client_name": "clay-outbound",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    client_id = registration["client_id"]
    _save_json(CLIENT_PATH, {"client_id": client_id})
    return str(client_id)


def _exchange_code(client_id: str, code: str, verifier: str) -> dict[str, Any]:
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _refresh_token(client_id: str, refresh_token: str) -> dict[str, Any]:
    form = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def store_tokens(
    token_payload: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> str:
    merged = {**(existing or _load_json(TOKEN_PATH)), **token_payload}
    now = datetime.now(timezone.utc)
    merged["obtained_at"] = now.isoformat()
    expires_in = int(merged.get("expires_in", 3600))
    merged["expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    _save_json(TOKEN_PATH, merged)
    access_token = merged["access_token"]
    if ENV_PATH.exists():
        set_key(str(ENV_PATH), "CLAY_ACCESS_TOKEN", access_token)
    os.environ["CLAY_ACCESS_TOKEN"] = access_token
    return access_token


def load_token_bundle() -> dict[str, Any]:
    if TOKEN_PATH.exists():
        return _load_json(TOKEN_PATH)

    env_token = os.getenv("CLAY_ACCESS_TOKEN")
    if env_token:
        return {"access_token": env_token}
    return {}


def is_token_expired(token_bundle: dict[str, Any]) -> bool:
    expires_at_str = token_bundle.get("expires_at")
    if not expires_at_str:
        return True

    expires_at = datetime.fromisoformat(str(expires_at_str))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    buffer = timedelta(seconds=REFRESH_BUFFER_SECONDS)
    return datetime.now(timezone.utc) >= (expires_at - buffer)


def load_access_token() -> str | None:
    bundle = load_token_bundle()
    access_token = bundle.get("access_token")
    if access_token:
        return str(access_token)
    return None


def refresh_access_token() -> str:
    bundle = load_token_bundle()
    refresh = bundle.get("refresh_token")
    if not refresh:
        raise ClayAuthError("No refresh token available. Run: python clay_auth.py")

    client_id = get_or_register_client()
    refreshed = _refresh_token(client_id, str(refresh))
    return store_tokens(refreshed, existing=bundle)


def ensure_access_token(interactive: bool = True) -> str:
    bundle = load_token_bundle()
    access_token = bundle.get("access_token")

    if access_token and not is_token_expired(bundle):
        return str(access_token)

    if bundle.get("refresh_token"):
        try:
            return refresh_access_token()
        except Exception:
            pass

    if not interactive:
        raise ClayAuthError(
            "Clay OAuth token missing or expired. Run: python clay_auth.py"
        )

    return login()


def login() -> str:
    client_id = get_or_register_client()
    verifier, challenge = _pkce_pair()
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
                b"<html><body><h1>Clay auth complete.</h1>"
                b"<p>You can close this tab and return to the terminal.</p></body></html>"
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 8765), CallbackHandler)
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
        }
    )
    auth_url = f"{AUTHORIZE_URL}?{params}"
    print("Opening browser for Clay OAuth login...")
    print(f"If browser does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    thread.join(timeout=180)
    server.server_close()

    if "code" not in auth_code:
        raise ClayAuthError("OAuth login timed out or was cancelled.")

    token_payload = _exchange_code(client_id, auth_code["code"], verifier)
    access_token = store_tokens(token_payload)
    print("Clay OAuth login successful.")
    return access_token


if __name__ == "__main__":
    login()
