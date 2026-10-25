"""Streamlit entry point for the ATS Resume Analyzer."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing

import streamlit as st

import auth as auth_module
from components.admin_dashboard import render_admin_dashboard
from components.user_dashboard import render_user_dashboard
from config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME,
    APP_TITLE,
    DATABASE_PATH,
    LOGIN_LOCKOUT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    get_configured_users,
)
from utils.storage import init_db, record_audit_event

MIN_ADMIN_PASSWORD_LENGTH = 12
MIN_CANDIDATE_PASSWORD_LENGTH = 12

authenticate = getattr(auth_module, "authenticate", None)
create_initial_admin = getattr(auth_module, "create_initial_admin", None)
hash_password = getattr(auth_module, "hash_password", None)
has_configured_admin = getattr(auth_module, "has_configured_admin", None)
logout = getattr(auth_module, "logout", None)
require_role = getattr(auth_module, "require_role", None)
create_candidate_account = getattr(
    auth_module, "create_candidate_account", None
)


def _legacy_create_candidate_account(
    username: str, password: str
) -> dict[str, str]:
    """Register candidates when running with an older auth.py module."""
    normalized_username = username.strip() if isinstance(username, str) else ""
    if not 3 <= len(normalized_username) <= 100:
        raise ValueError("Username must be between 3 and 100 characters.")
    if not isinstance(password, str) or not (
        MIN_CANDIDATE_PASSWORD_LENGTH <= len(password) <= 1024
    ):
        raise ValueError(
            f"Password must be between {MIN_CANDIDATE_PASSWORD_LENGTH} and "
            "1024 characters."
        )
    if not callable(hash_password):
        raise RuntimeError(
            "The installed auth.py is too old to register accounts. "
            "Deploy the current auth.py and app.py files together."
        )

    configured_accounts = get_configured_users()
    reserved_names = set(configured_accounts)
    if ADMIN_PASSWORD_HASH:
        reserved_names.add(ADMIN_USERNAME)
    if any(
        name.casefold() == normalized_username.casefold()
        for name in reserved_names
    ):
        raise ValueError("That username is already registered.")

    parent = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(parent, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH, timeout=10)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS local_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'candidate')),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT 1 FROM local_users WHERE username = ? COLLATE NOCASE",
            (normalized_username,),
        ).fetchone()
        if existing:
            connection.rollback()
            raise ValueError("That username is already registered.")
        try:
            connection.execute(
                "INSERT INTO local_users(username, password_hash, role, created_at) "
                "VALUES (?, ?, 'candidate', datetime('now'))",
                (normalized_username, hash_password(password)),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ValueError("That username is already registered.") from exc
    return {"username": normalized_username, "role": "candidate"}


if not callable(create_candidate_account):
    create_candidate_account = _legacy_create_candidate_account

_REQUIRED_AUTH_FUNCTIONS = {
    "authenticate": authenticate,
    "create_initial_admin": create_initial_admin,
    "hash_password": hash_password,
    "has_configured_admin": has_configured_admin,
    "logout": logout,
    "require_role": require_role,
}


def _first_admin_screen(configured_users: dict[str, dict[str, str]]) -> None:
    st.title(APP_TITLE)
    st.subheader("Create the first administrator")
    st.info(
        "This app has no administrator account yet. Create one to secure access "
        "to the candidate and admin dashboards."
    )
    with st.form("first_admin_form"):
        username = st.text_input("Administrator username", max_chars=100)
        password = st.text_input(
            "Password",
            type="password",
            help=f"Use at least {MIN_ADMIN_PASSWORD_LENGTH} characters.",
        )
        password_confirmation = st.text_input(
            "Confirm password",
            type="password",
        )
        submitted = st.form_submit_button(
            "Create administrator", type="primary", use_container_width=True
        )

    if not submitted:
        return
    normalized_username = username.strip()
    if len(normalized_username) < 3:
        st.error("The username must contain at least 3 characters.")
        return
    if normalized_username in configured_users:
        st.error("That username is already configured. Choose another username.")
        return
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        st.error(f"Use a password with at least {MIN_ADMIN_PASSWORD_LENGTH} characters.")
        return
    if password != password_confirmation:
        st.error("The passwords do not match.")
        return

    try:
        create_initial_admin(normalized_username, hash_password(password))
    except ValueError as exc:
        st.error(str(exc))
        return
    record_audit_event(
        "initial_admin_created",
        username=normalized_username,
    )
    st.session_state.user = {"username": normalized_username, "role": "admin"}
    st.session_state.login_attempts = 0
    st.session_state.login_locked_until = 0.0
    st.rerun()


def _login_screen() -> None:
    st.title(APP_TITLE)
    st.caption("Sign in to securely analyze a resume against a target job description.")
    try:
        configured_users = get_configured_users()
    except ValueError as exc:
        st.error(f"Authentication configuration error: {exc}")
        return
    if not has_configured_admin():
        _first_admin_screen(configured_users)
        return

    locked_until = st.session_state.get("login_locked_until", 0.0)
    remaining = int(locked_until - time.time())
    if locked_until and remaining <= 0:
        st.session_state.login_attempts = 0
        st.session_state.login_locked_until = 0.0

    sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with sign_in_tab:
        if remaining > 0:
            st.error(f"Too many failed attempts. Try again in {remaining} seconds.")
        with st.form("login_form"):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input(
                "Password", type="password", autocomplete="current-password"
            )
            submitted = st.form_submit_button(
                "Sign in", use_container_width=True, disabled=remaining > 0
            )

        if submitted:
            user = authenticate(username, password)
            if user is None:
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state.login_attempts = attempts
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    st.session_state.login_locked_until = (
                        time.time() + LOGIN_LOCKOUT_SECONDS
                    )
                record_audit_event("login_failed", username=username.strip()[:100])
                st.error("Invalid username or password.")
                return

            st.session_state.login_attempts = 0
            st.session_state.login_locked_until = 0.0
            st.session_state.user = user
            record_audit_event("login_succeeded", username=user["username"])
            st.rerun()

    with register_tab:
        st.caption(
            "Create a candidate account. New registrations cannot access "
            "administrator features."
        )
        with st.form("candidate_registration_form"):
            new_username = st.text_input(
                "New username",
                max_chars=100,
                key="registration_username",
                autocomplete="username",
            )
            new_password = st.text_input(
                "New password",
                type="password",
                key="registration_password",
                help="Use at least 12 characters.",
                autocomplete="new-password",
            )
            password_confirmation = st.text_input(
                "Confirm password",
                type="password",
                key="registration_password_confirmation",
                autocomplete="new-password",
            )
            register_submitted = st.form_submit_button(
                "Create candidate account",
                type="primary",
                use_container_width=True,
            )

        if register_submitted:
            if new_password != password_confirmation:
                st.error("The passwords do not match.")
                return
            try:
                user = create_candidate_account(new_username, new_password)
            except ValueError as exc:
                st.error(str(exc))
                return
            record_audit_event("candidate_registered", username=user["username"])
            st.session_state.login_attempts = 0
            st.session_state.login_locked_until = 0.0
            st.session_state.user = user
            st.rerun()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📄", layout="wide")
    missing_auth_functions = [
        name
        for name, function in _REQUIRED_AUTH_FUNCTIONS.items()
        if not callable(function)
    ]
    if missing_auth_functions:
        st.error(
            "This deployment has an outdated or incomplete auth.py. Missing "
            f"functions: {', '.join(missing_auth_functions)}. Deploy the current "
            "auth.py and app.py from the same project version, then restart the app."
        )
        return
    init_db()

    user = st.session_state.get("user")
    if not isinstance(user, dict) or not require_role(user, {"admin", "candidate"}):
        _login_screen()
        return

    with st.sidebar:
        st.title("ATS Analyzer")
        st.caption(f"Signed in as **{user['username']}** · {user['role']}")
        if st.button("Sign out", use_container_width=True):
            record_audit_event("logout", username=user["username"])
            logout()
            st.rerun()

    if user["role"] == "admin":
        render_admin_dashboard(user["username"])
    elif user["role"] == "candidate":
        render_user_dashboard(user["username"])
    else:
        logout()
        st.error("Your account has an unsupported role. Please sign in again.")


if __name__ == "__main__":
    main()
