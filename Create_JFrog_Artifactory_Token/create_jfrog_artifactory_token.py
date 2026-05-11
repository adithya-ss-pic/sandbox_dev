#!/usr/bin/env python

from __future__ import annotations

import argparse
import base64
import getpass
import json
import subprocess
import time
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

PASS_REFRESH_TOKEN_NAMES = {
    "dcp-sgs-local": "dcp-sgs-local-refresh-token",
    "dcp-sgs-docker-local": "dcp-sgs-docker-local-refresh-token",
    "dps-maven-remote": "dps-maven-remote-refresh-token",
    "dps-python-remote": "dps-python-remote-refresh-token",
    "dps-sgse-maven-virtual": "dps-sgse-maven-virtual-refresh-token",
}

# Credentials stored in pass for non-interactive (auto) mode
PASS_CREDENTIAL_ENTRIES = {
    "username": "code1-id",
    "password": "code1-password",
}

# Artifact paths for smoke testing after token refresh/creation
ARTIFACT_SMOKE_TESTS = {
    "dcp-sgs-local": "rhel-9-baseos-rpms/20251113.2/repodata/repomd.xml",
    "dcp-sgs-docker-local": "sgs-buildagent-base/3.0.155/manifest.json",
    "dps-maven-remote": "last_updated.txt",
    "dps-python-remote": ".pypi/version-utils.html",
    "dps-sgse-maven-virtual": "last_updated.txt",
}

TOKEN_REFRESH_BUFFER_SECONDS = 3600

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
        "include_reference_token": "true",
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
        "include_reference_token": "true",
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
    headers = {"X-JFrog-Art-Api": access_token}

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

