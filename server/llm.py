"""LLM integration for sample generation"""
import json
import uuid
import time
from .models import Sample, Layer, Note, SoundType
from .logger import get_logger
from .llm_providers import complete, LLMConfig

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


LAYER_GUIDELINES = {
    SoundType.PAD: """PAD LAYER GUIDELINES:
- Octaves 3-5 (C3 to B5)

RICH EMOTIONAL CHORDS:
- Use 4-5 note voicings: 9ths, maj9, min9, add9, 11ths
- Example Cmin9: ["C3", "Eb4", "G4", "Bb4", "D5"]
- Example Fmaj9: ["F3", "A4", "C5", "E5", "G5"]
- Spread voicings across octaves for lush sound

EMOTIONAL PROGRESSIONS:
- i - VI - III - VII (minor epic)
- I - V - vi - IV (emotional pop)
- ii - V - I - vi (jazz emotional)
- Use chromatic mediants: C to Ab, C to E major
- Borrow from parallel minor/major for color

MOVEMENT AND FEEL:
- Let chords breathe - long sustains (2-4 beats)
- Smooth voice leading between chords
- Build emotional arc: tension -> release -> tension
- End on unresolved chord for longing feel""",

    SoundType.LEAD: """LEAD MELODY GUIDELINES:
- Octaves 4-6 (C4 to B6)

OCCASIONAL GRACE NOTES (USE SPARINGLY):
- Only 1-2 grace notes per 4 bars MAX
- Place on downbeats of new phrases only (beat 1 or 5 or 9)
- Grace note must be a half-step or whole-step from target
- Duration: exactly 0.125 beats, velocity: 50
- Example: one D5 grace note at 0.875 -> C5 at 1.0
- DO NOT put grace notes on every note - ruins the feel

ARPEGGIATED PATTERNS:
- Break chords into flowing arpeggios
- Example: instead of one note, play C5->E5->G5->E5 as 16ths
- Mix arp directions: up, down, up-down, random
- Weave arpeggios around the chord tones

VARY NOTE LENGTHS - CRITICAL!
- Mix: 16th notes (0.25), 8ths (0.5), quarters (1), half (2)
- Example rhythm: 0.25, 0.25, 0.5, 1, 0.25, 0.25, 0.25, 0.5
- NEVER make all notes the same duration
- Quick runs followed by held notes

DYNAMICS - NOT SO LOUD:
- Velocity range: 50-90 (NOT 100-127)
- Soft arps: 50-65
- Melodic peaks: 80-90
- Grace notes should be softer (40-60)
- Vary EVERY note's velocity slightly

PHRASING:
- 2-bar phrases with space between
- Rise and fall in pitch
- End phrases on chord tones""",

    SoundType.BASS: """BASS LAYER GUIDELINES:
- Octaves 1-3 (C1 to B3)

FOLLOW THE CHORDS - BE SUPPORTIVE:
- Play the ROOT note of whatever chord the pad is playing
- When pad plays Cmin9, bass plays C. When pad plays Fmaj, bass plays F.
- Bass exists to SUPPORT the harmony, not to be interesting
- NO fancy patterns, NO showing off, NO melodic movement

SIMPLE AND SLOW:
- One note per chord change (often one note per bar or two)
- Use whole notes (4 beats) or half notes (2 beats) ONLY
- NO eighth notes, NO sixteenth notes, NO syncopation
- Just the root, held long

EXAMPLE FOR 4 BARS:
- Bar 1: C2 whole note (4 beats)
- Bar 2: Ab1 whole note (4 beats)
- Bar 3: Eb2 whole note (4 beats)
- Bar 4: Bb1 whole note (4 beats)

VELOCITY:
- Keep consistent: 75-85
- No variation needed - steady foundation"""
}

SINGLE_LAYER_SYSTEM = """You are a music production AI creating emotional, expressive music.

Output ONLY valid JSON (no markdown):
{{"id": "id", "name": "description", "sound": "{sound_type}", "notes": [{{"pitch": "C4", "start": 0, "duration": 2, "velocity": 70}}]}}

Note format:
- pitch: "C4" for single notes, ["C4", "E4", "G4", "Bb4", "D5"] for rich chords
- start: beat number (0, 0.25, 0.5, 1, 1.5, 2.5, etc)
- duration: VARY THIS! Use 0.25, 0.5, 1, 2, 4 - mix short and long
- velocity: 50-90 range (NOT too loud, leave headroom)

CRITICAL RULES:
- For LEAD: use arpeggios, vary note lengths (0.25 to 2), keep velocity 50-85
- For PAD: use 4-5 note chords (9ths, 11ths), emotional progressions
- For BASS: keep it simple and supportive, mostly roots, long notes
- NEVER make all notes the same duration - this sounds robotic
- VARY velocity note-to-note for human feel

{layer_guidelines}"""


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

    system = SINGLE_LAYER_SYSTEM.format(
        sound_type=sound_type.value,
        layer_guidelines=LAYER_GUIDELINES[sound_type]
    )

    user_prompt = f"""Create a {sound_type.value} layer for this sample:

Style/Vibe: {prompt}
Key: {key}
BPM: {bpm}
Length: {bars} bars ({bars * 4} beats total)
{build_layer_context(existing_layers or [])}

Generate the {sound_type.value} layer JSON:"""

    response = complete(system, user_prompt, config)

    elapsed = time.time() - start_time
    log.info(f"LLM responded in {elapsed:.1f}s (model: {response.model})")
    log.debug(f"Raw response: {response.content[:200]}...")

    json_str = extract_json(response.content)
    log.debug(f"Parsing JSON: {json_str[:100]}...")

    try:
        layer_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e}")
        log.error(f"JSON string was: {json_str[:500]}")
        raise

    layer = parse_layer(layer_data, sound_override=sound_type)
    log.info(f"Generated {sound_type.value}: '{layer.name}' ({len(layer.notes)} notes)")
    return layer


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
    data = json.loads(json_str)

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

Rules for notes:
- pitch: string "C4" OR array ["C4", "E4", "G4"] for chords
- start: beat number (0, 1, 2.5, etc)
- duration: beats (0.5, 1, 2, 4, etc)
- velocity: 1-127

Important:
- Keep the exact same layer IDs from the input
- Only include layers that have feedback (not "No changes requested")
- Ensure all layers work together musically"""


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
