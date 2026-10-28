#!/bin/sh
# The importer may exit non-zero. Compose must still bring the rest of the stack up.
set -u
python /app/import_device_types.py "$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo "device-types import exited ${code}; the rest of the stack is not stopped"
fi
exit 0
