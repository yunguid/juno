"""LLM integration for sample generation"""
import json
import uuid
import time
import random
from .models import Sample, Layer, Note, SoundType
from .logger import get_logger
from .llm_providers import complete, LLMConfig
from .prompts import get_random_chord_example, get_random_melody_example, get_system_prompt

log = get_logger("llm")


# --- Prompts ---

SYSTEM_PROMPT = """You are a music production AI that creates MIDI samples for a Yamaha synthesizer.
You output structured JSON that defines musical layers.

You have 3 sounds available:
- bass: Deep, sub-heavy bass sounds. Use octaves 1-3 (e.g., C1, E2, G2)
- pad: Lush, atmospheric pad sounds. Use octaves 3-5 (e.g., C4, E4, G4). Great for chords.
- lead: Melodic lead sounds. Use octaves 4-6 (e.g., C5, E5, G5). Great for melodies.

Musical guidelines:
- Keep everything in the same key for harmonic coherence
- Bass notes should be simple, rhythmic, and lock with the groove
- Pads provide harmonic foundation - use sustained chords
- Lead melodies should be memorable and complement the harmony
- Use velocity variation (60-127) for dynamics
- Think about note spacing and rhythm

Output ONLY valid JSON matching this exact structure:
{
  "name": "sample name",
  "bpm": 85,
  "bars": 4,
  "key": "C minor",
  "layers": [
    {
      "id": "unique-id",
      "name": "layer description",
      "sound": "bass|pad|lead",
      "notes": [
        {"pitch": "C2", "start": 0, "duration": 0.5, "velocity": 100},
        {"pitch": ["C4", "Eb4", "G4"], "start": 0, "duration": 4, "velocity": 70}
      ]
    }
  ]
}

Where:
- start: beat number (0 = first beat, 1 = second beat, etc.)
- duration: length in beats
- pitch: single note "C4" or chord ["C4", "E4", "G4"]
- velocity: 1-127 (loudness)

Be creative but musically coherent. Make it sound good!"""


# System prompts are now loaded from server/prompts/system/
# Chord examples from server/prompts/chords/
# Melody examples from server/prompts/melodies/


# --- Utilities ---

def extract_json(text: str) -> str:
    """Extract JSON from LLM response, handling markdown code blocks"""
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


def parse_notes(notes_data: list[dict]) -> list[Note]:
    """Parse note data from JSON into Note objects"""
    return [
        Note(
            pitch=n["pitch"],
            start=n["start"],
            duration=n["duration"],
            velocity=n.get("velocity", 80)
        )
        for n in notes_data
    ]


def parse_layer(data: dict, sound_override: SoundType | None = None) -> Layer:
    """Parse layer data from JSON into Layer object"""
    sound = sound_override or SoundType(data["sound"])
    use_portamento = sound == SoundType.LEAD

    return Layer(
        id=data.get("id", str(uuid.uuid4())[:8]),
        name=data.get("name", f"{sound.value} layer"),
        sound=sound,
        notes=parse_notes(data.get("notes", [])),
        portamento=use_portamento,
        portamento_time=50 if use_portamento else 0
    )


def build_layer_context(existing_layers: list[Layer]) -> str:
    """Build context string from existing layers"""
    if not existing_layers:
        return ""

    context = "\n\nEXISTING LAYERS - create COUNTERPOINT, don't copy their rhythm:\n"
    for layer in existing_layers:
        # Show timing info to help create independence
        timings = [f"{n.start}" for n in layer.notes[:6]]
        pitches = [
            n.pitch if isinstance(n.pitch, str) else "+".join(n.pitch)
            for n in layer.notes[:4]
        ]
        context += f"- {layer.sound.value}: notes at beats [{', '.join(timings)}...], pitches: {', '.join(pitches)}...\n"
    context += "\nPlay BETWEEN their notes, not ON them. Create rhythmic contrast!\n"
    return context


# --- Main Functions ---

