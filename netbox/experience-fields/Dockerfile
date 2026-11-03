FROM python:3.13-slim
COPY ensure_fields.py /app/ensure_fields.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh /app/ensure_fields.py
# Always exit 0 so a failed field create does not fail `docker compose up`.
ENTRYPOINT ["/entrypoint.sh"]
