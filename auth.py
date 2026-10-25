"""Password verification and role checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import streamlit as st

from config import ADMIN_PASSWORD_HASH, ADMIN_USERNAME, get_configured_users
from utils.storage import get_local_user, has_local_admin

PBKDF2_ITERATIONS = 310_000


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Create a salted PBKDF2-SHA256 password hash for deployment configuration."""
    if not password:
        raise ValueError("Password must not be empty.")
    if iterations < 100_000:
        raise ValueError("Password hashing iterations must be at least 100,000.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


_DUMMY_PASSWORD_HASH = hash_password("invalid-account-password")


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = encoded_hash.split("$", 3)
        iterations = int(iterations_text)
        if (
            algorithm != "pbkdf2_sha256"
            or not 100_000 <= iterations <= 2_000_000
            or len(salt_hex) != 32
            or len(digest_hex) != 64
        ):
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (AttributeError, ValueError):
        return False
    calculated = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(calculated, expected)


def authenticate(username: str, password: str) -> dict[str, str] | None:
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    normalized_username = username.strip()
    if not normalized_username or not password:
        return None

    accounts = get_configured_users()
    if ADMIN_PASSWORD_HASH:
        accounts[ADMIN_USERNAME] = {
            "password_hash": ADMIN_PASSWORD_HASH,
            "role": "admin",
        }
    account = accounts.get(normalized_username)
    if account is None:
        account = get_local_user(normalized_username)
    if account is None:
        # Spend comparable work on unknown usernames to reduce timing signals.
        _verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not _verify_password(password, account["password_hash"]):
        return None
    return {"username": normalized_username, "role": account["role"]}


def has_configured_admin() -> bool:
    accounts = get_configured_users()
    return (
        bool(ADMIN_PASSWORD_HASH)
        or any(account["role"] == "admin" for account in accounts.values())
        or has_local_admin()
    )


def require_role(user: Any, allowed_roles: set[str]) -> bool:
    return (
        isinstance(user, dict)
        and isinstance(user.get("username"), str)
        and user.get("role") in allowed_roles
    )


def logout() -> None:
    st.session_state.clear()
