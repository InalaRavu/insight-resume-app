"""Environment loading.

Import this module before reading any os.getenv() at module scope.

Modules like auth.py and llm.py evaluate configuration constants at import time,
and those imports run before the application module body does. Calling
load_dotenv() from the application would therefore be too late -- the constants
would already have been frozen from an unpopulated environment. Loading here, at
the bottom of the import graph, guarantees .env is in place first.
"""
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

# Real environment variables win over .env, so container/App Service settings
# always override a stray local file.
load_dotenv(dotenv_path=ENV_PATH, override=False)
