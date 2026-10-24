# TODO(Phindani): pin alpine by digest after review (no digest invented here).
FROM alpine:3.20
RUN apk add --no-cache net-snmp-trapd net-snmp-tools curl jq \
 && addgroup -g 10002 trapd && adduser -D -u 10002 -G trapd trapd \
 && mkdir -p /var/lib/trapd && chown trapd:trapd /var/lib/trapd
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY trap-handler.sh /usr/local/bin/trap-handler.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/trap-handler.sh
USER trapd
EXPOSE 1162/udp
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
