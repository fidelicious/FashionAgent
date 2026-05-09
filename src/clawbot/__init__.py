"""
Clawbot — local-only personal fashion assistant.

This package is the application layer that runs inside the `clawbot` container.
External services (Ollama, the host filesystem) are reached via well-defined
adapters in their own submodules; the core domain (profile, wardrobe, outfits)
stays free of I/O so it can be unit-tested cheaply.

Submodules
----------
config     : pydantic-validated config loader (Step 2)
db         : SQLite + sqlite-vec layer (Step 3)
profile    : user profile CRUD (Step 4)
vision     : image pipeline (Step 5)
discord    : Discord bot (Steps 6-7)
inbox      : auto-ingestion (Steps 8-9)
outfits    : recommendation engine (Steps 10-13)
scheduler  : APScheduler wiring
main       : process entry point
"""

__version__ = "0.1.0"
