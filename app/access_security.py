"""Shared development-access credential and token helpers.

This module intentionally provides a small temporary access gate for the early
single-user development stage. It is not a replacement for the future user and
ownership authorization model.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

ACCESS_ENABLED_ENV = "APP_ACCESS_ENABLED"
ACCESS_PASSWORD_HASH_ENV = "APP_ACCESS_PASSWORD_HASH"
ACCESS_TOKEN_SECRET_ENV = "APP_ACCESS_TOKEN_SECRET"
ACCESS_TOKEN_TTL_ENV = "APP_ACCESS_TOKEN_TTL_SECONDS"

PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_DEFAULT_ITERATIONS = 600_000
PASSWORD_HASH_MIN_ITERATIONS = 100_000
PASSWORD_HASH_MAX_ITERATIONS = 2_000_000
PASSWORD_SALT_BYTES = 16
PASSWORD_DIGEST_BYTES = 32
SHARED_PASSWORD_MIN_LENGTH = 12

ACCESS_TOKEN_DEFAULT_TTL_SECONDS = 12 * 60 * 60
ACCESS_TOKEN_MIN_TTL_SECONDS = 5 * 60
ACCESS_TOKEN_MAX_TTL_SECONDS = 24 * 60 * 60
ACCESS_TOKEN_CLOCK_SKEW_SECONDS = 60
ACCESS_TOKEN_SUBJECT = "shared-development-access"
ACCESS_TOKEN_SCOPE = "app"
ACCESS_TOKEN_VERSION = 1
ACCESS_TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_MIN_SECRET_LENGTH = 32
ACCESS_TOKEN_MAX_LENGTH = 4096

_TRUE_VALUES = {"1", "true", "yes", "on"}


class AccessConfigurationError(RuntimeError):
    """Raised when the development access gate is enabled but misconfigured."""


class AccessTokenError(ValueError):
    """Raised when an access token is missing, malformed, invalid, or expired."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("invalid base64url value") from exc
    padding = b"=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.b64decode(raw + padding, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid base64url value") from exc


