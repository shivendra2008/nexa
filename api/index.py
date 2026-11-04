"""Vercel entry point: every request is routed here (see vercel.json) and served by the Flask app."""
from nexa.app import create_app

app = create_app()
