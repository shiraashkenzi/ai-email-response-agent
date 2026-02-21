"""Main entry point for AI Email Response Agent CLI."""

import logging
import sys

from email_agent.cli import CLI
from email_agent.config import (
    get_gmail_credentials_path,
    get_gmail_token_path,
    get_openai_api_key,
    get_openai_model,
)
from email_agent.gmail_service import GmailService, authenticate_gmail
from email_agent.llm_service import LLMService

# Application logs at INFO; external libraries at WARNING to reduce noise
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
# Ensure our package logs are visible
logging.getLogger("email_agent").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Orchestrate Gmail and LLM services and run the CLI.

    Loads configuration, authenticates with Gmail, initializes the LLM service,
    and runs the interactive CLI. Exits with appropriate codes on configuration
    errors or keyboard interrupt.
    """
    openai_key = get_openai_api_key()
    if not openai_key:
        print("❌ ERROR: OPENAI_API_KEY not found in environment variables.")
        print("   Please set OPENAI_API_KEY in your .env file or environment.")
        sys.exit(1)

    token_path = get_gmail_token_path()
    credentials_path = get_gmail_credentials_path()
    model = get_openai_model()
    logger.info("Starting AI Email Response Agent")

    try:
        print("🔐 Authenticating with Gmail...")
        credentials = authenticate_gmail(
            token_path=token_path, credentials_path=credentials_path
        )
        gmail_service = GmailService(credentials)

        print("🤖 Initializing LLM service...")
        llm_service = LLMService(api_key=openai_key, model=model)

        cli = CLI(gmail_service, llm_service)
        cli.run()

    except FileNotFoundError as e:
        print(f"❌ Configuration error: {str(e)}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Configuration error: {str(e)}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        logger.exception("Unexpected error in main")
        sys.exit(1)


if __name__ == "__main__":
    main()