def _detect_genre(prompt: str) -> str:
    """Detect genre/vibe from user prompt"""
    prompt_lower = prompt.lower()
    
    if any(w in prompt_lower for w in ["rnb", "r&b", "neo-soul", "soul", "frank ocean", "sza", "daniel caesar"]):
        return "rnb"
    elif any(w in prompt_lower for w in ["jazz", "bebop", "swing", "bill evans", "coltrane", "miles"]):
        return "jazz"
    elif any(w in prompt_lower for w in ["lofi", "lo-fi", "chill", "study", "relax"]):
        return "lofi"
    elif any(w in prompt_lower for w in ["ambient", "atmospheric", "ethereal", "vangelis", "blade runner", "space"]):
        return "ambient"
    elif any(w in prompt_lower for w in ["dark", "moody", "intense", "weeknd", "tense", "dramatic"]):
        return "dark"
    elif any(w in prompt_lower for w in ["gospel", "church", "uplifting", "spiritual"]):
        return "gospel"
    elif any(w in prompt_lower for w in ["pop", "catchy", "radio", "mainstream"]):
        return "pop"
    elif any(w in prompt_lower for w in ["classical", "orchestral", "cinematic", "film", "epic"]):
        return "cinematic"
    elif any(w in prompt_lower for w in ["trap", "hip-hop", "hip hop", "rap", "808"]):
        return "trap"
    elif any(w in prompt_lower for w in ["edm", "electronic", "house", "techno", "dance"]):
        return "electronic"
    else:
        return "emotional"  # default


# --- Genre Detection and Examples ---
# Chord progressions and melody examples are loaded from the modular prompt system.
# See server/prompts/ for the complete library.


def _get_layer_specific_prompt(sound_type: SoundType, prompt: str, key: str, bpm: int, bars: int, existing_layers: list[Layer] | None) -> str:
    """Build a specialized prompt for each layer type with genre awareness"""
    beats = bars * 4
    genre = _detect_genre(prompt)
    
    if sound_type == SoundType.PAD:
        chord_example = get_random_chord_example(genre)
        
        return f"""{genre.upper()} chord progression. Key: {key}. {bars} bars ({beats} beats).
Vibe: {prompt}

INSPIRATION (transpose to {key}, don't copy):
{chord_example}

Output {bars} bars of chords. Use 4-6 note voicings. Velocity 55-70."""

    elif sound_type == SoundType.LEAD:
        melody_example = get_random_melody_example(genre)
        
        # Extract chord info for melody to follow
        chord_info = ""
        if existing_layers:
            pad_layer = next((l for l in existing_layers if l.sound == SoundType.PAD), None)
            if pad_layer:
                chord_tones = []
                for n in pad_layer.notes[:6]:
                    if isinstance(n.pitch, list) and len(n.pitch) > 1:
                        chord_tones.append(f"beat {n.start}: {n.pitch[1:3]}")
                if chord_tones:
                    chord_info = "Hit these chord tones: " + ", ".join(chord_tones)
        
        return f"""{genre.upper()} melody. Key: {key}. {bars} bars ({beats} beats).
Vibe: {prompt}

INSPIRATION (adapt rhythm to your melody):
{melody_example}

{chord_info}

Output melody with VARIED rhythms (0.25, 0.5, 1, 2 beats). Use SYNCOPATION (0.5, 1.5, 2.5).
Leave SPACE. Climax in bar 3. Velocity 55-85."""

    else:  # BASS
        # Extract chord roots for bass to follow
        root_sequence = ""
        if existing_layers:
            pad_layer = next((l for l in existing_layers if l.sound == SoundType.PAD), None)
            if pad_layer:
                roots = []
                for n in pad_layer.notes[:8]:
                    if isinstance(n.pitch, list) and n.pitch:
                        root_note = n.pitch[0]
                        note_name = ''.join(c for c in root_note if not c.isdigit())
                        roots.append(f"{note_name}2 at beat {n.start}")
                    elif isinstance(n.pitch, str):
                        note_name = ''.join(c for c in n.pitch if not c.isdigit())
                        roots.append(f"{note_name}2 at beat {n.start}")
                if roots:
                    root_sequence = "Play these roots: " + ", ".join(roots[:6])
        
        return f"""Bass line. Key: {key}. {bars} bars ({beats} beats).

{root_sequence if root_sequence else "Play root notes matching the chord changes."}

Simple whole notes (4 beats). Octave 1-2. Velocity 75-85."""


def generate_single_layer(
    sound_type: SoundType,
    prompt: str,
    key: str,
    bpm: int,
    bars: int,
    existing_layers: list[Layer] | None = None,
    config: LLMConfig | None = None,
) -> Layer:
    """Generate a single layer with context of existing layers"""
    log.info(f"Generating {sound_type.value} layer...")
    start_time = time.time()

    # Use specialized system prompt for each layer type
    system = get_system_prompt(sound_type.value)
    if not system:
        raise ValueError(f"Unknown sound type: {sound_type}")

    # Build layer-specific user prompt
    user_prompt = _get_layer_specific_prompt(
        sound_type, prompt, key, bpm, bars, existing_layers
    )

    # Add context from existing layers
    if existing_layers:
        user_prompt += build_layer_context(existing_layers)

    log.debug(f"System prompt ({len(system)} chars)")
    log.debug(f"User prompt: {user_prompt[:200]}...")

    cfg = config or LLMConfig()
    response = complete(system, user_prompt, cfg)

    elapsed = time.time() - start_time
    log.info(f"LLM responded in {elapsed:.1f}s (model: {response.model})")

    try:
        json_str = extract_json(response.content)
        data = json.loads(json_str)

        layer_data = data if "notes" in data else data.get("layers", [{}])[0]
        layer = parse_layer(layer_data, sound_override=sound_type)

        log.info(f"{sound_type.value} layer generated ({len(layer.notes)} notes)")
        return layer
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        log.error(f"Failed to parse layer response: {e}")
        log.error(f"Response was: {response.content[:500]}")
        raise ValueError(f"Failed to generate {sound_type.value} layer: {e}")


