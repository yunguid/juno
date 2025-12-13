"""LLM Provider abstraction for pluggable model backends"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class Provider(Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass
class LLMConfig:
    provider: Provider = Provider.ANTHROPIC
    model: str | None = None  # None = use provider default
    max_tokens: int = 2048
    temperature: float = 1.0

    def get_model(self) -> str:
        if self.model:
            return self.model
        return DEFAULT_MODELS[self.provider]


DEFAULT_MODELS = {
    Provider.ANTHROPIC: "claude-sonnet-4-5-20250929",
    Provider.OPENAI: "gpt-5.2-2025-12-11",
}

AVAILABLE_MODELS = {
    Provider.ANTHROPIC: [
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
    ],
    Provider.OPENAI: [
        "gpt-5.2-2025-12-11",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "o3",
        "o4-mini",
    ],
}


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, config: LLMConfig) -> LLMResponse:
        """Send a completion request and return the response"""
        pass


class AnthropicProvider(LLMProvider):
    def __init__(self):
        from anthropic import Anthropic
        self._client = Anthropic()

    def complete(self, system: str, user: str, config: LLMConfig) -> LLMResponse:
        model = config.get_model()
        response = self._client.messages.create(
            model=model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        return LLMResponse(
            content=response.content[0].text,
            model=model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        )


class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI()

    def complete(self, system: str, user: str, config: LLMConfig) -> LLMResponse:
        model = config.get_model()
        response = self._client.responses.create(
            model=model,
            instructions=system,
            input=user,
            max_output_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        # Extract text from output
        text = ""
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        text += content.text
        return LLMResponse(
            content=text,
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            } if response.usage else None
        )


_provider_cache: dict[Provider, LLMProvider] = {}


def get_provider(provider: Provider) -> LLMProvider:
    """Get or create a cached provider instance"""
    if provider not in _provider_cache:
        if provider == Provider.ANTHROPIC:
            _provider_cache[provider] = AnthropicProvider()
        elif provider == Provider.OPENAI:
            _provider_cache[provider] = OpenAIProvider()
        else:
            raise ValueError(f"Unknown provider: {provider}")
    return _provider_cache[provider]


# Global config - can be modified at runtime
_config = LLMConfig()


def get_config() -> LLMConfig:
    return _config


def set_config(
    provider: Provider | str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> LLMConfig:
    """Update the global LLM config"""
    global _config
    if provider is not None:
        if isinstance(provider, str):
            provider = Provider(provider)
        _config.provider = provider
    if model is not None:
        _config.model = model
    if max_tokens is not None:
        _config.max_tokens = max_tokens
    if temperature is not None:
        _config.temperature = temperature
    return _config


def complete(system: str, user: str, config: LLMConfig | None = None) -> LLMResponse:
    """Main entry point - send completion using current config"""
    cfg = config or get_config()
    provider = get_provider(cfg.provider)
    return provider.complete(system, user, cfg)
