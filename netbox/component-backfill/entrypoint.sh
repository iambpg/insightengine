#!/bin/sh
# The backfill may exit non-zero. Compose must still bring the rest of the stack up.
set -u
python /app/backfill_components.py "$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo "component backfill exited ${code}; the rest of the stack is not stopped"
fi
exit 0
