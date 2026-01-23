"""LLM provider abstraction for papersort.

Provides a uniform interface for LLM operations across different providers:
- MistralLLM: Mistral AI (default)
- OpenAILLM: OpenAI GPT-4

Usage:
    from models import create_llm
    
    llm = create_llm("mistral")
    result = llm.analyze_document(pdf_path, layout_content)
    is_match = llm.compare_names("JPMorgan", "J.P. Morgan")
"""

from .base import LLM, LLMError, DocumentAnalysis
from .mistral import MistralLLM
from .openai import OpenAILLM


def create_llm(provider: str = "mistral") -> LLM:
    """Create an LLM instance for the specified provider.
    
    Args:
        provider: LLM provider name ("mistral" or "openai")
        
    Returns:
        LLM instance for the specified provider
        
    Raises:
        ValueError: If provider is not recognized
    """
    provider = provider.lower()
    
    if provider == "mistral":
        return MistralLLM()
    elif provider == "openai":
        return OpenAILLM()
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            "Must be 'mistral' or 'openai'"
        )


__all__ = [
    'LLM',
    'LLMError',
    'DocumentAnalysis',
    'MistralLLM',
    'OpenAILLM',
    'create_llm',
]
