import time

import pytest

from app.auth import Auth, SessionSigner, load_or_create_secret, safe_next_path

from tests.conftest import fake_google, make_auth


def test_secret_is_created_once_and_persisted(tmp_path):
    path = tmp_path / "secret"
    first = load_or_create_secret(path)
    assert len(first) >= 32
    assert load_or_create_secret(path) == first
    assert path.read_bytes() == first


def test_session_round_trip():
    signer = SessionSigner(b"k" * 32)
    token = signer.sign({"email": "martin@example.com"}, max_age=3600)
    assert signer.verify(token) == {"email": "martin@example.com"}


def test_tampered_token_is_rejected():
    signer = SessionSigner(b"k" * 32)
    token = signer.sign({"email": "martin@example.com"}, max_age=3600)
    body, sig = token.rsplit(".", 1)
    assert signer.verify(body + "x." + sig) is None
    assert signer.verify(body + "." + sig[:-2] + "zz") is None
    assert signer.verify("garbage") is None
    assert signer.verify("") is None


def test_token_signed_with_other_key_is_rejected():
    token = SessionSigner(b"a" * 32).sign({"email": "x"}, max_age=3600)
    assert SessionSigner(b"b" * 32).verify(token) is None


def test_expired_token_is_rejected():
    signer = SessionSigner(b"k" * 32)
    token = signer.sign({"email": "x"}, max_age=10, now=time.time() - 20)
    assert signer.verify(token) is None


def test_auth_url_points_at_google_with_state_and_redirect(tmp_path):
    auth = make_auth(tmp_path)
    url = auth.auth_url("https://home.example:8088/auth/callback", "state-xyz")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fhome.example%3A8088%2Fauth%2Fcallback" in url
    assert "state=state-xyz" in url
    assert "scope=openid+email" in url
    assert "response_type=code" in url


async def test_fetch_email_exchanges_code_then_reads_userinfo(tmp_path):
    transport, seen = fake_google(email="Martin@Example.com")
    auth = make_auth(tmp_path, transport)
    email = await auth.fetch_email("code-1", "https://home.example:8088/auth/callback")
    assert email == "martin@example.com"  # normalised
    assert seen["token_requests"] == [{
        "code": "code-1",
        "client_id": "cid",
        "client_secret": "csecret",
        "redirect_uri": "https://home.example:8088/auth/callback",
        "grant_type": "authorization_code",
    }]
    assert seen["userinfo_auth"] == ["Bearer at-123"]


async def test_fetch_email_rejects_unverified_email(tmp_path):
    transport, _ = fake_google(verified=False)
    auth = make_auth(tmp_path, transport)
    with pytest.raises(ValueError, match="verified"):
        await auth.fetch_email("code-1", "https://h/cb")


async def test_fetch_email_raises_on_token_error(tmp_path):
    transport, _ = fake_google(token_status=400)
    auth = make_auth(tmp_path, transport)
    with pytest.raises(ValueError):
        await auth.fetch_email("bad", "https://h/cb")


def test_is_allowed_is_case_insensitive(tmp_path):
    auth = make_auth(tmp_path, allowed=["Martin.E.Strom@gmail.com"])
    assert auth.is_allowed("martin.e.strom@gmail.com")
    assert not auth.is_allowed("mallory@gmail.com")


def test_safe_next_path_only_allows_local_paths():
    assert safe_next_path("/doors.html") == "/doors.html"
    assert safe_next_path("/doors.html?x=1") == "/doors.html?x=1"
    assert safe_next_path("https://evil.example/") == "/"
    assert safe_next_path("//evil.example/") == "/"
    assert safe_next_path(None) == "/"
    assert safe_next_path("doors.html") == "/"
