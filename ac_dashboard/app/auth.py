"""Google sign-in for the Doors page.

Flow: /auth/login redirects to Google (OAuth 2.0 authorization code, scope
openid+email); /auth/callback exchanges the code, reads the verified email
from Google's userinfo endpoint, checks it against the allow-list and sets a
long-lived signed session cookie. Sessions are stateless (HMAC-signed, key
persisted on disk) so they survive add-on restarts and updates.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SESSION_COOKIE = "session"
STATE_COOKIE = "oauth_state"
STATE_MAX_AGE = 600  # seconds to complete the Google round-trip


def load_or_create_secret(path: str | Path) -> bytes:
    path = Path(path)
    if path.exists():
        secret = path.read_bytes()
        if len(secret) >= 32:
            return secret
    secret = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secret)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionSigner:
    """HMAC-SHA256 signed, expiring JSON tokens."""

    def __init__(self, secret: bytes):
        self._secret = secret

    def _sig(self, body: str) -> str:
        return _b64(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())

    def sign(self, payload: dict, max_age: int, now: float | None = None) -> str:
        exp = int((now if now is not None else time.time()) + max_age)
        body = _b64(json.dumps({**payload, "exp": exp}, separators=(",", ":")).encode())
        return f"{body}.{self._sig(body)}"

    def verify(self, token: str | None) -> dict | None:
        if not token or "." not in token:
            return None
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(self._sig(body), sig):
            return None
        try:
            payload = json.loads(_unb64(body))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
            return None
        payload.pop("exp", None)
        return payload


def safe_next_path(value: str | None) -> str:
    """Only allow same-origin absolute paths as post-login destinations."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


class Auth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        allowed_emails: list[str],
        signer: SessionSigner,
        session_days: int = 365,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.allowed = {e.strip().lower() for e in allowed_emails if e.strip()}
        self.signer = signer
        self.session_max_age = session_days * 86400
        self._http = httpx.AsyncClient(timeout=15.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def is_allowed(self, email: str) -> bool:
        return email.strip().lower() in self.allowed

    def auth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "prompt": "select_account",
            "access_type": "online",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def fetch_email(self, code: str, redirect_uri: str) -> str:
        """Exchange the code and return the user's verified, normalised email.

        Raises ValueError on any failure (caller maps it to an HTTP error)."""
        try:
            token_resp = await self._http.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise ValueError("Google returned no access token")
            info_resp = await self._http.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info_resp.raise_for_status()
            info = info_resp.json()
        except httpx.HTTPError as exc:
            raise ValueError(f"Google sign-in failed: {exc}") from exc
        email = (info.get("email") or "").strip().lower()
        if not email or not info.get("email_verified"):
            raise ValueError("Google account email is not verified")
        return email

    # -- session tokens
    def new_state(self) -> str:
        return secrets.token_urlsafe(24)

    def state_token(self, state: str, next_path: str) -> str:
        return self.signer.sign({"state": state, "next": next_path}, STATE_MAX_AGE)

    def session_token(self, email: str) -> str:
        return self.signer.sign({"email": email}, self.session_max_age)

    def session_email(self, token: str | None) -> str | None:
        payload = self.signer.verify(token)
        return payload.get("email") if payload else None
