FROM docker.io/library/python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# pandoc: Dokumentgenerierung (Markdown -> .docx); gettext: .po -> .mo
RUN apt-get update \
    && apt-get install -y --no-install-recommends pandoc gettext \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /usr/share/elisa
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
RUN python manage.py compilemessages 2>/dev/null || true
# Daten (DB, media, staticfiles, incoming, RAG-Index) liegen im Volume.
RUN mkdir -p /etc/elisa /var/lib/elisa /var/log/elisa \
    && chown -R 10001:10001 /var/lib/elisa /var/log/elisa
COPY --chmod=755 packaging/container-entrypoint.sh /usr/local/bin/elisa-entrypoint
USER 10001:10001
EXPOSE 8088 8765
ENTRYPOINT ["/usr/local/bin/elisa-entrypoint"]
CMD ["web"]
