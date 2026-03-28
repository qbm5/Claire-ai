"""
xAI Grok LLM provider implementation.

Grok uses an OpenAI-compatible API at https://api.x.ai/v1,
so this provider simply extends OpenAIProvider with a different base URL.

IMPORTANT: Not fully tested yet, so use with caution and report any issues.
"""

import logging

import openai

from services.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class GrokProvider(OpenAIProvider):
    """xAI Grok provider — OpenAI-compatible API at api.x.ai."""

    def __init__(self, api_key: str):
        # Skip OpenAIProvider.__init__ and set client directly with custom base_url
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        logger.info("[Grok] Provider initialized")
