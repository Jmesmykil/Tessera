#!/bin/bash
# Serialise Blender on this host, and never let one outlive its caller.
#
# Two failures produced this file, both silent. Concurrent headless EEVEE contexts
# on this box HANG rather than fail — three of them sat for 38 minutes on a 12 MB
# asset. And a Blender launched over SSH whose caller dies is left writing into a
# pipe with no reader: one thread, sleeping, 0.1% CPU, holding the GPU forever.
# Neither errors. Both look like an application that is merely thinking.
#
# So: one at a time, and a hard ceiling on any single run. `timeout --kill-after`
# guarantees an orphan dies even if it is ignoring TERM, and stdout goes to a log
# rather than an inherited pipe that can vanish underneath it.
#
#   gpu_lock.sh <timeout-seconds> <command...>
set -uo pipefail
TIMEOUT="${1:-1800}"; shift

LOCK="/tmp/tessera-blender.lock"
LOG_DIR="${HOME}/Tessera/out/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/blender-$$.log"

exec 9>"$LOCK"
if ! flock -w "$TIMEOUT" 9; then
  echo "gpu_lock: another Blender held the GPU for more than ${TIMEOUT}s" >&2
  echo "gpu_lock: holder -> $(fuser -v "$LOCK" 2>&1 | tail -1)" >&2
  exit 75
fi

# The log is the stdout the caller would have read. Detaching from the inherited
# pipe is what stops an orphan from blocking on a reader that no longer exists.
timeout --kill-after=30s "${TIMEOUT}s" "$@" > "$LOG" 2>&1
status=$?
cat "$LOG"
if [ $status -eq 124 ] || [ $status -eq 137 ]; then
  echo "gpu_lock: killed after ${TIMEOUT}s — this asset did not finish" >&2
fi
exit $status
