"""Microsoft Entra ID identity, as surfaced by Azure App Service Easy Auth.

Easy Auth terminates the OIDC flow at the platform edge and injects the verified
principal as request headers. The application therefore never handles tokens --
but that only holds while traffic cannot reach the container except through the
platform. The backend port must stay private; see README for the deployment note.

Locally there is no platform in front of us, so ALLOW_ANONYMOUS_AUTH=true turns
on a developer identity. It must never be set in production.
"""
import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping, Optional

from src import config  # noqa: F401 - ensures .env is loaded before the constants below

PRINCIPAL_NAME_HEADER = "x-ms-client-principal-name"
PRINCIPAL_ID_HEADER = "x-ms-client-principal-id"
PRINCIPAL_BLOB_HEADER = "x-ms-client-principal"

ALLOW_ANONYMOUS = os.getenv("ALLOW_ANONYMOUS_AUTH", "false").lower() in ("true", "1", "yes")
DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev.user@insight.com")

# Restrict sign-in to the corporate tenant's domains. Empty => any authenticated user.
ALLOWED_EMAIL_DOMAINS = [
    d.strip().lower()
    for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "insight.com").split(",")
    if d.strip()
]


@dataclass(frozen=True)
class Principal:
    email: str
    object_id: Optional[str] = None
    display_name: Optional[str] = None
    is_dev_identity: bool = False

    @property
    def domain(self) -> str:
        return self.email.rsplit("@", 1)[-1].lower() if "@" in self.email else ""


class AuthError(Exception):
    """Raised when no valid principal can be established for a request."""


def _decode_principal_blob(blob: str) -> dict:
    """Easy Auth's base64 claims blob; padding is often stripped in transit."""
    padded = blob + "=" * (-len(blob) % 4)
    return json.loads(base64.b64decode(padded).decode("utf-8"))


def _claims_lookup(payload: dict) -> dict:
    claims = {}
    for claim in payload.get("claims", []):
        typ = claim.get("typ") or claim.get("type")
        if typ:
            claims[typ] = claim.get("val") or claim.get("value")
    return claims


def principal_from_headers(headers: Mapping[str, str]) -> Principal:
    """Build a Principal from Easy Auth headers, or raise AuthError."""
    # Header names are case-insensitive; normalise so plain dicts work too.
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}

    email = lowered.get(PRINCIPAL_NAME_HEADER)
    object_id = lowered.get(PRINCIPAL_ID_HEADER)
    display_name = None

    blob = lowered.get(PRINCIPAL_BLOB_HEADER)
    if blob:
        try:
            claims = _claims_lookup(_decode_principal_blob(blob))
            email = email or claims.get(
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"
            ) or claims.get(
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
            ) or claims.get("preferred_username")
            object_id = object_id or claims.get(
                "http://schemas.microsoft.com/identity/claims/objectidentifier"
            )
            display_name = claims.get(
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
            ) or claims.get("name")
        except Exception:  # noqa: BLE001 - a malformed blob simply yields no claims
            pass

    if not email:
        if ALLOW_ANONYMOUS:
            return Principal(email=DEV_USER_EMAIL, display_name="Local Developer", is_dev_identity=True)
        raise AuthError(
            "Not signed in. This application requires Microsoft Entra ID single sign-on."
        )

    principal = Principal(email=email, object_id=object_id, display_name=display_name or email)

    if ALLOWED_EMAIL_DOMAINS and principal.domain not in ALLOWED_EMAIL_DOMAINS:
        raise AuthError(
            f"Account '{principal.email}' is outside the permitted domains "
            f"({', '.join(ALLOWED_EMAIL_DOMAINS)})."
        )

    return principal
