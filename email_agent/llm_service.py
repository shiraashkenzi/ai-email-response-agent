"""LLM Service Module - Handles OpenAI API calls"""

import os
from typing import Optional

from openai import APIError, APIConnectionError, OpenAI, RateLimitError


class LLMService:
    """Service for interacting with OpenAI API"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        """
        Initialize LLM service
        
        Args:
            api_key: OpenAI API key (if None, reads from OPENAI_API_KEY env var)
            model: Model name to use (default: gpt-4)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
    
    def generate_reply(
        self,
        original_email: dict,
        context: Optional[str] = None,
        tone: str = "professional",
        max_tokens: int = 500
    ) -> str:
        """
        Generate a reply suggestion for an email
        
        Args:
            original_email: Dictionary with 'from', 'subject', 'body', etc.
            context: Optional additional context for the reply
            tone: Desired tone (professional, friendly, casual, etc.)
            max_tokens: Maximum tokens for the response
            
        Returns:
            Generated reply text
            
        Raises:
            LLMError: If API call fails
        """
        try:
            # Build prompt
            prompt = self._build_reply_prompt(original_email, context, tone)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful email assistant that writes clear, concise, and appropriate email replies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=max_tokens
            )
            
            reply = response.choices[0].message.content.strip()
            return reply
            
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
        original_email: dict,
        context: Optional[str],
        tone: str
    ) -> str:
        """Build the prompt for reply generation"""
        prompt = f"""Generate a {tone} email reply to the following email:

From: {original_email.get('from', 'Unknown')}
Subject: {original_email.get('subject', 'No Subject')}
Date: {original_email.get('date', 'Unknown')}

Body:
{original_email.get('body', 'No body content')}
"""
        
        if context:
            prompt += f"\nAdditional context: {context}\n"
        
        prompt += """
Please write a clear, concise, and appropriate reply. Do not include the subject line or email headers, just the body text of the reply."""
        
        return prompt
    
    def improve_reply(self, original_reply: str, feedback: str) -> str:
        """
        Improve a reply based on user feedback
        
        Args:
            original_reply: The original reply text
            feedback: User feedback on how to improve it
            
        Returns:
            Improved reply text
            
        Raises:
            LLMError: If API call fails
        """
        try:
            prompt = f"""The following email reply needs to be improved based on this feedback:

Original reply:
{original_reply}

Feedback:
{feedback}

Please provide an improved version of the reply."""
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful email assistant that improves email replies based on feedback."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            improved_reply = response.choices[0].message.content.strip()
            return improved_reply
            
        except Exception as e:
            raise LLMError(f"Failed to improve reply: {str(e)}") from e


class LLMError(Exception):
    """Base exception for LLM service errors"""
    pass
