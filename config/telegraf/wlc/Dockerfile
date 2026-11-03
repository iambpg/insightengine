FROM telegraf:1.38.3

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY render_wlc.py /usr/local/bin/render_wlc.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh /usr/local/bin/render_wlc.py
USER 10001:10001
ENTRYPOINT ["/entrypoint.sh"]
