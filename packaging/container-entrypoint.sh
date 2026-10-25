#!/bin/sh
# Startet je nach Argument den Web-, MCP- oder Supervisor-Prozess.
set -eu
case "${1:-web}" in
  web)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    exec daphne -b 0.0.0.0 -p 8088 elisa.asgi:application ;;
  mcp)
    export MCP_HOST="${MCP_HOST:-0.0.0.0}" MCP_PORT="${MCP_PORT:-8765}"
    exec python -m mcp_server.server ;;
  worker)
    exec python manage.py run_supervisor ;;
  *)
    exec "$@" ;;
esac
