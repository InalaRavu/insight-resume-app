"""Tests for the Entra/Easy Auth principal extraction."""
import base64
import json

import pytest

from src import auth


def _blob(claims: dict) -> str:
    payload = {"claims": [{"typ": k, "val": v} for k, v in claims.items()]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


UPN = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"


@pytest.fixture(autouse=True)
def _enforce_auth(monkeypatch):
    """Default every test to production behaviour: anonymous access denied."""
    monkeypatch.setattr(auth, "ALLOW_ANONYMOUS", False)
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", ["insight.com"])


def test_principal_from_name_header():
    p = auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL-NAME": "ravi.inala@insight.com"})
    assert p.email == "ravi.inala@insight.com"
    assert not p.is_dev_identity


def test_header_lookup_is_case_insensitive():
    p = auth.principal_from_headers({"x-ms-client-principal-name": "a@insight.com"})
    assert p.email == "a@insight.com"


def test_principal_decoded_from_claims_blob():
    p = auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL": _blob({UPN: "b@insight.com"})})
    assert p.email == "b@insight.com"


def test_unpadded_claims_blob_still_decodes():
    """Easy Auth frequently strips base64 padding in transit."""
    blob = _blob({UPN: "c@insight.com"}).rstrip("=")
    assert auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL": blob}).email == "c@insight.com"


def test_malformed_blob_is_ignored_rather_than_crashing():
    with pytest.raises(auth.AuthError):
        auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL": "!!!not-base64!!!"})


def test_anonymous_request_is_rejected():
    with pytest.raises(auth.AuthError, match="single sign-on"):
        auth.principal_from_headers({})


def test_foreign_tenant_is_rejected():
    with pytest.raises(auth.AuthError, match="outside the permitted domains"):
        auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL-NAME": "someone@contoso.com"})


def test_dev_identity_only_when_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_ANONYMOUS", True)
    monkeypatch.setattr(auth, "DEV_USER_EMAIL", "dev@insight.com")
    p = auth.principal_from_headers({})
    assert p.is_dev_identity and p.email == "dev@insight.com"


def test_empty_domain_allowlist_permits_any_tenant(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", [])
    assert auth.principal_from_headers({"X-MS-CLIENT-PRINCIPAL-NAME": "x@contoso.com"}).email == "x@contoso.com"
