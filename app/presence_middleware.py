"""Markiert angemeldete Nutzer bei jedem Request als „online" (für who-is-online)."""
from .presence import mark_online


class PresenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        mark_online(getattr(request, "user", None))
        return self.get_response(request)
