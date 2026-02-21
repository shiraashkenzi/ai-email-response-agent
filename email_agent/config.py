"""Configuration module: loads .env and exposes environment settings."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root (parent of this package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def get_openai_api_key() -> Optional[str]:
    """Return OpenAI API key from environment.

    Returns:
        The API key string, or None if not set.
    """
    return os.getenv("OPENAI_API_KEY")


def get_openai_model() -> str:
    """Return OpenAI model name from environment.

    Returns:
        Model name; defaults to 'gpt-4o-mini' if OPENAI_MODEL is not set.
        Use gpt-4o or gpt-4 if your account has access.
    """
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_gmail_token_path() -> str:
    """Return path to Gmail OAuth token file.

    Returns:
        Path string; defaults to 'token.json' if GMAIL_TOKEN_PATH is not set.
    """
    return os.getenv("GMAIL_TOKEN_PATH", "token.json")


def get_gmail_credentials_path() -> str:
    """Return path to Gmail OAuth credentials JSON file.

    Returns:
        Path string; defaults to 'credentials.json' if not set.
    """
    return os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")


def get_project_root() -> Path:
    """Return the project root directory.

    Returns:
        Path to the project root.
    """
    return _PROJECT_ROOT
