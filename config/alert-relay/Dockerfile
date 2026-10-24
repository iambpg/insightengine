# TODO(Phindani): pin python image by digest after review (no digest invented here).
FROM python:3.12-alpine
RUN adduser -D -u 10003 relay
COPY relay.py /app/relay.py
USER relay
EXPOSE 8080
CMD ["python3", "/app/relay.py"]
