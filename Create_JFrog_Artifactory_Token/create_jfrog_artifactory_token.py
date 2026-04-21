#!/usr/bin/env python

from __future__ import annotations

import getpass
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import requests


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prompt_nonempty(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("This field is required.")


def prompt_int(label: str, default: int) -> int:
    raw = input(f"{label} [default={default}]: ").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if value < 0:
            raise ValueError
        return value
    except ValueError:
        print("Please enter a valid non-negative integer.")
        return prompt_int(label, default)


def prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(f"{label} [{suffix}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def create_token(
    base_url: str,
    username: str,
    password: str,
    expires_in: int,
    refreshable: bool,
    verify_ssl: bool,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/access/api/v1/tokens"
    data = {
        "grant_type": "client_credentials",
        "username": username,
        "expires_in": str(expires_in),
        "refreshable": str(refreshable).lower(),
    }

    response = requests.post(
        url,
        auth=(username, password),
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
        verify=verify_ssl,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Token creation failed.\n"
            f"HTTP {response.status_code}\n"
            f"Response: {response.text.strip()}"
        )

    return response.json()


def refresh_token_request(
    base_url: str,
    refresh_token: str,
    verify_ssl: bool,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/access/api/v1/tokens"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    response = requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
        verify=verify_ssl,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Token refresh failed.\n"
            f"HTTP {response.status_code}\n"
            f"Response: {response.text.strip()}"
        )

    return response.json()


def validate_repo_with_token(
    base_url: str,
    repo: str,
    access_token: str,
    verify_ssl: bool,
    timeout: int = 30,
) -> Tuple[bool, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    meta_url = f"{base_url.rstrip('/')}/artifactory/api/repositories/{repo}"

    try:
        response = requests.get(
            meta_url,
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as exc:
        return False, f"Repository validation request failed: {exc}"

    if response.status_code == 200:
        return True, f"Token can access repository metadata for '{repo}'."
    if response.status_code == 404:
        return False, f"Repository '{repo}' was not found."
    if response.status_code in (401, 403):
        return False, f"Token does not have access to '{repo}' (HTTP {response.status_code})."

    return False, f"Unexpected validation response: HTTP {response.status_code}."


def compute_expiry(expires_in: int) -> Tuple[str, str]:
    created_at = utc_now()
    expires_at = created_at + timedelta(seconds=expires_in)
    return created_at.isoformat(), expires_at.isoformat()


def print_result(
    operation: str,
    repo: str,
    result: Dict[str, Any],
    verify_ssl: bool,
    base_url: str,
) -> int:
    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token")
    token_id = result.get("token_id")
    scope = result.get("scope")
    token_type = result.get("token_type")
    expires_in = int(result.get("expires_in", 0))

    print(f"\n1. {operation} status: SUCCESS")
    if token_id:
        print(f"   Token ID: {token_id}")
    if token_type:
        print(f"   Token type: {token_type}")
    if scope:
        print(f"   Scope: {scope}")

    created_at, expires_at = compute_expiry(expires_in)

    if access_token and repo:
        ok, message = validate_repo_with_token(
            base_url=base_url,
            repo=repo,
            access_token=access_token,
            verify_ssl=verify_ssl,
        )
        print(f"2. Token validation for repo: {'SUCCESS' if ok else 'FAILED'}")
        print(f"   {message}")
    else:
        ok = True
        print("2. Token validation for repo: SKIPPED")
        print("   No repository provided for validation.")

    print("3. Token expiry:")
    print(f"   Created at (UTC): {created_at}")
    print(f"   Expires at (UTC): {expires_at}")
    print(f"   Expires in: {expires_in} seconds")

    print("\nReturned credentials:")
    safe = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "scope": scope,
        "token_id": token_id,
        "token_type": token_type,
    }
    print(json.dumps(safe, indent=2))

    return 0 if ok else 2


def main() -> int:
    print("JFrog Token Utility")
    print("-------------------")
    print("1. Create a new token")
    print("2. Refresh an existing token")

    choice = input("Choose an option [1/2]: ").strip()

    base_url = prompt_nonempty("JFrog URL (e.g. https://your-company.jfrog.io): ")
    verify_ssl = not prompt_yes_no("Disable SSL verification?", default=False)

    try:
        if choice == "1":
            username = prompt_nonempty("Username: ")
            password = getpass.getpass("Password (hidden): ")
            repo = prompt_nonempty("Repository name to validate: ")
            expires_in = prompt_int("Token expiry in seconds", 3600)
            refreshable = prompt_yes_no("Make token refreshable?", default=True)

            result = create_token(
                base_url=base_url,
                username=username,
                password=password,
                expires_in=expires_in,
                refreshable=refreshable,
                verify_ssl=verify_ssl,
            )

            return print_result(
                operation="Token creation",
                repo=repo,
                result=result,
                verify_ssl=verify_ssl,
                base_url=base_url,
            )

        elif choice == "2":
            existing_refresh_token = getpass.getpass("Refresh token (hidden): ")
            repo = input("Repository name to validate [optional]: ").strip()

            result = refresh_token_request(
                base_url=base_url,
                refresh_token=existing_refresh_token,
                verify_ssl=verify_ssl,
            )

            return print_result(
                operation="Token refresh",
                repo=repo,
                result=result,
                verify_ssl=verify_ssl,
                base_url=base_url,
            )

        else:
            print("Invalid choice. Please run the script again and choose 1 or 2.")
            return 1

    except Exception as exc:
        print("\n1. Operation status: FAILED")
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())