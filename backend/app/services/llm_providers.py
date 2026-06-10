"""
LLM Provider Abstraction Layer

Provides a unified interface for different LLM providers (Ollama, OpenAI, Anthropic, vLLM).
Each provider is wrapped in a class that implements the generate() method.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str, model: str, timeout: int = 120, max_tokens: int = 4096) -> str:
        """
        Generate text using the LLM.

        Args:
            prompt: The input prompt
            model: The model name/ID
            timeout: Request timeout in seconds
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response

        Raises:
            Exception: If generation fails
        """
        pass


class OllamaProvider(LLMProvider):
    """Provider for Ollama (local LLM)."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama provider.

        Args:
            base_url: Base URL for Ollama API (default: localhost:11434)
        """
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, model: str, timeout: int = 120, max_tokens: int = 4096) -> str:
        """
        Generate text using Ollama.

        Args:
            prompt: The input prompt
            model: The model name (e.g., 'llama3', 'mistral')
            timeout: Request timeout in seconds
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        import requests

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()

        result = response.json()
        return result.get("response", "")


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI (GPT models)."""

    def __init__(self, api_key: str):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
        """
        import openai
        self.client = openai.OpenAI(api_key=api_key)

    def generate(self, prompt: str, model: str, timeout: int = 120, max_tokens: int = 4096) -> str:
        """
        Generate text using OpenAI.

        Args:
            prompt: The input prompt
            model: The model name (e.g., 'gpt-4o-mini', 'gpt-4-turbo')
            timeout: Request timeout in seconds
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content or ""


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic (Claude models)."""

    def __init__(self, api_key: str):
        """
        Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
        """
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str, model: str, timeout: int = 120, max_tokens: int = 4096) -> str:
        """
        Generate text using Anthropic.

        Args:
            prompt: The input prompt
            model: The model name (e.g., 'claude-sonnet-4-6', 'claude-opus-4-6')
            timeout: Request timeout in seconds
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )

        return response.content[0].text if response.content else ""


class VLLMProvider(LLMProvider):
    """Provider for self-hosted vLLM fleet (OpenAI-compatible API, no auth required)."""

    def __init__(self, base_url: str = "http://localhost:8100"):
        import os
        import openai
        api_base = base_url.rstrip("/")
        if not api_base.endswith("/v1"):
            api_base = f"{api_base}/v1"
        # vLLM sidecar doesn't require auth; openai client requires a non-empty string
        api_key = os.environ.get("VLLM_API_KEY", "no-auth")
        self.client = openai.OpenAI(base_url=api_base, api_key=api_key)

    def generate(self, prompt: str, model: str, timeout: int = 120, max_tokens: int = 4096) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def describe_image(self, image_url: str, model: str, timeout: int = 30) -> str:
        """Send a multimodal request and return a 1-2 sentence image description.

        Returns "" on any error — never raises.
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this video frame from a technical presentation. Identify the main topic, any visible code snippets, diagrams, or key bullet points. Provide a 2-sentence technical summary."},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
                timeout=timeout,
                max_tokens=512,
            )
            return response.choices[0].message.content or ""
        except Exception:
            return ""


# Default models per provider
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "ollama": None,  # Falls back to settings.ollama.model_name
    "vllm": "gemma4-31b",
}


def build_provider(
    provider_name: str,
    api_key: str | None = None,
    ollama_base_url: str = "http://localhost:11434",
) -> LLMProvider:
    """
    Factory function to build an LLM provider.

    Args:
        provider_name: Name of the provider ("anthropic", "openai", "ollama", "vllm")
        api_key: API key (required for anthropic/openai, ignored for ollama/vllm)
        ollama_base_url: Base URL for Ollama or vLLM sidecar (e.g. http://10.255.150.36:8100)

    Returns:
        An instance of the appropriate LLMProvider subclass

    Raises:
        ValueError: If provider_name is unknown or required api_key is missing
    """
    provider_name = provider_name.lower()

    if provider_name == "anthropic":
        if not api_key:
            raise ValueError("api_key is required for Anthropic provider")
        return AnthropicProvider(api_key)

    elif provider_name == "openai":
        if not api_key:
            raise ValueError("api_key is required for OpenAI provider")
        return OpenAIProvider(api_key)

    elif provider_name == "ollama":
        return OllamaProvider(ollama_base_url)

    elif provider_name == "vllm":
        return VLLMProvider(ollama_base_url)

    else:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            "Must be one of: 'anthropic', 'openai', 'ollama', 'vllm'"
        )
