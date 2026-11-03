FROM telegraf:1.38.3

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# catalog.py has to be importable as "catalog" from render_wlc.py. The compose
# mount of this directory is /etc/telegraf, which is not the script directory.
COPY catalog.py /usr/local/bin/catalog.py
COPY render_wlc.py /usr/local/bin/render_wlc.py
COPY drop-priv.sh /usr/local/bin/drop-priv.sh
COPY entrypoint.sh /entrypoint.sh
ENV PYTHONPATH=/usr/local/bin:/etc/telegraf
RUN chmod 0755 /entrypoint.sh /usr/local/bin/render_wlc.py /usr/local/bin/drop-priv.sh \
    && chmod 0644 /usr/local/bin/catalog.py
# Stay root. entrypoint.sh copies root-only secrets to mode 0400 for uid
# 10001 and drops privileges before Telegraf starts.
USER root
ENTRYPOINT ["/entrypoint.sh"]
