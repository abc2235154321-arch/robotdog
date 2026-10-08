#!/usr/bin/env bash
# Isolated motor stack; same homing/feedback/timeout checks, new follower only.
set -euo pipefail
export PUPPER_FOLLOW_VARIANT=appearance
exec /bin/bash /home/pi/pupper-tests/run_voice_single_person_stack.sh "${1:-180}"
