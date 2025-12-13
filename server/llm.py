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
- Use octaves 3-5 (C3 to B5)

CHORD QUALITY - Be creative!
- Use extended chords: maj7, min7, min9, add9, sus2, sus4
- Try unexpected movements: bVI, bVII, borrowed chords, modal interchange
- Inversions create smooth voice leading (e.g., C/E, Am/C)

TIMING - VARY THE RHYTHM! Don't make every chord the same length!
- Mix durations: some chords 2 beats, some 3 beats, some 4 beats, some 1 beat
- Create rhythmic interest with syncopation (start chords on beat 2 or the "and")
- Example rhythm pattern: | 3 beats | 1 beat | 2 beats | 2 beats | 4 beats | 4 beats |
- Let some chords breathe longer, others move quickly
- Avoid the boring pattern of 4 equal chords of 4 beats each!

VOICING - Vary the texture!
- Some chords: 3 notes (triads)
- Some chords: 4 notes (7ths, add notes)
- Some chords: 2 notes (open fifths, octaves for drama)
- Change the spacing: close voicing vs open voicing
- Move inner voices while bass stays static sometimes

DYNAMICS - Use velocity variation!
- Build intensity: start softer (vel 60-70), crescendo to louder (vel 85-100)
- Or start strong and get intimate
- Accent important chord changes with higher velocity

Think: cinematic film scores, Vangelis, Hans Zimmer - dynamic, evolving, emotional""",

    SoundType.LEAD: """LEAD MELODY GUIDELINES:
- Use octaves 4-6 (C4 to B6)
- Create a memorable, singable melodic line
- Use LEGATO phrasing - notes that connect smoothly (portamento/glide is enabled)
- Stepwise motion (2nds, 3rds) sounds great with glide, use larger intervals sparingly
- Mix sustained notes with shorter rhythmic passages
- The melody should complement the existing chords
- Think: expressive synth leads, soaring Vangelis-style melodies with smooth glides""",

    SoundType.BASS: """BASS LAYER GUIDELINES:
- Use octaves 1-3 (C1 to B3)
- Keep it simple and rhythmic
- Lock with the harmonic rhythm of the chords
- Root notes work great, occasional fifths
- Think: deep sub bass, rhythmic foundation"""
}

SINGLE_LAYER_SYSTEM = """You are a music production AI. Generate a SINGLE musical layer.

Output ONLY valid JSON for ONE layer (no markdown, no explanation):
{{
  "id": "unique-id",
  "name": "layer description",
  "sound": "{sound_type}",
  "notes": [
    {{"pitch": ["C4", "Eb4", "G4", "Bb4"], "start": 0, "duration": 3, "velocity": 65}},
    {{"pitch": ["Ab3", "C4", "Eb4"], "start": 3, "duration": 1, "velocity": 70}},
    {{"pitch": ["Bb3", "D4", "F4"], "start": 4, "duration": 2.5, "velocity": 75}},
    {{"pitch": ["G3", "Bb3", "D4", "F4"], "start": 6.5, "duration": 1.5, "velocity": 80}},
    {{"pitch": ["Ab3", "C4", "Eb4", "G4"], "start": 8, "duration": 4, "velocity": 85}}
  ]
}}

Rules:
- start: beat number (0 = first beat, can use decimals like 2.5 for offbeats)
- duration: length in beats (VARY THIS - use 1, 1.5, 2, 2.5, 3, 4 - not all the same!)
- pitch: single note "C4" or chord array ["C4", "E4", "G4"]
- velocity: 1-127 (VARY THIS for dynamics - build intensity or create movement)

IMPORTANT: Create variety! Don't use the same duration for every note. Mix up rhythms, chord sizes, and velocities.

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

    context = "\n\nEXISTING LAYERS (complement these):\n"
    for layer in existing_layers:
        notes_preview = layer.notes[:4]
        pitches = [
            n.pitch if isinstance(n.pitch, str) else "+".join(n.pitch)
            for n in notes_preview
        ]
        context += f"- {layer.sound.value}: {', '.join(pitches)}...\n"
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
