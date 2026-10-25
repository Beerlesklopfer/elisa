#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elisa.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django konnte nicht importiert werden. Ist die venv aktiv "
            "(source .venv/bin/activate) und sind die requirements installiert?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
