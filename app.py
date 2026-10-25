"""Streamlit entry point for the ATS Resume Analyzer."""

from __future__ import annotations

import time

import streamlit as st

from auth import authenticate, logout, require_role
from components.admin_dashboard import render_admin_dashboard
from components.user_dashboard import render_user_dashboard
from config import (
    ADMIN_PASSWORD_HASH,
    APP_TITLE,
    LOGIN_LOCKOUT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    get_configured_users,
)
from utils.storage import init_db, record_audit_event


def _login_screen() -> None:
    st.title(APP_TITLE)
    st.caption("Sign in to securely analyze a resume against a target job description.")
    try:
        configured_users = get_configured_users()
    except ValueError as exc:
        st.error(f"Authentication configuration error: {exc}")
        return
    if not ADMIN_PASSWORD_HASH and not configured_users:
        st.error(
            "No accounts are configured. Set ATS_ADMIN_PASSWORD_HASH for an "
            "administrator and/or configure ATS_USERS_JSON."
        )
        return

    locked_until = st.session_state.get("login_locked_until", 0.0)
    remaining = int(locked_until - time.time())
    if remaining > 0:
        st.error(f"Too many failed attempts. Try again in {remaining} seconds.")
        return
    if locked_until:
        st.session_state.login_attempts = 0
        st.session_state.login_locked_until = 0.0

    with st.form("login_form"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password"
        )
        submitted = st.form_submit_button("Sign in", use_container_width=True)

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


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📄", layout="wide")
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
