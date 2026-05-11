#!/bin/bash

##
# Copyright Koninklijke Philips N.V. 2021
#
# All rights are reserved. Reproduction or transmission in whole or in part, in
# any form or by any means, electronic, mechanical or otherwise, is prohibited
# without the prior written consent of the copyright owner.
#
# Filename: load_credentials_from_pass.sh
# Description: Load credentials from pass (password store) into environment variables
##

set -e

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced, not executed directly."
    echo "Usage: source ${BASH_SOURCE[0]}"
    exit 1
fi

get_credential() {
    local username="$1"
    local password
    password=$(pass show "philips-artifactory/$username" 2>&1)
    if [ $? -ne 0 ] || [ -z "$password" ]; then
        echo "ERROR: No credential found for artifactory/$username" >&2
        return 1
    fi
    echo "$password"
}

echo "Loading credentials from pass..."

# Run the token utility in auto mode to check/refresh/regenerate tokens
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/create_jfrog_artifactory_token.py" --auto
if [ $? -ne 0 ]; then
    echo "WARNING: Token auto-refresh encountered errors (see above). Proceeding with available tokens."
fi

export RT_PYTHON_REMOTE_USER=$(get_credential "code1-id")
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to load RT_PYTHON_REMOTE_USER"
    return 1
fi

export RT_PYTHON_REMOTE_TOKEN=$(get_credential "dps-python-remote-reference-token")
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to load RT_PYTHON_REMOTE_TOKEN"
    return 1
fi

export RT_SGSE_MAVEN_VIRTUAL_TOKEN=$(get_credential "dps-sgse-maven-virtual-reference-token")
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to load RT_SGSE_MAVEN_VIRTUAL_TOKEN"
    return 1
fi

echo "Credentials loaded successfully"
