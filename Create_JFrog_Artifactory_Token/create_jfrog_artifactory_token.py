#!/usr/bin/env python

from __future__ import annotations

import getpass
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import requests

## --------- Configuration ---------- ##

BASE_URL = "https://artifactory-ehv.ta.philips.com"
PASS_FOLDER = "philips-artifactory"

REPOSITORIES = [
    "dcp-sgs-local",
    "dcp-sgs-docker-local",
    "dps-maven-remote",
    "dps-python-remote",
    "dps-sgse-maven-virtual",
]

PASS_ENTRY_NAMES = {
    "dcp-sgs-local": "dcp-sgs-local-api-token",
    "dcp-sgs-docker-local": "dcp-sgs-docker-local-api-token",
    "dps-maven-remote": "dps-maven-remote-api-token",
    "dps-python-remote": "dps-python-remote-api-token",
    "dps-sgse-maven-virtual": "dps-sgse-maven-virtual-api-token",
}

## ---------- Prompts ---------- ##

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


## ---------- JFrog API ---------- ##

def create_token(
    username: str,
    password: str,
    expires_in: int,
    refreshable: bool,
    verify_ssl: bool,
) -> Dict[str, Any]:
    url = f"{BASE_URL}/access/api/v1/tokens"
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
        timeout=30,
        verify=verify_ssl,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text.strip()}")
    return response.json()


def refresh_token(refresh_tok: str, verify_ssl: bool) -> Dict[str, Any]:
    url = f"{BASE_URL}/access/api/v1/tokens"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
    }

    response = requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
        verify=verify_ssl,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text.strip()}")
    return response.json()


def validate_repo(repo: str, access_token: str, verify_ssl: bool) -> Tuple[bool, str]:
    url = f"{BASE_URL}/artifactory/api/repositories/{repo}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=30, verify=verify_ssl)
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, "Access confirmed."
    if response.status_code == 404:
        return False, "Repository not found."
    if response.status_code in (401, 403):
        return False, f"Access denied (HTTP {response.status_code})."
    return False, f"Unexpected HTTP {response.status_code}."


def test_artifact_download(
    repo: str,
    artifact_path: str,
    access_token: str,
    verify_ssl: bool,
) -> Tuple[bool, str]:
    headers = {"X-JFrog-Art-Api": access_token}
    url = f"{BASE_URL}/artifactory/{repo}/{artifact_path.lstrip('/')}"

    try:
        response = requests.head(url, headers=headers, timeout=30, verify=verify_ssl)
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        size = response.headers.get("Content-Length", "unknown")
        return True, f"Accessible ({size} bytes)."
    if response.status_code == 404:
        return False, "Artifact not found."
    if response.status_code in (401, 403):
        return False, f"Access denied (HTTP {response.status_code})."
    return False, f"Unexpected HTTP {response.status_code}."


## ---------- Communicate with pass ---------- ##

def store_in_pass(repo: str, token: str) -> Tuple[bool, str]:
    entry_name = PASS_ENTRY_NAMES.get(repo, f"{repo}-api-token")
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
            return True, full_path
        return False, proc.stderr.strip()
    except FileNotFoundError:
        return False, "pass is not installed"
    except Exception as exc:
        return False, str(exc)


