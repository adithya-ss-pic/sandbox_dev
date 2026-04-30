#!/bin/bash
##
# Copyright Koninklijke Philips N.V. 2021
#
# All rights are reserved. Reproduction or transmission in whole or in part, in
# any form or by any means, electronic, mechanical or otherwise, is prohibited
# without the prior written consent of the copyright owner.
#
# Filename: store_secrets_in_pass_for_local_builds.sh
#
##

set -e

echo "=== Store credential in pass (password store) ==="

# -------- Ensure pass is installed --------
if ! command -v pass >/dev/null 2>&1; then
  echo "ERROR: pass is not installed. Install it with: sudo apt install pass"
  exit 1
fi

# -------- Inputs --------
FOLDER="philips-artifactory"
read -p "Enter entry name: " ENTRY

if [ -z "$ENTRY" ]; then
  echo "ERROR: Entry name cannot be empty"
  exit 1
fi

# -------- Store in pass (prompts for password twice) --------
pass insert "$FOLDER/$ENTRY"
