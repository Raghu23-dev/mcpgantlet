"""Importable app for multi-worker uvicorn, which forks and cannot pickle a closure."""

from tests.fixtures.reference_server import create_reference_app

app = create_reference_app()
