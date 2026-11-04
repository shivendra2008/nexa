"""Vercel entry point (zero-config Flask): Vercel serves the module-level `app`.

Static assets live in public/static so Vercel's CDN can serve them directly; Flask serves the same
folder at /static when running locally.
"""
from nexa.app import create_app

app = create_app()