def _pass_show(full_path: str) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["pass", "show", full_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return True, proc.stdout.strip()
        return False, proc.stderr.strip() or "Entry not found"
    except FileNotFoundError:
        return False, "pass is not installed"
    except Exception as exc:
        return False, str(exc)


def _pass_insert(full_path: str, value: str) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["pass", "insert", "--echo", "--force", full_path],
            input=value,
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


def retrieve_credentials_from_pass() -> Tuple[bool, str, str]:
    user_entry = f"{PASS_FOLDER}/{PASS_CREDENTIAL_ENTRIES['username']}"
    pass_entry = f"{PASS_FOLDER}/{PASS_CREDENTIAL_ENTRIES['password']}"

    ok, username = _pass_show(user_entry)
    if not ok:
        return False, "", f"Failed to retrieve username: {username}"

    ok, password = _pass_show(pass_entry)
    if not ok:
        return False, "", f"Failed to retrieve password: {password}"

    return True, username, password


def store_in_pass(repo: str, token: str) -> Tuple[bool, str]:
    entry_name = PASS_ENTRY_NAMES.get(repo, f"{repo}-api-token")
    full_path = f"{PASS_FOLDER}/{entry_name}"
    return _pass_insert(full_path, token)


def store_refresh_token_in_pass(repo: str, refresh_tok: str) -> Tuple[bool, str]:
    entry_name = PASS_REFRESH_TOKEN_NAMES.get(repo, f"{repo}-refresh-token")
    full_path = f"{PASS_FOLDER}/{entry_name}"
    return _pass_insert(full_path, refresh_tok)


def retrieve_from_pass(repo: str) -> Tuple[bool, str]:
    entry_name = PASS_ENTRY_NAMES.get(repo, f"{repo}-api-token")
    full_path = f"{PASS_FOLDER}/{entry_name}"
    return _pass_show(full_path)


def retrieve_refresh_token_from_pass(repo: str) -> Tuple[bool, str]:
    entry_name = PASS_REFRESH_TOKEN_NAMES.get(repo, f"{repo}-refresh-token")
    full_path = f"{PASS_FOLDER}/{entry_name}"
    return _pass_show(full_path)


## ---------- Processing & Output ---------- ##

def _mask_token(value: str) -> str:
    """Mask a token value, showing only the first 5 characters."""
    if len(value) <= 5:
        return value
    return f"{value[:5]}{'*' * 20}"


def process_repo(repo: str, result: Dict[str, Any], verify_ssl: bool) -> bool:
    access_token = result.get("access_token")
    reference_token = result.get("reference_token")
    refresh_tok = result.get("refresh_token")
    token_id = result.get("token_id")
    expires_in = int(result.get("expires_in", 0))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Prefer the reference token (opaque, works with X-JFrog-Art-Api header)
    api_token = reference_token or access_token

    ok = True
    if api_token:
        valid, msg = validate_repo(repo, api_token, verify_ssl)
        print(f"  Validation: {'PASSED' if valid else 'FAILED'} - {msg}")
        ok = valid

    if ok and api_token:
        stored, store_msg = store_in_pass(repo, api_token)
        print(f"  Pass store (reference token): {'OK' if stored else 'FAILED'} - {store_msg}")
        ok = stored

    if ok and refresh_tok:
        stored, store_msg = store_refresh_token_in_pass(repo, refresh_tok)
        print(f"  Pass store (refresh token): {'OK' if stored else 'FAILED'} - {store_msg}")
        # Non-fatal: refresh token storage failure doesn't block the flow

    # Check if a artifact can be downloaded. 
    # Only do this if the token is valid and we have a known artifact path for the repo.
    if ok and api_token and repo in ARTIFACT_SMOKE_TESTS:
        artifact_path = ARTIFACT_SMOKE_TESTS[repo]
        art_ok, art_msg = test_artifact_download(repo, artifact_path, api_token, verify_ssl)
        print(f"  Artifact smoke test: {'PASSED' if art_ok else 'FAILED'} - {art_msg}")

    print(f"  Expires at: {expires_at} ({expires_in}s)")

    token_fields = [
        ("reference_token", reference_token),
        ("access_token", access_token),
        ("refresh_token", refresh_tok),
        ("token_id", token_id),
    ]
    entries = [(k, v) for k, v in token_fields if v]
    print("  Credentials: {")
    for i, (key, value) in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        if key == "token_id":
            print(f'      "{key}": "{value}"{comma}')
        else:
            print(f'      "{key}": "{_mask_token(value)}" (Length: {len(value)}){comma}')
    print("  }")

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

def decode_jwt_expiry(token: str) -> float | None:
    try:
        payload_b64 = token.split(".")[1]
        # Base64url requires padding to be a multiple of 4
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(claims["exp"])
    except Exception:
        return None


def is_token_expiring_soon(token: str) -> Tuple[bool, str]:
    exp = decode_jwt_expiry(token)
    if exp is None:
        return True, "Could not decode token; treating as expired"

    seconds_left = exp - time.time()
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if seconds_left <= 0:
        return True, f"Token expired at {expires_at}"
    if seconds_left <= TOKEN_REFRESH_BUFFER_SECONDS:
        return True, f"Token expires at {expires_at} (within refresh buffer of {TOKEN_REFRESH_BUFFER_SECONDS}s)"
    return False, f"Token valid until {expires_at} ({int(seconds_left)}s remaining)"


def check_token_status(repo: str, verify_ssl: bool) -> Tuple[str, str]:
    found, token = retrieve_from_pass(repo)
    if not found:
        return "missing", "No existing token found in credential store"

    # Reference tokens are opaque (not JWT) - can only validate via API
    is_opaque = token.count(".") != 2

    if not is_opaque:
        expiring, jwt_msg = is_token_expiring_soon(token)
        if not expiring:
            return "valid", f"Token is active and valid ({jwt_msg})"

    try:
        valid, msg = validate_repo(repo, token, verify_ssl)
    except requests.ConnectionError:
        return "unreachable", "Server unreachable; using existing token as-is"
    except requests.Timeout:
        return "unreachable", "Server timed out; using existing token as-is"

    if valid:
        if is_opaque:
            return "valid", f"Reference token is active ({msg})"
        # Refresh token when the remaining time is within the defined buffer.
        return "expiring", f"Token is active but expiring soon ({jwt_msg})"
    return "expired", f"Token is expired or no longer valid ({msg})"


def _try_refresh_token(repo: str, verify_ssl: bool) -> Tuple[bool, Dict[str, Any]]:
    found, refresh_tok = retrieve_refresh_token_from_pass(repo)
    if not found:
        return False, {}

    try:
        result = refresh_token(refresh_tok, verify_ssl)
        return True, result
    except Exception:
        return False, {}


def check_and_regenerate(
    all_repos: List[str],
    username: str,
    password: str,
    expires_in: int,
    refreshable: bool,
    verify_ssl: bool,
) -> Dict[str, str]:
    results: Dict[str, str] = {}
    still_valid: List[str] = []
    refreshed: List[str] = []
    generated_new: List[str] = []
    unreachable: List[str] = []

    for repo in all_repos:
        print(f"\n[{repo}]")
        status, msg = check_token_status(repo, verify_ssl)
        print(f"  Check: {msg}")

        if status == "valid":
            print(f"  Action: No action required")
            results[repo] = "VALID"
            still_valid.append(repo)
            continue

        if status == "unreachable":
            print(f"  Action: Graceful fallback - keeping existing token")
            results[repo] = "UNREACHABLE"
            unreachable.append(repo)
            continue

        # Token is expired or missing - try refresh first, then fall back to create
        if status in ("expired", "expiring"):
            action_msg = "Refreshing token since it is found to be expiring soon..." if status == "expiring" else "Attempting token refresh..."
            print(f"  Action: {action_msg}")
            ok, result = _try_refresh_token(repo, verify_ssl)
            if ok:
                print(f"  Refresh: Successful")
                proc_ok = process_repo(repo, result, verify_ssl)
                if proc_ok:
                    results[repo] = "REFRESHED"
                    refreshed.append(repo)
                    continue
                else:
                    print(f"  Refresh: Token obtained but validation/storage failed, falling back to new token")

            else:
                print(f"  Refresh: No stored refresh token or refresh failed, falling back to new token")

        # Fall through: create a brand new token
        if status == "missing":
            print(f"  Action: Generating new token...")
        else:
            print(f"  Action: Creating new token (refresh unavailable)...")

        try:
            result = create_token(username, password, expires_in, refreshable, verify_ssl)
            ok = process_repo(repo, result, verify_ssl)
            if ok:
                if status == "missing":
                    results[repo] = "GENERATED"
                    generated_new.append(repo)
                else:
                    results[repo] = "REGENERATED"
                    refreshed.append(repo)
            else:
                results[repo] = "FAILED"
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results[repo] = "FAILED"

    print("\n" + "=" * 50)
    print("TOKEN STATUS REPORT")
    print("=" * 50)

    if still_valid:
        print(f"\n  Active - no action taken ({len(still_valid)}):")
        for r in still_valid:
            print(f"    - {r}")

    if refreshed:
        print(f"\n  Expired - refreshed/regenerated ({len(refreshed)}):")
        for r in refreshed:
            print(f"    - {r}")

    if generated_new:
        print(f"\n  Not found - newly generated ({len(generated_new)}):")
        for r in generated_new:
            print(f"    - {r}")

    if unreachable:
        print(f"\n  Server unreachable - kept existing token ({len(unreachable)}):")
        for r in unreachable:
            print(f"    - {r}")

    failed = [r for r, s in results.items() if s == "FAILED"]
    if failed:
        print(f"\n  Failed ({len(failed)}):")
        for r in failed:
            print(f"    - {r}")

    if not refreshed and not generated_new and not failed and not unreachable:
        print("\n  All tokens are active and valid. No action was needed.")

    return results


## ---------- Main ---------- ##

def run_auto_mode(verify_ssl: bool, extra_repos: List[str] | None = None) -> int:
    print("JFrog Token Utility (auto mode)")
    print("================================")
    print("Retrieving credentials from pass...")

    ok, username, password_or_err = retrieve_credentials_from_pass()
    if not ok:
        print(f"  ERROR: {password_or_err}")
        print("  Ensure credentials are stored in pass:")
        print(f"    pass insert {PASS_FOLDER}/{PASS_CREDENTIAL_ENTRIES['username']}")
        print(f"    pass insert {PASS_FOLDER}/{PASS_CREDENTIAL_ENTRIES['password']}")
        return 1

    print(f"  Credentials retrieved for user: {username}")

    all_repos = REPOSITORIES + [r for r in (extra_repos or []) if r not in REPOSITORIES]
    if extra_repos:
        print(f"  Additional repos: {', '.join(r for r in extra_repos if r not in REPOSITORIES) or 'none (already in defaults)'}")

    results = check_and_regenerate(
        all_repos, username, password_or_err, 604800, True, verify_ssl
    )

    success_states = ("VALID", "GENERATED", "REFRESHED", "REGENERATED", "UNREACHABLE")
    passed = all(v in success_states for v in results.values())
    return 0 if passed else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="JFrog Artifactory Token Utility")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive mode: read credentials from pass, check and refresh/regenerate tokens automatically.",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL certificate verification.",
    )
    parser.add_argument(
        "--repos",
        metavar="REPO",
        nargs="+",
        help="Additional repository names to process on top of the hard-coded defaults (auto mode only).",
    )
    args = parser.parse_args()

    verify_ssl = not args.no_verify_ssl

    if args.auto:
        return run_auto_mode(verify_ssl, extra_repos=args.repos)

    print("JFrog Token Utility")
    print("-------------------")
    print("1. Create a new token")
    print("2. Refresh an existing token")
    print("3. Test artifact download")
    print("4. Check & regenerate expired tokens")

    choice = input("Choose an option [1/2/3/4]: ").strip()
    if not args.no_verify_ssl:
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
            status, msg = check_token_status(repo, verify_ssl)
            if status == "valid":
                print(f"  Check: {msg}")
                print(f"  Action: No action required")
                results[repo] = "PASSED"
                continue
            print(f"  Mode: Manual token creation (user-initiated)")
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
            status, msg = check_token_status(repo, verify_ssl)
            if status == "valid":
                print(f"  Check: {msg}")
                print(f"  Action: No action required")
                results[repo] = "PASSED"
                continue
            print(f"  Mode: Manual token refresh (user-initiated)")
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

        results = check_and_regenerate(
            all_repos, username, password, 604800, True, verify_ssl
        )
        success_states = ("VALID", "GENERATED", "REFRESHED", "REGENERATED", "UNREACHABLE")
        passed = all(v in success_states for v in results.values())
        return 0 if passed else 2

    else:
        print("Invalid choice.")
        return 1

    print_summary(results)
    return 0 if all(v == "PASSED" for v in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
