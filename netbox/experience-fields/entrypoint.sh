#!/bin/sh
# The field ensure may exit non-zero. Compose must still bring the rest of the stack up.
set -u
python /app/ensure_fields.py "$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo "experience fields exited ${code}; the rest of the stack is not stopped"
fi
exit 0
