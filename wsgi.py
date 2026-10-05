"""WSGI entry point: gunicorn wsgi:app."""

from campfile import create_app

app = create_app()
