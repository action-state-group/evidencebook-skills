#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# The multi-role testbed in one step (evidencebook-skills#382): set-up (setup.sh, which skips what is already done),
# then every role on its own screen (testbed.py up). Arguments go to testbed.py up, such as --witness local.
#
#   ~/ard-demo/evidencebook-skills/demo/ard/testbed.sh [--witness public|local|off]
#
# All of it is one function, run on the last line: bash reads the whole file first, so the set-up moving this
# checkout to its pinned commit cannot change the code that is running.
set -euo pipefail

main() {
  local demo="$HOME/ard-demo"
  local skills="$demo/evidencebook-skills"
  # the set-up leaves the witness to testbed.py up, which measures it and offers the local one when it is slow
  ARD_SETUP_WITNESS=testbed /bin/bash "$skills/demo/ard/setup.sh"
  # The three paths every demo command needs (RUNBOOK.md, "In every terminal"): the set-up just put them there.
  export ARD_EVIDENCEBOOK="$demo/evidencebook" \
    CAPSULECTL_DEAL="$HOME/.local/lib/capsulectl/plugins/capsulectl-deal" \
    CAPSULE_ENGINE="$demo/bin/capsule-engine"
  cd "$skills"
  exec "$skills/.venv/bin/python" "$skills/demo/ard/testbed.py" up "$@"
}

main "$@"
