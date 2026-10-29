FROM python:3.13-slim
RUN pip install --no-cache-dir requests==2.* pyyaml==6.*
COPY import_regions.py /app/import_regions.py
COPY regions.yaml /data/regions.yaml
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
# Always exit 0 so a failed import does not fail `docker compose up` for the rest of the stack.
ENTRYPOINT ["/entrypoint.sh"]
