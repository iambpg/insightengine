FROM python:3.13-slim
RUN pip install --no-cache-dir requests==2.* pyyaml==6.*
COPY import_device_types.py /app/import_device_types.py
COPY entrypoint.sh /entrypoint.sh
COPY library /library
RUN chmod 755 /entrypoint.sh
# Always exit 0 so a failed import does not fail `docker compose up` for the rest of the stack.
ENTRYPOINT ["/entrypoint.sh"]
