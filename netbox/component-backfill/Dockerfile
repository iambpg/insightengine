FROM python:3.13-slim
RUN pip install --no-cache-dir requests==2.*
COPY backfill_components.py /app/backfill_components.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
# Always exit 0 so a failed backfill does not fail `docker compose up` for the rest of the stack.
ENTRYPOINT ["/entrypoint.sh"]