def retrieve_from_pass(repo: str) -> Tuple[bool, str]:
    entry_name = PASS_ENTRY_NAMES.get(repo, f"{repo}-api-token")
    full_path = f"{PASS_FOLDER}/{entry_name}"

    try:
        proc = subprocess.run(
            ["pass", "show", full_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return True, proc.stdout.strip()
        return False, proc.stderr.strip() or "No token found"
    except FileNotFoundError:
        return False, "pass is not installed"
    except Exception as exc:
        return False, str(exc)


## ---------- Processing & Output ---------- ##

def process_repo(repo: str, result: Dict[str, Any], verify_ssl: bool) -> bool:
    access_token = result.get("access_token")
    refresh_tok = result.get("refresh_token")
    token_id = result.get("token_id")
    expires_in = int(result.get("expires_in", 0))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    ok = True
    if access_token:
        valid, msg = validate_repo(repo, access_token, verify_ssl)
        print(f"  Validation: {'PASSED' if valid else 'FAILED'} - {msg}")
        ok = valid

    if ok and access_token:
        stored, store_msg = store_in_pass(repo, access_token)
        print(f"  Pass store: {'OK' if stored else 'FAILED'} - {store_msg}")
        ok = stored

    print(f"  Expires at: {expires_at} ({expires_in}s)")

    creds = {k: v for k, v in {
        "access_token": access_token,
        "refresh_token": refresh_tok,
        "token_id": token_id,
    }.items() if v}
    print(f"  Credentials: {json.dumps(creds, indent=4)}")

    return ok


def print_summary(results: Dict[str, str]) -> None:
    passed = sum(1 for s in results.values() if s == "PASSED")
    print(f"\n--- SUMMARY ({passed}/{len(results)} passed) ---")
    for repo, status in results.items():
        print(f"  [{'PASS' if status == 'PASSED' else 'FAIL'}] {repo}")
    failed = [r for r, s in results.items() if s == "FAILED"]
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")


def collect_repos() -> List[str]:
    extra = input("Additional repos (comma-separated) [optional]: ").strip()
    extra_repos = [r.strip() for r in extra.split(",") if r.strip()] if extra else []
    return REPOSITORIES + [r for r in extra_repos if r not in REPOSITORIES]


## ---------- Check & Regenerate ---------- ##

def check_token_expired(repo: str, verify_ssl: bool) -> Tuple[bool, str]:
    """Returns (is_expired, message). is_expired=True means token needs regeneration."""
    found, token = retrieve_from_pass(repo)
    if not found:
        return True, f"No existing token in pass: {token}"

    valid, msg = validate_repo(repo, token, verify_ssl)
    if valid:
        return False, "Token is still valid."
    return True, f"Token expired or invalid: {msg}"


def check_and_regenerate(
    all_repos: List[str],
    username: str,
    password: str,
    expires_in: int,
    refreshable: bool,
    verify_ssl: bool,
) -> Dict[str, str]:
    """Check each repo's token; regenerate if expired. Returns status dict."""
    results: Dict[str, str] = {}
    regenerated: List[str] = []
    still_valid: List[str] = []

    for repo in all_repos:
        print(f"\n[{repo}]")
        expired, msg = check_token_expired(repo, verify_ssl)
        print(f"  Status: {msg}")

        if not expired:
            results[repo] = "VALID"
            still_valid.append(repo)
            continue

        # Token is expired or missing - regenerate
        print(f"  Regenerating token...")
        try:
            result = create_token(username, password, expires_in, refreshable, verify_ssl)
            ok = process_repo(repo, result, verify_ssl)
            if ok:
                results[repo] = "REGENERATED"
                regenerated.append(repo)
            else:
                results[repo] = "FAILED"
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results[repo] = "FAILED"

    # --- Final report ---
    print("\n" + "=" * 50)
    print("TOKEN STATUS REPORT")
    print("=" * 50)

    if still_valid:
        print(f"\n  Still valid ({len(still_valid)}):")
        for r in still_valid:
            print(f"    - {r}")

    if regenerated:
        print(f"\n  Regenerated ({len(regenerated)}):")
        for r in regenerated:
            print(f"    - {r}")

    failed = [r for r, s in results.items() if s == "FAILED"]
    if failed:
        print(f"\n  Failed ({len(failed)}):")
        for r in failed:
            print(f"    - {r}")

    if not regenerated and not failed:
        print("\n  All tokens are still valid. No action needed.")

    return results


## ---------- Main ---------- ##

def main() -> int:
    print("JFrog Token Utility")
    print("-------------------")
    print("1. Create a new token")
    print("2. Refresh an existing token")
    print("3. Test artifact download")
    print("4. Check & regenerate expired tokens")

    choice = input("Choose an option [1/2/3/4]: ").strip()
    verify_ssl = not prompt_yes_no("Disable SSL verification?", default=False)

    results: Dict[str, str] = {}

    if choice == "1":
        all_repos = collect_repos()
        username = prompt_nonempty("Username: ")
        password = getpass.getpass("Password (hidden): ")
        expires_in = prompt_int("Token expiry in seconds", 3600)
        refreshable = prompt_yes_no("Make token refreshable?", default=True)

        for repo in all_repos:
            print(f"\n[{repo}]")
            try:
                result = create_token(username, password, expires_in, refreshable, verify_ssl)
                ok = process_repo(repo, result, verify_ssl)
                results[repo] = "PASSED" if ok else "FAILED"
            except Exception as exc:
                print(f"  ERROR: {exc}")
                results[repo] = "FAILED"

    elif choice == "2":
        all_repos = collect_repos()
        refresh_tok = getpass.getpass("Refresh token (hidden): ")

        for repo in all_repos:
            print(f"\n[{repo}]")
            try:
                result = refresh_token(refresh_tok, verify_ssl)
                ok = process_repo(repo, result, verify_ssl)
                results[repo] = "PASSED" if ok else "FAILED"
            except Exception as exc:
                print(f"  ERROR: {exc}")
                results[repo] = "FAILED"

    elif choice == "3":
        access_token = getpass.getpass("Access token (hidden): ")
        repo = prompt_nonempty("Repository name: ")
        artifact_path = prompt_nonempty("Artifact path (e.g. <version>/<file.zip>): ")

        print(f"\n[{repo}/{artifact_path}]")
        ok, msg = test_artifact_download(repo, artifact_path, access_token, verify_ssl)
        print(f"  Download test: {'PASSED' if ok else 'FAILED'} - {msg}")
        results[repo] = "PASSED" if ok else "FAILED"

    elif choice == "4":
        all_repos = collect_repos()
        username = prompt_nonempty("Username: ")
        password = getpass.getpass("Password (hidden): ")
        expires_in = prompt_int("Token expiry in seconds", 3600)
        refreshable = prompt_yes_no("Make token refreshable?", default=True)

        results = check_and_regenerate(
            all_repos, username, password, expires_in, refreshable, verify_ssl
        )
        passed = all(v in ("VALID", "REGENERATED") for v in results.values())
        return 0 if passed else 2

    else:
        print("Invalid choice.")
        return 1

    print_summary(results)
    return 0 if all(v == "PASSED" for v in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