def generate_sample(
    prompt: str,
    bpm: int | None = None,
    bars: int | None = None,
    config: LLMConfig | None = None,
) -> Sample:
    """Generate a full sample from a text prompt"""
    log.info("Generating full sample...")
    start_time = time.time()

    user_prompt = prompt
    if bpm:
        user_prompt += f"\nBPM: {bpm}"
    if bars:
        user_prompt += f"\nLength: {bars} bars"

    response = complete(SYSTEM_PROMPT, user_prompt, config)

    elapsed = time.time() - start_time
    log.info(f"LLM responded in {elapsed:.1f}s (model: {response.model})")

    json_str = extract_json(response.content)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error: {e}, attempting repair...")
        log.debug(f"Original JSON: {json_str[:500]}...")
        repaired = repair_truncated_json(json_str)
        try:
            data = json.loads(repaired)
            log.info("JSON repair successful")
        except json.JSONDecodeError as e2:
            log.error(f"JSON repair failed: {e2}")
            log.error(f"JSON was: {json_str[:1000]}")
            raise ValueError(f"Failed to parse LLM response: {e2}")

    layers = [parse_layer(ld) for ld in data.get("layers", [])]

    return Sample(
        id=str(uuid.uuid4())[:8],
        name=data.get("name", "Generated Sample"),
        bpm=data.get("bpm", bpm or 90),
        bars=data.get("bars", bars or 4),
        layers=layers
    )


def edit_layer(
    sample: Sample,
    layer_id: str,
    prompt: str,
    config: LLMConfig | None = None,
) -> Sample:
    """Edit a specific layer based on a prompt"""
    layer = next((l for l in sample.layers if l.id == layer_id), None)
    if not layer:
        raise ValueError(f"Layer {layer_id} not found")

    other_layers = [l for l in sample.layers if l.id != layer_id]
    context = {
        "bpm": sample.bpm,
        "bars": sample.bars,
        "current_layer": layer.model_dump(),
        "other_layers": [l.model_dump() for l in other_layers]
    }

    user_prompt = f"""The user wants to edit the "{layer.name}" layer.

Current sample context:
{json.dumps(context, indent=2)}

User request: {prompt}

Output ONLY the updated layer JSON (just the single layer, not the full sample):
{{"id": "{layer_id}", "name": "...", "sound": "{layer.sound.value}", "notes": [...]}}"""

    response = complete(SYSTEM_PROMPT, user_prompt, config)
    json_str = extract_json(response.content)
    layer_data = json.loads(json_str)

    updated_layer = parse_layer(layer_data, sound_override=layer.sound)
    updated_layer.id = layer_id  # Preserve original ID

    new_layers = [updated_layer if l.id == layer_id else l for l in sample.layers]

    return Sample(
        id=sample.id,
        name=sample.name,
        bpm=sample.bpm,
        bars=sample.bars,
        layers=new_layers
    )


def add_layer(
    sample: Sample,
    prompt: str,
    sound: SoundType,
    config: LLMConfig | None = None,
) -> Sample:
    """Add a new layer to the sample"""
    context = {
        "bpm": sample.bpm,
        "bars": sample.bars,
        "existing_layers": [l.model_dump() for l in sample.layers]
    }

    user_prompt = f"""Add a new {sound.value} layer to this sample.

Current sample context:
{json.dumps(context, indent=2)}

User request: {prompt}

The new layer should complement the existing layers. Output ONLY the new layer JSON:
{{"id": "new-id", "name": "...", "sound": "{sound.value}", "notes": [...]}}"""

    response = complete(SYSTEM_PROMPT, user_prompt, config)
    json_str = extract_json(response.content)
    layer_data = json.loads(json_str)

    new_layer = parse_layer(layer_data, sound_override=sound)

    return Sample(
        id=sample.id,
        name=sample.name,
        bpm=sample.bpm,
        bars=sample.bars,
        layers=sample.layers + [new_layer]
    )


