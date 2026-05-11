#!/bin/bash

##
# Copyright Koninklijke Philips N.V. 2026
#
# All rights are reserved. Reproduction or transmission in whole or in part, in
# any form or by any means, electronic, mechanical or otherwise, is prohibited
# without the prior written consent of the copyright owner.
#
# Filename: non_anonymous_artifactory_init.sh
# Description: 
#   Initialization script that ensures gpg, pass, GPG key, password store,
#   and Artifactory credentials are all set up before the devcontainer
#   starts.
##

set -euo pipefail

PASS_FOLDER="philips-artifactory"

# ---------- Helpers ----------

info()  { echo "[non_anonymous_init] $*"; }
error() { echo "[non_anonymous_init] ERROR: $*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

# Detect the package manager available on the host/WSL
install_packages() {
    local packages=("$@")
    if command_exists apt-get; then
        sudo apt-get update -qq && sudo apt-get install -y -qq "${packages[@]}"
    elif command_exists dnf; then
        sudo dnf install -y -q "${packages[@]}"
    elif command_exists yum; then
        sudo yum install -y -q "${packages[@]}"
    elif command_exists pacman; then
        sudo pacman -Sy --noconfirm "${packages[@]}"
    else
        error "No supported package manager found (apt, dnf, yum, pacman)."
        error "Please install the following packages manually: ${packages[*]}"
        exit 1
    fi
}

# ---------- Step 1: Ensure gpg and pass are installed ----------

ensure_packages_installed() {
    local missing=()

    if ! command_exists gpg; then
        missing+=(gnupg)
    fi
    if ! command_exists pass; then
        missing+=(pass)
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        info "Installing missing packages: ${missing[*]} ..."
        install_packages "${missing[@]}"
        info "Packages installed successfully."
    else
        info "gpg and pass are already installed."
    fi
}

# ---------- Step 2: Ensure a GPG key exists ----------

get_gpg_key_id() {
    # Returns the long key ID of the first secret key, or empty string if none exist.
    # '|| true' prevents grep's non-zero exit code from aborting the script under set -e.
    gpg --list-secret-keys --keyid-format long 2>/dev/null \
        | grep -E '^sec' \
        | head -n1 \
        | sed -E 's|^sec\s+[^/]+/([A-F0-9]+)\s.*|\1|' \
        || true
}

ensure_gpg_key() {
    local key_id
    key_id=$(get_gpg_key_id)

    if [ -n "$key_id" ]; then
        info "Found existing GPG key: $key_id"
        return
    fi

    info "No GPG secret key found. A new key will be generated."
    echo ""

    read -rp "Enter your full name (for GPG key): " gpg_name
    if [ -z "$gpg_name" ]; then
        error "Name cannot be empty."
        exit 1
    fi

    read -rp "Enter your email address (for GPG key): " gpg_email
    if [ -z "$gpg_email" ]; then
        error "Email cannot be empty."
        exit 1
    fi

    # Use a passphrase for the GPG key
    local gpg_passphrase gpg_passphrase_confirm
    while true; do
        read -rsp "Enter passphrase for the new GPG key: " gpg_passphrase
        echo ""
        if [ -z "$gpg_passphrase" ]; then
            error "Passphrase cannot be empty."
            continue
        fi
        read -rsp "Confirm passphrase: " gpg_passphrase_confirm
        echo ""
        if [ "$gpg_passphrase" != "$gpg_passphrase_confirm" ]; then
            error "Passphrases do not match. Please try again."
            continue
        fi
        break
    done

    info "Generating GPG key (this may take a moment)..."

    # Generate key non-interactively using batch mode
    gpg --batch --gen-key <<EOF
%no-protection
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: ${gpg_name}
Name-Email: ${gpg_email}
Expire-Date: 0
%commit
EOF

    # Now set the passphrase on the key
    key_id=$(get_gpg_key_id)
    if [ -z "$key_id" ]; then
        error "GPG key generation failed."
        exit 1
    fi

    # Change passphrase from empty to the user-provided one
    echo -e "\n${gpg_passphrase}" | gpg --batch --pinentry-mode loopback \
        --command-fd 0 --passphrase "" --change-passphrase "$key_id" 2>/dev/null || true

    info "GPG key generated successfully: $key_id"
}

# ---------- Step 3: Ensure password store is initialized ----------

ensure_pass_initialized() {
    if [ -d "$HOME/.password-store" ] && [ -f "$HOME/.password-store/.gpg-id" ]; then
        info "Password store is already initialized."
        return
    fi

    local key_id
    key_id=$(get_gpg_key_id)

    if [ -z "$key_id" ]; then
        error "No GPG key found. Cannot initialize password store."
        exit 1
    fi

    info "Initializing password store with GPG key $key_id ..."
    pass init "$key_id"
    info "Password store initialized."
}

# ---------- Step 4: Ensure Artifactory credentials are stored ----------

ensure_credential_stored() {
    local entry_name="$1"
    local prompt_label="$2"
    local is_secret="${3:-true}"   # 'true' hides input (passwords); 'false' shows input (usernames)

    # Check if the entry already exists
    if pass show "${PASS_FOLDER}/${entry_name}" >/dev/null 2>&1; then
        info "Credential '${PASS_FOLDER}/${entry_name}' already exists."
        return
    fi

    info "Credential '${PASS_FOLDER}/${entry_name}' not found."
    local value
    if [ "$is_secret" = "true" ]; then
        read -rsp "Enter ${prompt_label}: " value
    else
        read -rp "Enter ${prompt_label}: " value
    fi
    echo ""

    if [ -z "$value" ]; then
        error "${prompt_label} cannot be empty."
        exit 1
    fi

    if ! printf '%s\n' "$value" | pass insert --echo --force "${PASS_FOLDER}/${entry_name}" > /dev/null 2>&1; then
        error "Failed to store credential '${PASS_FOLDER}/${entry_name}' in pass."
        error "Try running: pass insert --echo --force ${PASS_FOLDER}/${entry_name}"
        exit 1
    fi

    # Verify it was actually stored
    if ! pass show "${PASS_FOLDER}/${entry_name}" >/dev/null 2>&1; then
        error "Credential '${PASS_FOLDER}/${entry_name}' was not stored correctly."
        exit 1
    fi

    info "Credential '${PASS_FOLDER}/${entry_name}' stored successfully."
}

ensure_artifactory_credentials() {
    ensure_credential_stored "code1-id" "your Artifactory user ID (Code1 ID)" "false"
    ensure_credential_stored "code1-password" "your Artifactory password" "true"
}

# ---------- Step 5: Verify GPG agent can decrypt ----------

REQUIRED_PASS_ENTRIES=("code1-id" "code1-password")

verify_pass_access() {
    info "Verifying pass can decrypt credentials..."
    for entry in "${REQUIRED_PASS_ENTRIES[@]}"; do
        if ! pass show "${PASS_FOLDER}/${entry}" >/dev/null 2>&1; then
            error "Cannot decrypt '${PASS_FOLDER}/${entry}'. Check your GPG passphrase / agent."
            error "You may need to run: gpg-connect-agent reloadagent /bye"
            exit 1
        fi
    done
    info "Credential access verified."
}

# ---------- Main ----------

main() {
    info "=== Running the initial setup requirements for non anonymous artifactory access ==="
    echo ""
    ensure_packages_installed
    ensure_gpg_key
    ensure_pass_initialized
    ensure_artifactory_credentials
    verify_pass_access
    echo ""
    info "=== Initial setup for non anonymous artifactory access complete. Credentials are ready. ==="
}

main "$@"
