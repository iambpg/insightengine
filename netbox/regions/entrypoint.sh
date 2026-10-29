#!/bin/sh
# The importer may exit non-zero. Compose must still bring the rest of the stack up.
set -u
python /app/import_regions.py "$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo "regions import exited ${code}; the rest of the stack is not stopped"
fi
exit 0
