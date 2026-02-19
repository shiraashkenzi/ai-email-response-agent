"""Configuration - Loads and exposes environment settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of this package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def get_openai_api_key() -> str | None:
    """Return OpenAI API key from environment. None if not set."""
    return os.getenv("OPENAI_API_KEY")


def get_openai_model() -> str:
    """Return OpenAI model name. Default: gpt-4."""
    return os.getenv("OPENAI_MODEL", "gpt-4")


def get_gmail_token_path() -> str:
    """Return path to Gmail token file. Default: token.json."""
    return os.getenv("GMAIL_TOKEN_PATH", "token.json")


def get_gmail_credentials_path() -> str:
    """Return path to Gmail OAuth credentials file. Default: credentials.json."""
    return os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")


def get_project_root() -> Path:
    """Return project root directory."""
    return _PROJECT_ROOT