def is_access_gate_enabled() -> bool:
    """Return whether shared development access enforcement is enabled."""
    return os.getenv(ACCESS_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def hash_password(
    password: str,
    *,
    iterations: int = PASSWORD_HASH_DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Return a portable PBKDF2-SHA256 encoded password hash."""
    if len(password) < SHARED_PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"shared development password must be at least {SHARED_PASSWORD_MIN_LENGTH} characters"
        )
    if not PASSWORD_HASH_MIN_ITERATIONS <= iterations <= PASSWORD_HASH_MAX_ITERATIONS:
        raise ValueError("PBKDF2 iteration count is outside the supported range")
    if salt is None:
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    if len(salt) < PASSWORD_SALT_BYTES:
        raise ValueError("password salt is too short")

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=PASSWORD_DIGEST_BYTES,
    )
    return "$".join(
        (
            PASSWORD_HASH_SCHEME,
            str(iterations),
            _b64url_encode(salt),
            _b64url_encode(digest),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password against the configured PBKDF2 hash."""
    try:
        scheme, iterations_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if scheme != PASSWORD_HASH_SCHEME:
            raise ValueError("unsupported password hash scheme")
        iterations = int(iterations_text)
        if not PASSWORD_HASH_MIN_ITERATIONS <= iterations <= PASSWORD_HASH_MAX_ITERATIONS:
            raise ValueError("PBKDF2 iteration count is outside the supported range")
        salt = _b64url_decode(salt_text)
        expected_digest = _b64url_decode(digest_text)
        if len(salt) < PASSWORD_SALT_BYTES or len(expected_digest) != PASSWORD_DIGEST_BYTES:
            raise ValueError("invalid password hash parameters")
    except (TypeError, ValueError) as exc:
        raise AccessConfigurationError("APP_ACCESS_PASSWORD_HASH is invalid") from exc

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def verify_configured_password(password: str) -> bool:
    """Verify a login password using the configured non-plaintext hash."""
    encoded_hash = os.getenv(ACCESS_PASSWORD_HASH_ENV, "").strip()
    if not encoded_hash:
        raise AccessConfigurationError("APP_ACCESS_PASSWORD_HASH is not configured")
    return verify_password(password, encoded_hash)


def _token_secret() -> bytes:
    value = os.getenv(ACCESS_TOKEN_SECRET_ENV, "")
    if len(value) < ACCESS_TOKEN_MIN_SECRET_LENGTH:
        raise AccessConfigurationError(
            "APP_ACCESS_TOKEN_SECRET must contain at least 32 characters"
        )
    return value.encode("utf-8")


def access_token_ttl_seconds() -> int:
    raw = os.getenv(ACCESS_TOKEN_TTL_ENV, str(ACCESS_TOKEN_DEFAULT_TTL_SECONDS)).strip()
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise AccessConfigurationError("APP_ACCESS_TOKEN_TTL_SECONDS must be an integer") from exc
    if not ACCESS_TOKEN_MIN_TTL_SECONDS <= ttl <= ACCESS_TOKEN_MAX_TTL_SECONDS:
        raise AccessConfigurationError(
            "APP_ACCESS_TOKEN_TTL_SECONDS must be between 300 and 86400"
        )
    return ttl


def issue_access_token(*, now: int | None = None) -> tuple[str, int]:
    """Issue a signed short-lived HS256 JWT for shared app access."""
    issued_at = int(time.time()) if now is None else int(now)
    ttl = access_token_ttl_seconds()
    header = {"alg": ACCESS_TOKEN_ALGORITHM, "typ": "JWT"}
    payload = {
        "v": ACCESS_TOKEN_VERSION,
        "sub": ACCESS_TOKEN_SUBJECT,
        "scope": ACCESS_TOKEN_SCOPE,
        "iat": issued_at,
        "exp": issued_at + ttl,
    }
    header_segment = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(_token_secret(), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}", ttl


def _decode_json_segment(segment: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64url_decode(segment).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AccessTokenError("invalid access token") from exc
    if not isinstance(decoded, dict):
        raise AccessTokenError("invalid access token")
    return decoded


def verify_access_token(token: str, *, now: int | None = None) -> dict[str, Any]:
    """Verify and return the claims of a shared development-access JWT."""
    if not token or len(token) > ACCESS_TOKEN_MAX_LENGTH:
        raise AccessTokenError("invalid access token")
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    except (ValueError, UnicodeEncodeError) as exc:
        raise AccessTokenError("invalid access token") from exc

    try:
        supplied_signature = _b64url_decode(signature_segment)
    except ValueError as exc:
        raise AccessTokenError("invalid access token") from exc
    expected_signature = hmac.new(_token_secret(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise AccessTokenError("invalid access token")

    header = _decode_json_segment(header_segment)
    if header.get("alg") != ACCESS_TOKEN_ALGORITHM or header.get("typ") != "JWT":
        raise AccessTokenError("invalid access token")

    payload = _decode_json_segment(payload_segment)
    if (
        payload.get("v") != ACCESS_TOKEN_VERSION
        or payload.get("sub") != ACCESS_TOKEN_SUBJECT
        or payload.get("scope") != ACCESS_TOKEN_SCOPE
    ):
        raise AccessTokenError("invalid access token")

    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise AccessTokenError("invalid access token")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise AccessTokenError("invalid access token")

    current_time = int(time.time()) if now is None else int(now)
    if issued_at > current_time + ACCESS_TOKEN_CLOCK_SKEW_SECONDS:
        raise AccessTokenError("invalid access token")
    if expires_at <= current_time:
        raise AccessTokenError("access token expired")
    if expires_at <= issued_at:
        raise AccessTokenError("invalid access token")
    return payload


def _cli_hash_password() -> None:
    password = getpass.getpass("Shared development password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < SHARED_PASSWORD_MIN_LENGTH:
        raise SystemExit(
            f"Password must be at least {SHARED_PASSWORD_MIN_LENGTH} characters"
        )
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    print(hash_password(password))


def _cli_generate_token_secret() -> None:
    print(secrets.token_urlsafe(48))


def main() -> None:
    parser = argparse.ArgumentParser(description="Development access-gate utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hash-password", help="Generate APP_ACCESS_PASSWORD_HASH")
    subparsers.add_parser(
        "generate-token-secret", help="Generate APP_ACCESS_TOKEN_SECRET"
    )
    args = parser.parse_args()
    if args.command == "hash-password":
        _cli_hash_password()
    else:
        _cli_generate_token_secret()


if __name__ == "__main__":
    main()
