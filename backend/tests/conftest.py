"""Loaded by pytest before any test module, so settings are cached with the test DB, never the dev DB."""

import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ANTHROPIC_API_KEY"] = ""  # tests never call a model
os.environ["GEMINI_API_KEY"] = ""
