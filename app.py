"""Streamlit entry point for the ATS Resume Analyzer."""

from __future__ import annotations

import time

import streamlit as st

from auth import (
    authenticate,
    create_candidate_account,
    create_initial_admin,
    hash_password,
    has_configured_admin,
    logout,
    require_role,
)
from components.admin_dashboard import render_admin_dashboard
from components.user_dashboard import render_user_dashboard
from config import (
    APP_TITLE,
    LOGIN_LOCKOUT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    get_configured_users,
)
from utils.storage import init_db, record_audit_event

MIN_ADMIN_PASSWORD_LENGTH = 12


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
