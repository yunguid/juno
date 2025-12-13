"""LLM integration for sample generation using Claude"""
import os
import json
import uuid
from anthropic import Anthropic
from .models import Sample, Layer, Note, SoundType


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


def generate_sample(prompt: str, bpm: int | None = None, bars: int | None = None) -> Sample:
    """Generate a sample from a text prompt using Claude"""
    client = Anthropic()

    user_prompt = prompt
    if bpm:
        user_prompt += f"\nBPM: {bpm}"
    if bars:
        user_prompt += f"\nLength: {bars} bars"

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )

    # Extract JSON from response
    response_text = response.content[0].text

    # Try to parse JSON (handle markdown code blocks)
    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0].strip()
    else:
        json_str = response_text.strip()

    data = json.loads(json_str)

    # Build Sample object
    sample_id = str(uuid.uuid4())[:8]

    layers = []
    for layer_data in data.get("layers", []):
        notes = []
        for note_data in layer_data.get("notes", []):
            notes.append(Note(
                pitch=note_data["pitch"],
                start=note_data["start"],
                duration=note_data["duration"],
                velocity=note_data.get("velocity", 80)
            ))

        layers.append(Layer(
            id=layer_data.get("id", str(uuid.uuid4())[:8]),
            name=layer_data.get("name", layer_data["sound"]),
            sound=SoundType(layer_data["sound"]),
            notes=notes
        ))

    return Sample(
        id=sample_id,
        name=data.get("name", "Generated Sample"),
        bpm=data.get("bpm", bpm or 90),
        bars=data.get("bars", bars or 4),
        layers=layers
    )


def edit_layer(sample: Sample, layer_id: str, prompt: str) -> Sample:
    """Edit a specific layer based on a prompt"""
    client = Anthropic()

    # Find the layer
    layer = next((l for l in sample.layers if l.id == layer_id), None)
    if not layer:
        raise ValueError(f"Layer {layer_id} not found")

    # Get other layers for context
    other_layers = [l for l in sample.layers if l.id != layer_id]
    context = {
        "bpm": sample.bpm,
        "bars": sample.bars,
        "current_layer": layer.model_dump(),
        "other_layers": [l.model_dump() for l in other_layers]
    }

    edit_prompt = f"""The user wants to edit the "{layer.name}" layer.

Current sample context:
{json.dumps(context, indent=2)}

User request: {prompt}

Output ONLY the updated layer JSON (just the single layer, not the full sample):
{{"id": "{layer_id}", "name": "...", "sound": "{layer.sound.value}", "notes": [...]}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": edit_prompt}
        ]
    )

    response_text = response.content[0].text

    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0].strip()
    else:
        json_str = response_text.strip()

    layer_data = json.loads(json_str)

    # Build updated layer
    notes = []
    for note_data in layer_data.get("notes", []):
        notes.append(Note(
            pitch=note_data["pitch"],
            start=note_data["start"],
            duration=note_data["duration"],
            velocity=note_data.get("velocity", 80)
        ))

    updated_layer = Layer(
        id=layer_id,
        name=layer_data.get("name", layer.name),
        sound=layer.sound,  # Keep same sound type
        notes=notes
    )

    # Replace layer in sample
    new_layers = [updated_layer if l.id == layer_id else l for l in sample.layers]

    return Sample(
        id=sample.id,
        name=sample.name,
        bpm=sample.bpm,
        bars=sample.bars,
        layers=new_layers
    )


def add_layer(sample: Sample, prompt: str, sound: SoundType) -> Sample:
    """Add a new layer to the sample"""
    client = Anthropic()

    context = {
        "bpm": sample.bpm,
        "bars": sample.bars,
        "existing_layers": [l.model_dump() for l in sample.layers]
    }

    add_prompt = f"""Add a new {sound.value} layer to this sample.

Current sample context:
{json.dumps(context, indent=2)}

User request: {prompt}

The new layer should complement the existing layers. Output ONLY the new layer JSON:
{{"id": "new-id", "name": "...", "sound": "{sound.value}", "notes": [...]}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": add_prompt}
        ]
    )

    response_text = response.content[0].text

    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0].strip()
    else:
        json_str = response_text.strip()

    layer_data = json.loads(json_str)

    notes = []
    for note_data in layer_data.get("notes", []):
        notes.append(Note(
            pitch=note_data["pitch"],
            start=note_data["start"],
            duration=note_data["duration"],
            velocity=note_data.get("velocity", 80)
        ))

    new_layer = Layer(
        id=str(uuid.uuid4())[:8],
        name=layer_data.get("name", f"New {sound.value}"),
        sound=sound,
        notes=notes
    )

    return Sample(
        id=sample.id,
        name=sample.name,
        bpm=sample.bpm,
        bars=sample.bars,
        layers=sample.layers + [new_layer]
    )
