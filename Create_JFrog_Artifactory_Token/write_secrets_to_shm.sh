#!/bin/bash

##
# Copyright Koninklijke Philips N.V. 2021
#
# All rights are reserved. Reproduction or transmission in whole or in part, in
# any form or by any means, electronic, mechanical or otherwise, is prohibited
# without the prior written consent of the copyright owner.
#
# Filename: write_secrets_to_shm.sh
# Description:
#   Fetches all credentials from pass and writes each as an individual file 
#   into /dev/shm/devcontainer-secrets/ (tmpfs - RAM only,never written to disk). 
#   Intended to be called as a devcontainer initializeCommand on the host before 
#   the container starts.
#
#   docker-compose.yml in the repo then declares which of these secret files
#   it needs - each repo can use all or a subset.
#
# Usage (devcontainer.json initializeCommand):
#   "bash ${localWorkspaceFolder}/external/SGS-Tools/local-build-setup-non-anonymous-artifactory-access/write_secrets_to_shm.sh"
##

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_FOLDER="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SECRETS_DIR="/dev/shm/devcontainer-secrets"

get_credential() {
    local username="$1"
    local password
    password=$(pass show "philips-artifactory/$username" 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$password" ]; then
        echo "ERROR: No credential found for philips-artifactory/$username" >&2
        return 1
    fi
    echo "$password"
}

write_secret() {
    local filename="$1"
    local value="$2"
    local filepath="$SECRETS_DIR/$filename"
    printf '%s' "$value" > "$filepath"
    chmod 600 "$filepath"
}

echo "Writing Artifactory secrets to $SECRETS_DIR ..."

# Run the token utility in auto mode to check/refresh/regenerate tokens
if [ -f "$SCRIPT_DIR/create_jfrog_tokens.py" ]; then
    python3 "$SCRIPT_DIR/create_jfrog_tokens.py" --auto || {
        echo "WARNING: Token auto-refresh encountered errors. Proceeding with available tokens."
    }
fi

# Create secure directory in tmpfs, clearing any old secret files
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"
rm -f "$SECRETS_DIR"/*

# Fetch all known Artifactory credentials
CODE1_ID=$(get_credential 'code1-id')
SGS_LOCAL_TOKEN=$(get_credential 'dcp-sgs-local-reference-token')
SGS_DOCKER_LOCAL_TOKEN=$(get_credential 'dcp-sgs-docker-local-reference-token')
MAVEN_REMOTE_TOKEN=$(get_credential 'dps-maven-remote-reference-token')
PYTHON_REMOTE_TOKEN=$(get_credential 'dps-python-remote-reference-token')
SGSE_MAVEN_VIRTUAL_TOKEN=$(get_credential 'dps-sgse-maven-virtual-reference-token')
TEST_YUM_TOKEN=$(get_credential 'dps-test-yum-reference-token')

# Write one file per secret - repos pick which ones they need in docker-compose.yml
write_secret 'rt_code_1_user_id'                     "$CODE1_ID"
write_secret 'rt_sgs_local_reference_token'           "$SGS_LOCAL_TOKEN"
write_secret 'rt_sgs_docker_local_reference_token'    "$SGS_DOCKER_LOCAL_TOKEN"
write_secret 'rt_maven_remote_reference_token'        "$MAVEN_REMOTE_TOKEN"
write_secret 'rt_python_remote_reference_token'       "$PYTHON_REMOTE_TOKEN"
write_secret 'rt_sgse_maven_virtual_reference_token'  "$SGSE_MAVEN_VIRTUAL_TOKEN"
write_secret 'rt_test_yum_reference_token'            "$TEST_YUM_TOKEN"

echo "Successfully wrote $(ls "$SECRETS_DIR" | wc -l) secret files to $SECRETS_DIR"
echo "Location: /dev/shm (tmpfs - RAM only, never written to disk)"
echo "Permissions: directory=700, files=600"

# Write .env for docker-compose.yml so WORKSPACE_FOLDER resolves at config time
DEVCONTAINER_ENV="${WORKSPACE_FOLDER}/.devcontainer/.env"
printf 'WORKSPACE_FOLDER=%s\n' "$WORKSPACE_FOLDER" > "$DEVCONTAINER_ENV"
chmod 600 "$DEVCONTAINER_ENV"
echo "Written WORKSPACE_FOLDER to $DEVCONTAINER_ENV"