IMPROVE_SYSTEM_PROMPT = """You are a music production AI. Improve musical layers based on user feedback.

Output ONLY valid JSON - no markdown, no explanation, no extra text.

Format:
{"layers": [{"id": "xxx", "name": "description", "sound": "pad", "notes": [{"pitch": "C4", "start": 0, "duration": 2, "velocity": 80}]}]}

LAYER-SPECIFIC IMPROVEMENT RULES:

PAD (chords):
- Use 4-6 note spread voicings
- pitch MUST be an array: ["C3", "G3", "Bb4", "D5", "Eb5"]
- Velocity: 55-75 (sit back in mix)
- Duration: 2-4 beats per chord
- Focus on voice leading and emotional progressions

LEAD (melody):
- pitch is a single string: "G5"
- Velocity: 55-90 (varied, not too loud)
- Mix note durations: 0.25, 0.5, 1, 2 beats
- Include syncopation and space
- Create melodic contour (rise and fall)

BASS:
- pitch is a single string: "C2"
- Velocity: 75-85 (consistent)
- Duration: mostly 2-4 beats (simple)
- Follow chord roots

Important:
- Keep the exact same layer IDs from the input
- Only include layers that have feedback
- Make the requested changes while keeping musicality"""


def repair_truncated_json(json_str: str) -> str:
    """Attempt to repair truncated JSON by closing open brackets"""
    # Count brackets
    open_braces = json_str.count('{') - json_str.count('}')
    open_brackets = json_str.count('[') - json_str.count(']')

    # If we're inside a string, try to close it
    if json_str.rstrip().endswith('"') is False and '"' in json_str:
        # Check if we have an unclosed string
        quote_count = json_str.count('"')
        if quote_count % 2 == 1:
            json_str = json_str.rstrip()
            if not json_str.endswith('"'):
                json_str += '"'

    # Remove trailing comma if present
    json_str = json_str.rstrip().rstrip(',')

    # Close brackets and braces
    json_str += ']' * open_brackets
    json_str += '}' * open_braces

    return json_str


def improve_layers(
    sample: Sample,
    feedback: dict[str, str],
    config: LLMConfig | None = None,
) -> Sample:
    """Improve layers based on user feedback for each layer"""
    log.info(f"Improving layers based on feedback...")
    start_time = time.time()

    # Build compact context - only include layers with feedback
    layers_context = []
    for layer in sample.layers:
        layer_feedback = feedback.get(layer.sound.value, "").strip()
        if layer_feedback:
            # Include simplified note info
            layers_context.append({
                "id": layer.id,
                "sound": layer.sound.value,
                "name": layer.name,
                "note_count": len(layer.notes),
                "feedback": layer_feedback
            })

    if not layers_context:
        log.info("No feedback provided, returning original sample")
        return sample

    user_prompt = f"""Key: {sample.key}, BPM: {sample.bpm}, Bars: {sample.bars}

Layers to improve:
{json.dumps(layers_context, indent=2)}

Generate improved layers based on feedback. Keep it musical and coherent."""

    # Use higher max_tokens for improvements
    from copy import copy
    improve_config = copy(config) if config else LLMConfig()
    improve_config.max_tokens = 4096

    response = complete(IMPROVE_SYSTEM_PROMPT, user_prompt, improve_config)

    elapsed = time.time() - start_time
    log.info(f"LLM responded in {elapsed:.1f}s (model: {response.model})")

    json_str = extract_json(response.content)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error: {e}, attempting repair...")
        try:
            repaired = repair_truncated_json(json_str)
            data = json.loads(repaired)
            log.info("JSON repair successful")
        except json.JSONDecodeError:
            log.error(f"JSON repair failed. Original: {json_str[:500]}")
            raise

    # Update layers that were improved
    improved_layers = {ld["id"]: ld for ld in data.get("layers", [])}

    new_layers = []
    for layer in sample.layers:
        if layer.id in improved_layers:
            improved_data = improved_layers[layer.id]
            new_layer = parse_layer(improved_data, sound_override=layer.sound)
            new_layer.id = layer.id  # Preserve ID
            new_layers.append(new_layer)
            log.info(f"Improved {layer.sound.value}: '{new_layer.name}'")
        else:
            new_layers.append(layer)
            log.info(f"Kept {layer.sound.value} unchanged")

    return Sample(
        id=sample.id,
        name=sample.name,
        prompt=sample.prompt,
        key=sample.key,
        bpm=sample.bpm,
        bars=sample.bars,
        layers=new_layers
    )
