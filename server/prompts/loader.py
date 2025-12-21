"""
Loader for prompt files.

Dynamically loads chord progressions and melody examples from genre-specific files.
"""

import random
from pathlib import Path
from typing import Literal

# All supported genres
GENRES = [
    "rnb", "jazz", "lofi", "ambient", "dark", "gospel",
    "pop", "cinematic", "trap", "electronic", "emotional",
    "funk", "blues", "classical", "indie", "metal",
    "reggae", "latin", "country", "disco", "synthwave",
    "house", "techno", "dubstep", "drill", "afrobeat",
    "bossa", "fusion", "prog", "grunge", "punk",
]

LayerType = Literal["pad", "lead", "bass"]

# Cache for loaded examples
_chord_cache: dict[str, list[str]] = {}
_melody_cache: dict[str, list[str]] = {}


def _load_examples_from_file(filepath: Path) -> list[str]:
    """Load examples from a text file, split by separator."""
    if not filepath.exists():
        return []
    
    content = filepath.read_text()
    # Split by separator line
    examples = []
    current = []
    for line in content.split('\n'):
        if line.strip() == '---':
            if current:
                examples.append('\n'.join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        examples.append('\n'.join(current).strip())
    
    return [e for e in examples if e]


def get_chord_examples(genre: str) -> list[str]:
    """Get all chord progression examples for a genre."""
    if genre in _chord_cache:
        return _chord_cache[genre]
    
    prompts_dir = Path(__file__).parent
    chord_file = prompts_dir / "chords" / f"{genre}.txt"
    
    examples = _load_examples_from_file(chord_file)
    
    # Fall back to emotional if genre not found
    if not examples and genre != "emotional":
        return get_chord_examples("emotional")
    
    _chord_cache[genre] = examples
    return examples


def get_melody_examples(genre: str) -> list[str]:
    """Get all melody examples for a genre."""
    if genre in _melody_cache:
        return _melody_cache[genre]
    
    prompts_dir = Path(__file__).parent
    melody_file = prompts_dir / "melodies" / f"{genre}.txt"
    
    examples = _load_examples_from_file(melody_file)
    
    # Fall back to emotional if genre not found
    if not examples and genre != "emotional":
        return get_melody_examples("emotional")
    
    _melody_cache[genre] = examples
    return examples


def get_random_chord_example(genre: str) -> str:
    """Get a random chord progression example for variety."""
    examples = get_chord_examples(genre)
    if not examples:
        return ""
    return random.choice(examples)


def get_random_melody_example(genre: str) -> str:
    """Get a random melody example for variety."""
    examples = get_melody_examples(genre)
    if not examples:
        return ""
    return random.choice(examples)


def get_system_prompt(layer_type: LayerType) -> str:
    """Get the system prompt for a layer type."""
    prompts_dir = Path(__file__).parent
    prompt_file = prompts_dir / "system" / f"{layer_type}.txt"
    
    if prompt_file.exists():
        return prompt_file.read_text().strip()
    
    # Fallback system prompts
    fallbacks = {
        "pad": 'Output ONLY valid JSON. No markdown. No explanation.\n\npitch = array of 4-6 notes. Root octave 3. Upper voices octave 4-5.',
        "lead": 'Output ONLY valid JSON. No markdown. No explanation.\n\npitch = single string. Range C4-C6. VARY durations. Use OFF-BEATS.',
        "bass": 'Output ONLY valid JSON. No markdown. No explanation.\n\npitch = single low note. Octave 1-2. Follow chord roots.',
    }
    return fallbacks.get(layer_type, "")


