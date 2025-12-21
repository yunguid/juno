"""
Prompt library for LLM music generation.

This module provides genre-specific chord progressions and melody examples
organized into separate files for easy maintenance and extension.
"""

from .loader import (
    get_chord_examples,
    get_melody_examples,
    get_random_chord_example,
    get_random_melody_example,
    get_system_prompt,
    GENRES,
)

__all__ = [
    "get_chord_examples",
    "get_melody_examples", 
    "get_random_chord_example",
    "get_random_melody_example",
    "get_system_prompt",
    "GENRES",
]


