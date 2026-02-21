"""LLM service module: OpenAI API for reply generation and improvement."""

import os
from typing import Any, Dict, List, Optional

from openai import APIError, APIConnectionError, OpenAI, RateLimitError


class LLMService:
    """Service for OpenAI API: generate and improve email replies."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        """Initialize the LLM client.

        Args:
            api_key: OpenAI API key; if None, uses OPENAI_API_KEY from environment.
            model: Model name (e.g. gpt-4o-mini, gpt-4o, gpt-4).

        Raises:
            ValueError: If no API key is available.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment variable."
            )
        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def generate_reply(
        self,
        original_email: Dict[str, Any],
        context: Optional[str] = None,
        tone: str = "professional",
        max_tokens: int = 500,
        language: str = "en",
    ) -> str:
        """Generate a reply suggestion for the given email.

        Args:
            original_email: Dict with 'from', 'subject', 'body', 'date', etc.
            context: Optional extra context for the reply.
            tone: Desired tone (e.g. professional, friendly, casual).
            max_tokens: Maximum response length in tokens.
            language: 'en' for English, 'he' for Hebrew (prompts and instructions).

        Returns:
            Generated reply body text.

        Raises:
            LLMError: If the API call fails (rate limit, connection, etc.).
        """
        try:
            prompt = self._build_reply_prompt(
                original_email, context, tone, language=language
            )
            system_content = (
                "You are a helpful email assistant that writes clear, concise, and appropriate email replies."
                if language == "en"
                else "אתה עוזר אימייל שכותב תגובות אימייל ברורות, תמציתיות ומתאימות. ענה בעברית."
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            return (content or "").strip()
        except RateLimitError as e:
            raise LLMError(f"OpenAI API rate limit exceeded: {str(e)}") from e
        except APIConnectionError as e:
            raise LLMError(f"Failed to connect to OpenAI API: {str(e)}") from e
        except APIError as e:
            raise LLMError(f"OpenAI API error: {str(e)}") from e
        except Exception as e:
            raise LLMError(f"Unexpected error generating reply: {str(e)}") from e

    def _build_reply_prompt(
        self,
        original_email: Dict[str, Any],
        context: Optional[str],
        tone: str,
        language: str = "en",
    ) -> str:
        """Build the user prompt for reply generation in the requested language.

        Args:
            original_email: Parsed email dict.
            context: Optional context string.
            tone: Requested tone.
            language: 'en' or 'he' for prompt language.

        Returns:
            Full prompt string for the API.
        """
        if language == "he":
            tone_he = {"professional": "מקצועית", "friendly": "ידידותית", "casual": "לא פורמלית"}.get(tone, "מתאימה")
            prompt = f"""צור תגובת אימייל {tone_he} לאימייל הבא:

מאת: {original_email.get('from', 'לא ידוע')}
נושא: {original_email.get('subject', 'ללא נושא')}
תאריך: {original_email.get('date', 'לא ידוע')}

גוף ההודעה:
{original_email.get('body', 'אין תוכן')}
"""
            if context:
                prompt += f"\nהקשר נוסף: {context}\n"
            prompt += "\nכתוב תגובה ברורה, תמציתית ומתאימה. אל תכלול שורת נושא או כותרות אימייל, רק את גוף התגובה."
        else:
            prompt = f"""Generate a {tone} email reply to the following email:

From: {original_email.get('from', 'Unknown')}
Subject: {original_email.get('subject', 'No Subject')}
Date: {original_email.get('date', 'Unknown')}

Body:
{original_email.get('body', 'No body content')}
"""
            if context:
                prompt += f"\nAdditional context: {context}\n"
            prompt += (
                "\nPlease write a clear, concise, and appropriate reply. "
                "Do not include the subject line or email headers, just the body text of the reply."
            )
        return prompt

    def improve_reply(
        self,
        original_reply: str,
        feedback: str,
        language: str = "en",
    ) -> str:
        """Improve a reply based on user feedback.

        Args:
            original_reply: Current reply text.
            feedback: User instructions for improvement.
            language: 'en' for English, 'he' for Hebrew prompts and response.

        Returns:
            Improved reply body text.

        Raises:
            LLMError: If the API call fails.
        """
        try:
            if language == "he":
                prompt = f"""תגובת האימייל הבאה צריכה שיפור לפי המשוב:

תגובה מקורית:
{original_reply}

משוב:
{feedback}

הנח גרסה משופרת של התגובה (בעברית)."""
                system_content = "אתה עוזר אימייל שמשפר תגובות אימייל לפי משוב. ענה בעברית."
            else:
                prompt = f"""The following email reply needs to be improved based on this feedback:

Original reply:
{original_reply}

Feedback:
{feedback}

Please provide an improved version of the reply."""
                system_content = "You are a helpful email assistant that improves email replies based on feedback."
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            return (content or "").strip()
        except RateLimitError as e:
            raise LLMError(f"OpenAI API rate limit exceeded: {str(e)}") from e
        except APIConnectionError as e:
            raise LLMError(f"Failed to connect to OpenAI API: {str(e)}") from e
        except APIError as e:
            raise LLMError(f"OpenAI API error: {str(e)}") from e
        except Exception as e:
            raise LLMError(f"Failed to improve reply: {str(e)}") from e

    def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """Run a chat completion with tool definitions; used by the agent loop.

        Args:
            messages: List of OpenAI message dicts (role, content; may include tool_calls and tool role).
            tools: OpenAI tools format (list of {"type": "function", "function": {...}}).
            max_tokens: Max tokens for the response.

        Returns:
            The assistant message dict with "content" (optional) and "tool_calls" (optional).

        Raises:
            LLMError: If the API call fails (rate limit, connection, context length, etc.).
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=max_tokens,
            )
            msg = response.choices[0].message
            out: Dict[str, Any] = {}
            if msg.content:
                out["content"] = msg.content
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                out["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            return out
        except RateLimitError as e:
            raise LLMError(f"OpenAI API rate limit exceeded: {str(e)}") from e
        except APIConnectionError as e:
            raise LLMError(f"Failed to connect to OpenAI API: {str(e)}") from e
        except APIError as e:
            raise LLMError(f"OpenAI API error: {str(e)}") from e
        except Exception as e:
            raise LLMError(f"Unexpected error in completion: {str(e)}") from e


class LLMError(Exception):
    """Base exception for LLM service errors."""
