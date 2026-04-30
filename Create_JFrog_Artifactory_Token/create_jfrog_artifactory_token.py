#!/usr/bin/env python

from __future__ import annotations

import getpass
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import requests

BASE_URL = "https://artifactory-ehv.ta.philips.com"

REPOSITORIES = [
    "dcp-sgs-local",
    "dcp-sgs-docker-local",
    "dps-maven-remote",
    "dps-python-remote",
    "dps-sgse-maven-virtual"
]

PASS_ENTRY_NAMES = {
    "dcp-sgs-local": "dcp-sgs-local-api-token",
    "dcp-sgs-docker-local": "dcp-sgs-docker-local-api-token",
    "dps-maven-remote": "dps-maven-remote-api-token",
    "dps-python-remote": "dps-python-remote-api-token",
    "dps-sgse-maven-virtual": "dps-sgse-maven-virtual-api-token",
}

PASS_FOLDER = "philips-artifactory"


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


def test_artifact_download(
    base_url: str,
    repo: str,
    artifact_path: str,
    access_token: str,
    verify_ssl: bool,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """
    Test downloading an artifact using X-JFrog-Art-Api header.
    artifact_path should be like: <version>/<zip-file-name>
    """
    headers = {"X-JFrog-Art-Api": access_token}
    artifact_url = f"{base_url.rstrip('/')}/artifactory/{repo}/{artifact_path.lstrip('/')}"

    try:
        # Use HEAD request to check access without downloading the full file
        response = requests.head(
            artifact_url,
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as exc:
        return False, f"Artifact access test failed: {exc}"

    if response.status_code == 200:
        content_length = response.headers.get("Content-Length", "unknown")
        return True, f"Token can access artifact at '{repo}/{artifact_path}' (size: {content_length} bytes)."
    if response.status_code == 404:
        return False, f"Artifact '{repo}/{artifact_path}' was not found."
    if response.status_code in (401, 403):
        return False, f"Token does not have download access to '{repo}/{artifact_path}' (HTTP {response.status_code})."

    return False, f"Unexpected response: HTTP {response.status_code}."


def compute_expiry(expires_in: int) -> Tuple[str, str]:
    created_at = utc_now()
    expires_at = created_at + timedelta(seconds=expires_in)
    return created_at.isoformat(), expires_at.isoformat()


def get_pass_entry_name(repo: str) -> str:
    return PASS_ENTRY_NAMES.get(repo, f"{repo}-api-token")


def store_in_pass(repo: str, token: str) -> Tuple[bool, str]:
    entry_name = get_pass_entry_name(repo)

    full_path = f"{PASS_FOLDER}/{entry_name}"
    try:
        proc = subprocess.run(
            ["pass", "insert", "--echo", "--force", full_path],
            input=token,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return True, f"Stored in pass: {full_path}"
        return False, f"pass insert failed: {proc.stderr.strip()}"
    except FileNotFoundError:
        return False, "pass is not installed"
    except Exception as exc:
        return False, f"Failed to store in pass: {exc}"


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
    expires_in = int(result.get("expires_in", 0))

    print(f"  {operation}: SUCCESS")

    created_at, expires_at = compute_expiry(expires_in)

    ok = True
    if access_token and repo:
        ok, message = validate_repo_with_token(
            base_url=base_url,
            repo=repo,
            access_token=access_token,
            verify_ssl=verify_ssl,
        )
        print(f"  Validation: {'PASSED' if ok else 'FAILED'} - {message}")

    if ok and access_token:
        stored, store_msg = store_in_pass(repo, access_token)
        print(f"  Pass store: {'OK' if stored else 'FAILED'} - {store_msg}")
        if not stored:
            ok = False

    print(f"  Expires at: {expires_at} ({expires_in}s)")

    creds = {k: v for k, v in {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_id": token_id,
    }.items() if v}
    print(f"  Credentials: {json.dumps(creds, indent=4)}")

    return 0 if ok else 2


def _print_summary(results: Dict[str, str]) -> None:
    passed = [r for r, s in results.items() if s == "PASSED"]
    failed = [r for r, s in results.items() if s == "FAILED"]

    print(f"\n--- SUMMARY ({len(passed)}/{len(results)} passed) ---")
    for repo, status in results.items():
        print(f"  [{'PASS' if status == 'PASSED' else 'FAIL'}] {repo}")
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")


def main() -> int:
    print("JFrog Token Utility")
    print("-------------------")
    print("1. Create a new token")
    print("2. Refresh an existing token")

    choice = input("Choose an option [1/2]: ").strip()

    verify_ssl = not prompt_yes_no("Disable SSL verification?", default=False)

    extra = input("Additional repos (comma-separated) [optional]: ").strip()
    extra_repos = [r.strip() for r in extra.split(",") if r.strip()] if extra else []
    all_repos = REPOSITORIES + [r for r in extra_repos if r not in REPOSITORIES]

    if choice == "1":
        username = prompt_nonempty("Username: ")
        password = getpass.getpass("Password (hidden): ")
        expires_in = prompt_int("Token expiry in seconds", 3600)
        refreshable = prompt_yes_no("Make token refreshable?", default=True)

        results_summary: Dict[str, str] = {}

        for repo in all_repos:
            print(f"\n[{repo}]")

            try:
                result = create_token(
                    base_url=BASE_URL,
                    username=username,
                    password=password,
                    expires_in=expires_in,
                    refreshable=refreshable,
                    verify_ssl=verify_ssl,
                )

                exit_code = print_result(
                    operation="Token creation",
                    repo=repo,
                    result=result,
                    verify_ssl=verify_ssl,
                    base_url=BASE_URL,
                )
                results_summary[repo] = "PASSED" if exit_code == 0 else "FAILED"

            except Exception as exc:
                print(f"\n  ERROR for '{repo}': {exc}")
                results_summary[repo] = "FAILED"

        _print_summary(results_summary)
        return 0 if all(v == "PASSED" for v in results_summary.values()) else 2

    elif choice == "2":
        existing_refresh_token = getpass.getpass("Refresh token (hidden): ")

        results_summary: Dict[str, str] = {}

        for repo in all_repos:
            print(f"\n[{repo}]")

            try:
                result = refresh_token_request(
                    base_url=BASE_URL,
                    refresh_token=existing_refresh_token,
                    verify_ssl=verify_ssl,
                )

                exit_code = print_result(
                    operation="Token refresh",
                    repo=repo,
                    result=result,
                    verify_ssl=verify_ssl,
                    base_url=BASE_URL,
                )
                results_summary[repo] = "PASSED" if exit_code == 0 else "FAILED"

            except Exception as exc:
                print(f"\n  ERROR for '{repo}': {exc}")
                results_summary[repo] = "FAILED"

        _print_summary(results_summary)
        return 0 if all(v == "PASSED" for v in results_summary.values()) else 2

    else:
        print("Invalid choice. Please run the script again and choose 1 or 2.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())