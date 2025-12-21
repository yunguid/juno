"""LLM integration for sample generation"""
import json
import uuid
import time
import random
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


SINGLE_LAYER_SYSTEM_PAD = """Output ONLY valid JSON. No markdown. No explanation. No text before or after.

EXAMPLE:
{{"id": "pad1", "name": "dark neo-soul", "sound": "pad", "notes": [
  {{"pitch": ["C3", "G3", "Bb4", "D5", "Eb5"], "start": 0, "duration": 4, "velocity": 62}},
  {{"pitch": ["Ab3", "C4", "Eb4", "G4", "Bb4"], "start": 4, "duration": 4, "velocity": 65}},
  {{"pitch": ["Eb3", "Bb3", "G4", "Bb4", "D5"], "start": 8, "duration": 4, "velocity": 68}},
  {{"pitch": ["Bb3", "D4", "F4", "A4", "C5"], "start": 12, "duration": 4, "velocity": 60}}
]}}

pitch = array of 4-6 notes. Root octave 3. Upper voices octave 4-5.
Use 9ths, 11ths, maj7, min9. Voice lead smoothly between chords."""


SINGLE_LAYER_SYSTEM_LEAD = """Output ONLY valid JSON. No markdown. No explanation. No text before or after.

EXAMPLE:
{{"id": "lead1", "name": "soulful melody", "sound": "lead", "notes": [
  {{"pitch": "G4", "start": 0.5, "duration": 1.5, "velocity": 65}},
  {{"pitch": "Bb4", "start": 2, "duration": 1, "velocity": 70}},
  {{"pitch": "C5", "start": 3.5, "duration": 0.5, "velocity": 68}},
  {{"pitch": "D5", "start": 4, "duration": 2, "velocity": 75}},
  {{"pitch": "Eb5", "start": 6.5, "duration": 1, "velocity": 80}},
  {{"pitch": "D5", "start": 8, "duration": 0.5, "velocity": 72}},
  {{"pitch": "C5", "start": 8.5, "duration": 0.5, "velocity": 68}},
  {{"pitch": "Bb4", "start": 9, "duration": 1.5, "velocity": 65}},
  {{"pitch": "G5", "start": 10.5, "duration": 2, "velocity": 85}},
  {{"pitch": "F5", "start": 12.5, "duration": 0.5, "velocity": 70}},
  {{"pitch": "Eb5", "start": 13, "duration": 1, "velocity": 65}},
  {{"pitch": "C5", "start": 14.5, "duration": 1.5, "velocity": 60}}
]}}

pitch = single string. Range C4-C6. VARY durations. Use OFF-BEATS (0.5, 1.5, 2.5). Leave GAPS."""


SINGLE_LAYER_SYSTEM_BASS = """Output ONLY valid JSON. No markdown. No explanation. No text before or after.

EXAMPLE:
{{"id": "bass1", "name": "foundation", "sound": "bass", "notes": [
  {{"pitch": "C2", "start": 0, "duration": 4, "velocity": 80}},
  {{"pitch": "Ab1", "start": 4, "duration": 4, "velocity": 80}},
  {{"pitch": "Eb2", "start": 8, "duration": 4, "velocity": 80}},
  {{"pitch": "Bb1", "start": 12, "duration": 4, "velocity": 80}}
]}}

pitch = single low note. Octave 1-2. Follow chord roots. Whole notes."""


SINGLE_LAYER_SYSTEMS = {
    SoundType.PAD: SINGLE_LAYER_SYSTEM_PAD,
    SoundType.LEAD: SINGLE_LAYER_SYSTEM_LEAD,
    SoundType.BASS: SINGLE_LAYER_SYSTEM_BASS,
}


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


# Genre-specific chord progression examples with EXACT notes
# Multiple examples per genre for variety
GENRE_CHORD_EXAMPLES = {
    "rnb": [
        """R&B PROGRESSION A - Neo-Soul (C minor):
Beat 0: Cm9 = ["C3", "G3", "Bb4", "D5", "Eb5"]
Beat 4: Fm9 = ["F3", "C4", "Eb4", "G4", "Ab4"]  
Beat 8: Abmaj9 = ["Ab3", "C4", "Eb4", "G4", "Bb4"]
Beat 12: G7b9 = ["G3", "B3", "D4", "F4", "Ab4"]

Smooth voice leading, jazz extensions (9ths, 11ths).""",
        """R&B PROGRESSION B - Soulful (Eb major):
Beat 0: Ebmaj9 = ["Eb3", "G3", "Bb4", "D5", "F5"]
Beat 4: Cm11 = ["C3", "G3", "Bb4", "Eb5", "F5"]
Beat 8: Abmaj7 = ["Ab3", "C4", "Eb4", "G4"]
Beat 12: Bb13 = ["Bb3", "D4", "F4", "Ab4", "G5"]

Extended dominant, lush voicings.""",
        """R&B PROGRESSION C - Moody (D minor):
Beat 0: Dm9 = ["D3", "A3", "C4", "E4", "F4"]
Beat 4: Bbmaj7 = ["Bb3", "D4", "F4", "A4"]
Beat 8: Gm9 = ["G3", "D4", "F4", "A4", "Bb4"]
Beat 12: A7#9 = ["A3", "C#4", "G4", "B#4"]

Dark but smooth, Hendrix chord at end."""
    ],

    "jazz": [
        """JAZZ PROGRESSION A - ii-V-I (C major):
Beat 0: Dm9 = ["D3", "A3", "C4", "E4", "F4"]
Beat 2: G13 = ["G3", "B3", "F4", "A4", "E5"]
Beat 4: Cmaj9 = ["C3", "E3", "B4", "D5", "G5"]
Beat 8: A7alt = ["A3", "C#4", "G4", "Bb4"]
Beat 12: Dm9 = ["D3", "F4", "A4", "C5", "E5"]
Beat 14: G7b9 = ["G3", "B3", "Db4", "F4", "Ab4"]

Classic jazz turnaround with alterations.""",
        """JAZZ PROGRESSION B - Modal (D dorian):
Beat 0: Dm7 = ["D3", "A3", "C4", "F4"]
Beat 4: Em7 = ["E3", "B3", "D4", "G4"]
Beat 8: Fmaj7 = ["F3", "C4", "E4", "A4"]
Beat 12: G7sus = ["G3", "C4", "D4", "F4"]

Quartal voicings, open sound, modal.""",
        """JAZZ PROGRESSION C - Coltrane Changes (Bb):
Beat 0: Bbmaj7 = ["Bb3", "D4", "F4", "A4"]
Beat 2: D7 = ["D3", "F#4", "A4", "C5"]
Beat 4: Gbmaj7 = ["Gb3", "Bb3", "Db4", "F4"]
Beat 6: A7 = ["A3", "C#4", "E4", "G4"]
Beat 8: Dmaj7 = ["D3", "F#3", "A4", "C#5"]
Beat 12: F7 = ["F3", "A3", "C4", "Eb4"]

Giant steps pattern, chromatic key centers."""
    ],

    "lofi": [
        """LOFI PROGRESSION A - Warm (F major):
Beat 0: Fmaj7 = ["F3", "A3", "C4", "E4"]
Beat 4: Em7 = ["E3", "G3", "B3", "D4"]
Beat 8: Dm7 = ["D3", "F3", "A3", "C4"]
Beat 12: Cmaj7 = ["C3", "E3", "G3", "B3"]

Simple 7th chords, warm and nostalgic.""",
        """LOFI PROGRESSION B - Rainy (A minor):
Beat 0: Am9 = ["A3", "C4", "E4", "G4", "B4"]
Beat 4: Fmaj9 = ["F3", "A3", "C4", "E4", "G4"]
Beat 8: Dm9 = ["D3", "F3", "A3", "C4", "E4"]
Beat 12: E7b9 = ["E3", "G#3", "D4", "F4"]

Melancholic, jazzy minor feel.""",
        """LOFI PROGRESSION C - Sunset (G major):
Beat 0: Gmaj7 = ["G3", "B3", "D4", "F#4"]
Beat 4: Em7 = ["E3", "G3", "B3", "D4"]
Beat 8: Cmaj9 = ["C3", "E3", "G4", "B4", "D5"]
Beat 12: D7sus4 = ["D3", "G3", "A3", "C4"]

Dreamy, open voicings."""
    ],

    "ambient": [
        """AMBIENT PROGRESSION A - Floating (C):
Beat 0-8: Csus2 = ["C3", "D3", "G4", "C5", "D5"]
Beat 8-16: Fsus2/C = ["C3", "F3", "G4", "C5"]

Very long chords, open fifths, suspended.""",
        """AMBIENT PROGRESSION B - Space (E minor):
Beat 0-6: Em(add9) = ["E3", "B3", "F#4", "G4", "B4"]
Beat 6-12: Cmaj7#11 = ["C3", "G3", "B4", "E5", "F#5"]
Beat 12-16: Am9 = ["A3", "E4", "G4", "B4", "C5"]

Lydian color, ethereal extensions.""",
        """AMBIENT PROGRESSION C - Drift (Bb):
Beat 0-8: Bbmaj9(no3) = ["Bb3", "F4", "A4", "C5"]
Beat 8-16: Eb(add9)/Bb = ["Bb3", "Eb4", "F4", "G4", "Bb4"]

Omit 3rds for ambiguity, pedal bass."""
    ],

    "dark": [
        """DARK PROGRESSION A - Phrygian (C minor):
Beat 0: Cm = ["C3", "G3", "Eb4", "G4", "C5"]
Beat 4: Dbmaj7 = ["Db3", "Ab3", "C4", "F4"]
Beat 8: Bbm7 = ["Bb2", "F3", "Ab3", "Db4"]
Beat 12: Abmaj7 = ["Ab3", "C4", "Eb4", "G4"]

bII chord creates sinister phrygian feel.""",
        """DARK PROGRESSION B - Chromatic (A minor):
Beat 0: Am = ["A3", "E4", "A4", "C5"]
Beat 4: Abmaj7 = ["Ab3", "C4", "Eb4", "G4"]
Beat 8: Gmaj7 = ["G3", "B3", "D4", "F#4"]
Beat 12: Gbmaj7 = ["Gb3", "Bb3", "Db4", "F4"]

Chromatic descent, unsettling.""",
        """DARK PROGRESSION C - Tension (F minor):
Beat 0: Fm = ["F3", "C4", "F4", "Ab4"]
Beat 4: Db = ["Db3", "Ab3", "Db4", "F4"]
Beat 8: Bbm = ["Bb3", "Db4", "F4", "Bb4"]
Beat 12: C7b9 = ["C3", "E4", "Bb4", "Db5"]

Building tension, unresolved dominant."""
    ],

    "gospel": [
        """GOSPEL PROGRESSION A - Classic (C major):
Beat 0: C = ["C3", "E4", "G4", "C5"]
Beat 2: C/E = ["E3", "G3", "C4", "E4"]
Beat 4: F = ["F3", "A3", "C4", "F4"]
Beat 6: Fm = ["F3", "Ab3", "C4", "F4"]
Beat 8: C/G = ["G3", "C4", "E4", "G4"]
Beat 12: G7 = ["G3", "B3", "D4", "F4"]

IV to iv movement, classic church sound.""",
        """GOSPEL PROGRESSION B - Soulful (Db major):
Beat 0: Dbmaj9 = ["Db3", "F4", "Ab4", "C5", "Eb5"]
Beat 4: Bbm11 = ["Bb3", "Db4", "F4", "Ab4", "Eb5"]
Beat 8: Gbmaj9 = ["Gb3", "Bb3", "Db4", "F4", "Ab4"]
Beat 12: Ab13 = ["Ab3", "C4", "Eb4", "Gb4", "F5"]

Rich extensions, soulful movement.""",
        """GOSPEL PROGRESSION C - Praise (G major):
Beat 0: G = ["G3", "B3", "D4", "G4"]
Beat 2: G/B = ["B3", "D4", "G4", "B4"]
Beat 4: C = ["C3", "E4", "G4", "C5"]
Beat 6: Cm = ["C3", "Eb4", "G4", "C5"]
Beat 8: G/D = ["D3", "G3", "B4", "D5"]
Beat 12: D = ["D3", "F#3", "A4", "D5"]

Walking bass, borrowed iv chord."""
    ],

    "pop": [
        """POP PROGRESSION A - Classic (G major):
Beat 0: G = ["G3", "B3", "D4", "G4"]
Beat 4: Em = ["E3", "G3", "B3", "E4"]
Beat 8: C = ["C3", "E3", "G3", "C4"]
Beat 12: D = ["D3", "F#3", "A3", "D4"]

I-vi-IV-V, simple and catchy.""",
        """POP PROGRESSION B - Emotional (C major):
Beat 0: Am = ["A3", "C4", "E4", "A4"]
Beat 4: F = ["F3", "A3", "C4", "F4"]
Beat 8: C = ["C3", "E3", "G3", "C4"]
Beat 12: G = ["G3", "B3", "D4", "G4"]

vi-IV-I-V, modern pop standard.""",
        """POP PROGRESSION C - Anthemic (D major):
Beat 0: D = ["D3", "F#3", "A4", "D5"]
Beat 4: A = ["A3", "C#4", "E4", "A4"]
Beat 8: Bm = ["B3", "D4", "F#4", "B4"]
Beat 12: G = ["G3", "B3", "D4", "G4"]

I-V-vi-IV, big sound."""
    ],

    "cinematic": [
        """CINEMATIC PROGRESSION A - Epic (C minor):
Beat 0: Cm = ["C3", "G3", "Eb4", "G4", "C5"]
Beat 4: Ab = ["Ab3", "C4", "Eb4", "Ab4"]
Beat 8: Eb = ["Eb3", "G3", "Bb4", "Eb5"]
Beat 12: Bb = ["Bb3", "D4", "F4", "Bb4"]

i-bVI-bIII-bVII, heroic arc.""",
        """CINEMATIC PROGRESSION B - Mysterious (D minor):
Beat 0: Dm = ["D3", "A3", "D4", "F4"]
Beat 4: Bbmaj7 = ["Bb3", "D4", "F4", "A4"]
Beat 8: Gm = ["G3", "D4", "G4", "Bb4"]
Beat 12: A = ["A3", "C#4", "E4", "A4"]

Minor with major V, unresolved tension.""",
        """CINEMATIC PROGRESSION C - Triumphant (Eb major):
Beat 0: Eb = ["Eb3", "G3", "Bb4", "Eb5"]
Beat 4: Cm = ["C3", "G3", "Eb4", "G4"]
Beat 8: Ab = ["Ab3", "C4", "Eb4", "Ab4"]
Beat 12: Bb = ["Bb3", "D4", "F4", "Bb4"]

Major key, victorious feel."""
    ],

    "trap": [
        """TRAP PROGRESSION A - Dark (C minor):
Beat 0: Cm = ["C3", "Eb4", "G4"]
Beat 4: Ab = ["Ab3", "C4", "Eb4"]
Beat 8: Bb = ["Bb3", "D4", "F4"]
Beat 12: Gm = ["G3", "Bb3", "D4"]

Simple triads, minor key, sparse.""",
        """TRAP PROGRESSION B - Eerie (A minor):
Beat 0: Am = ["A3", "C4", "E4"]
Beat 4: F = ["F3", "A3", "C4"]
Beat 8: E = ["E3", "G#3", "B3"]
Beat 12: E7 = ["E3", "G#3", "B3", "D4"]

Major V for tension, dark vibe.""",
        """TRAP PROGRESSION C - Menacing (F minor):
Beat 0: Fm = ["F3", "Ab3", "C4"]
Beat 4: Db = ["Db3", "F3", "Ab3"]
Beat 8: Eb = ["Eb3", "G3", "Bb3"]
Beat 12: C = ["C3", "E3", "G3"]

Phrygian, dark, hard-hitting."""
    ],

    "electronic": [
        """ELECTRONIC PROGRESSION A - Driving (A minor):
Beat 0: Am = ["A3", "C4", "E4", "A4"]
Beat 4: F = ["F3", "A3", "C4", "F4"]
Beat 8: C = ["C3", "E3", "G3", "C4"]
Beat 12: G = ["G3", "B3", "D4", "G4"]

vi-IV-I-V, clean and punchy.""",
        """ELECTRONIC PROGRESSION B - Euphoric (F major):
Beat 0: F = ["F3", "A3", "C4", "F4"]
Beat 4: Am = ["A3", "C4", "E4", "A4"]
Beat 8: Dm = ["D3", "F3", "A3", "D4"]
Beat 12: Bb = ["Bb3", "D4", "F4", "Bb4"]

Major key, uplifting energy.""",
        """ELECTRONIC PROGRESSION C - Trance (E minor):
Beat 0: Em = ["E3", "B3", "E4", "G4"]
Beat 4: C = ["C3", "E3", "G3", "C4"]
Beat 8: D = ["D3", "F#3", "A3", "D4"]
Beat 12: B = ["B3", "D#4", "F#4", "B4"]

i-bVI-bVII-V, driving trance feel."""
    ],

    "emotional": [
        """EMOTIONAL PROGRESSION A - Yearning (C minor):
Beat 0: Cm9 = ["C3", "G3", "Bb4", "D5", "Eb5"]
Beat 4: Abmaj7 = ["Ab3", "C4", "Eb4", "G4"]
Beat 8: Ebmaj7 = ["Eb3", "G3", "Bb4", "D5"]
Beat 12: Bb(add9) = ["Bb3", "D4", "F4", "C5"]

Lush extensions, smooth voice leading.""",
        """EMOTIONAL PROGRESSION B - Melancholy (D minor):
Beat 0: Dm9 = ["D3", "A3", "C4", "E4", "F4"]
Beat 4: Bbmaj9 = ["Bb3", "D4", "F4", "A4", "C5"]
Beat 8: Gm7 = ["G3", "Bb3", "D4", "F4"]
Beat 12: A7sus4 = ["A3", "D4", "E4", "G4"]

Suspended resolution, longing.""",
        """EMOTIONAL PROGRESSION C - Hopeful (G major):
Beat 0: Gmaj9 = ["G3", "B3", "D4", "F#4", "A4"]
Beat 4: Em9 = ["E3", "G3", "B4", "D5", "F#5"]
Beat 8: Cmaj7 = ["C3", "E3", "G4", "B4"]
Beat 12: D7sus4 = ["D3", "G3", "A3", "C4"]

Major key warmth, gentle resolution."""
    ]
}


def _get_random_chord_example(genre: str) -> str:
    """Get a random chord progression example for variety"""
    examples = GENRE_CHORD_EXAMPLES.get(genre, GENRE_CHORD_EXAMPLES["emotional"])
    return random.choice(examples)

# Genre-specific melody examples with EXACT notes
GENRE_MELODY_EXAMPLES = {
    "rnb": [
        """R&B MELODY EXAMPLE (C minor, 4 bars):
Bar 1: G4 (beat 0.5, dur 1), Eb5 (beat 1.5, dur 0.5), D5 (beat 2, dur 1.5)
Bar 2: C5 (beat 4, dur 2), Bb4 (beat 6.5, dur 1)
Bar 3: G4 (beat 8, dur 0.5), Bb4 (beat 8.5, dur 0.5), C5 (beat 9, dur 0.5), D5 (beat 9.5, dur 2)
Bar 4: Eb5 (beat 12, dur 1), D5 (beat 13, dur 0.5), C5 (beat 13.5, dur 2)

Syncopated, soulful runs, end on chord tones.""",
        """R&B MELODY EXAMPLE (Eb major, 4 bars):
Bar 1: Bb4 (beat 0, dur 1.5), G4 (beat 1.5, dur 0.5), Bb4 (beat 2, dur 2)
Bar 2: C5 (beat 4.5, dur 1), Bb4 (beat 5.5, dur 0.5), Ab4 (beat 6, dur 1), G4 (beat 7, dur 1)
Bar 3: Eb5 (beat 8, dur 2), D5 (beat 10, dur 0.5), C5 (beat 10.5, dur 1.5)
Bar 4: Bb4 (beat 12, dur 3), rest

Melodic arc, smooth, breath at end."""
    ],
    "jazz": [
        """JAZZ MELODY EXAMPLE (C major, ii-V-I):
Bar 1: F4 (beat 0, dur 0.5), E4 (beat 0.5, dur 0.5), D4 (beat 1, dur 1), B4 (beat 2.5, dur 1)
Bar 2: G4 (beat 4, dur 2), E4 (beat 6, dur 0.5), D4 (beat 6.5, dur 0.5), C4 (beat 7, dur 1)
Bar 3: A4 (beat 8.5, dur 0.5), G4 (beat 9, dur 0.5), E4 (beat 9.5, dur 0.5), C4 (beat 10, dur 2)
Bar 4: D4 (beat 12, dur 1), C4 (beat 13, dur 2)

Bebop enclosures, chromatic approach notes.""",
        """JAZZ MELODY EXAMPLE (D dorian):
Bar 1: D5 (beat 0, dur 1), C5 (beat 1, dur 0.5), A4 (beat 1.5, dur 1.5)
Bar 2: F4 (beat 4, dur 0.5), G4 (beat 4.5, dur 0.5), A4 (beat 5, dur 0.5), C5 (beat 5.5, dur 2)
Bar 3: E5 (beat 8, dur 0.5), D5 (beat 8.5, dur 0.5), C5 (beat 9, dur 0.5), B4 (beat 9.5, dur 0.5), A4 (beat 10, dur 2)
Bar 4: G4 (beat 12, dur 2), D4 (beat 14, dur 2)

Modal, angular, swing feel."""
    ],
    "lofi": [
        """LOFI MELODY EXAMPLE (F major):
Bar 1: C5 (beat 0.5, dur 1.5), A4 (beat 2, dur 2)
Bar 2: G4 (beat 4.5, dur 1.5), E4 (beat 6, dur 1), F4 (beat 7.5, dur 0.5)
Bar 3: A4 (beat 8, dur 1), G4 (beat 9.5, dur 1.5), E4 (beat 11, dur 1)
Bar 4: C4 (beat 12, dur 4)

Simple, sparse, slightly behind beat, nostalgic.""",
        """LOFI MELODY EXAMPLE (A minor):
Bar 1: E5 (beat 0, dur 2), C5 (beat 2.5, dur 1.5)
Bar 2: B4 (beat 4, dur 1), A4 (beat 5.5, dur 2.5)
Bar 3: C5 (beat 8.5, dur 1), B4 (beat 9.5, dur 0.5), A4 (beat 10, dur 1), G4 (beat 11.5, dur 0.5)
Bar 4: A4 (beat 12, dur 4)

Pentatonic, dreamy, space between notes."""
    ],
    "ambient": [
        """AMBIENT MELODY EXAMPLE (C minor):
Bar 1-2: G4 (beat 0, dur 6), Eb5 (beat 6, dur 2)
Bar 3-4: D5 (beat 8, dur 4), C5 (beat 12, dur 4)

Very sparse, long held notes, ethereal.""",
        """AMBIENT MELODY EXAMPLE (E minor):
Bar 1: B4 (beat 0, dur 4)
Bar 2: (rest)
Bar 3: F#5 (beat 8, dur 3), E5 (beat 11, dur 1)
Bar 4: G5 (beat 12, dur 4)

Floating, lots of space, barely there."""
    ],
    "dark": [
        """DARK MELODY EXAMPLE (C minor, phrygian):
Bar 1: C5 (beat 0, dur 1), Db5 (beat 1, dur 0.5), C5 (beat 1.5, dur 0.5), Bb4 (beat 2, dur 2)
Bar 2: Ab4 (beat 4, dur 1.5), G4 (beat 5.5, dur 0.5), F4 (beat 6, dur 2)
Bar 3: Eb5 (beat 8, dur 1), Db5 (beat 9, dur 0.5), C5 (beat 9.5, dur 0.5), Bb4 (beat 10, dur 0.5), Ab4 (beat 10.5, dur 1.5)
Bar 4: G4 (beat 12, dur 2), C4 (beat 14, dur 2)

b2 for darkness, descending lines, tense.""",
        """DARK MELODY EXAMPLE (A minor):
Bar 1: A4 (beat 0.5, dur 1), Bb4 (beat 1.5, dur 0.5), A4 (beat 2, dur 1.5)
Bar 2: E4 (beat 4, dur 2), F4 (beat 6, dur 1), E4 (beat 7, dur 1)
Bar 3: A4 (beat 8, dur 0.5), G#4 (beat 8.5, dur 0.5), A4 (beat 9, dur 0.5), B4 (beat 9.5, dur 0.5), C5 (beat 10, dur 2)
Bar 4: B4 (beat 12, dur 1), A4 (beat 13, dur 3)

Chromatic tension, minor key anguish."""
    ],
    "gospel": [
        """GOSPEL MELODY EXAMPLE (C major):
Bar 1: E4 (beat 0, dur 0.5), G4 (beat 0.5, dur 0.5), C5 (beat 1, dur 2)
Bar 2: D5 (beat 4, dur 0.5), E5 (beat 4.5, dur 0.5), D5 (beat 5, dur 0.5), C5 (beat 5.5, dur 1.5), G4 (beat 7, dur 1)
Bar 3: A4 (beat 8, dur 0.25), B4 (beat 8.25, dur 0.25), C5 (beat 8.5, dur 0.5), E5 (beat 9, dur 1.5), D5 (beat 10.5, dur 1.5)
Bar 4: C5 (beat 12, dur 4)

Melismatic runs, soulful ornamentation, climax in bar 3.""",
        """GOSPEL MELODY EXAMPLE (G major):
Bar 1: D5 (beat 0, dur 1.5), B4 (beat 1.5, dur 0.5), G4 (beat 2, dur 2)
Bar 2: A4 (beat 4.5, dur 0.5), B4 (beat 5, dur 0.5), C5 (beat 5.5, dur 0.5), D5 (beat 6, dur 2)
Bar 3: E5 (beat 8, dur 0.5), D5 (beat 8.5, dur 0.5), E5 (beat 9, dur 0.5), F#5 (beat 9.5, dur 0.5), G5 (beat 10, dur 2)
Bar 4: F#5 (beat 12, dur 0.5), E5 (beat 12.5, dur 0.5), D5 (beat 13, dur 3)

Build to high note in bar 3, graceful descent."""
    ],
    "pop": [
        """POP MELODY EXAMPLE (G major):
Bar 1: D5 (beat 0, dur 1), B4 (beat 1, dur 1), G4 (beat 2, dur 2)
Bar 2: A4 (beat 4, dur 1.5), B4 (beat 5.5, dur 0.5), C5 (beat 6, dur 2)
Bar 3: D5 (beat 8, dur 1), E5 (beat 9, dur 1), D5 (beat 10, dur 1), C5 (beat 11, dur 1)
Bar 4: B4 (beat 12, dur 2), G4 (beat 14, dur 2)

Stepwise, catchy, singable hook.""",
        """POP MELODY EXAMPLE (C major):
Bar 1: E5 (beat 0.5, dur 1.5), D5 (beat 2, dur 1), C5 (beat 3, dur 1)
Bar 2: D5 (beat 4, dur 2), E5 (beat 6, dur 2)
Bar 3: G5 (beat 8, dur 1), F5 (beat 9, dur 0.5), E5 (beat 9.5, dur 0.5), D5 (beat 10, dur 2)
Bar 4: C5 (beat 12, dur 4)

Clear phrases, memorable, ends on root."""
    ],
    "cinematic": [
        """CINEMATIC MELODY EXAMPLE (C minor):
Bar 1: G4 (beat 0, dur 2), C5 (beat 2, dur 2)
Bar 2: Eb5 (beat 4, dur 2), D5 (beat 6, dur 1), C5 (beat 7, dur 1)
Bar 3: G5 (beat 8, dur 2), F5 (beat 10, dur 1), Eb5 (beat 11, dur 1)
Bar 4: D5 (beat 12, dur 2), C5 (beat 14, dur 2)

Wide intervals, heroic arc, dramatic leap to G5.""",
        """CINEMATIC MELODY EXAMPLE (D minor):
Bar 1: D4 (beat 0, dur 3), F4 (beat 3, dur 1)
Bar 2: A4 (beat 4, dur 2), G4 (beat 6, dur 1), F4 (beat 7, dur 1)
Bar 3: D5 (beat 8, dur 1.5), C5 (beat 9.5, dur 0.5), Bb4 (beat 10, dur 2)
Bar 4: A4 (beat 12, dur 4)

Haunting, building tension, octave leap."""
    ],
    "trap": [
        """TRAP MELODY EXAMPLE (C minor):
Bar 1: G4 (beat 0, dur 0.5), Eb5 (beat 0.5, dur 1), D5 (beat 1.5, dur 0.5), C5 (beat 2, dur 1.5)
Bar 2: G4 (beat 4, dur 0.5), Eb5 (beat 4.5, dur 1), D5 (beat 5.5, dur 0.5), C5 (beat 6, dur 2)
Bar 3: (similar pattern with slight variation)
Bar 4: Eb5 (beat 12, dur 0.5), D5 (beat 12.5, dur 0.5), C5 (beat 13, dur 3)

Repetitive hook, short phrases, catchy.""",
        """TRAP MELODY EXAMPLE (A minor):
Bar 1: E5 (beat 0, dur 0.5), C5 (beat 0.5, dur 1.5)
Bar 2: B4 (beat 4, dur 0.5), A4 (beat 4.5, dur 1.5), rest
Bar 3: E5 (beat 8, dur 0.5), C5 (beat 8.5, dur 0.5), B4 (beat 9, dur 0.5), A4 (beat 9.5, dur 0.5), G4 (beat 10, dur 2)
Bar 4: A4 (beat 12, dur 2), rest

Minimal, catchy, lots of space."""
    ],
    "electronic": [
        """ELECTRONIC MELODY EXAMPLE (A minor, arpeggiated):
Bar 1: A4 (beat 0, dur 0.25), C5 (beat 0.25, dur 0.25), E5 (beat 0.5, dur 0.25), A5 (beat 0.75, dur 0.25), repeat pattern
Bar 2: F4 (beat 4, dur 0.25), A4 (beat 4.25, dur 0.25), C5 (beat 4.5, dur 0.25), F5 (beat 4.75, dur 0.25), repeat
Bar 3: (similar arp on different chord)
Bar 4: Build to sustained A5 (beat 14, dur 2)

Driving arpeggios, energetic, build at end.""",
        """ELECTRONIC MELODY EXAMPLE (F major):
Bar 1: C5 (beat 0, dur 1), A4 (beat 1, dur 0.5), C5 (beat 1.5, dur 0.5), F5 (beat 2, dur 2)
Bar 2: E5 (beat 4, dur 0.5), D5 (beat 4.5, dur 0.5), C5 (beat 5, dur 1), A4 (beat 6, dur 2)
Bar 3: C5 (beat 8, dur 0.5), F5 (beat 8.5, dur 0.5), G5 (beat 9, dur 1), A5 (beat 10, dur 2)
Bar 4: G5 (beat 12, dur 1), F5 (beat 13, dur 1), C5 (beat 14, dur 2)

Euphoric, rising energy, clear phrases."""
    ],
    "emotional": [
        """EMOTIONAL MELODY EXAMPLE (C minor):
Bar 1: Eb5 (beat 0, dur 1.5), D5 (beat 1.5, dur 0.5), C5 (beat 2, dur 2)
Bar 2: G4 (beat 4, dur 1), Bb4 (beat 5.5, dur 1.5), C5 (beat 7, dur 1)
Bar 3: D5 (beat 8, dur 1), Eb5 (beat 9, dur 1), F5 (beat 10, dur 1), G5 (beat 11, dur 1)
Bar 4: Eb5 (beat 12, dur 2), D5 (beat 14, dur 0.5), C5 (beat 14.5, dur 1.5)

Expressive dynamics, rise to climax in bar 3, gentle resolve.""",
        """EMOTIONAL MELODY EXAMPLE (D minor):
Bar 1: A4 (beat 0.5, dur 1.5), G4 (beat 2, dur 1), F4 (beat 3, dur 1)
Bar 2: E4 (beat 4, dur 2), D4 (beat 6.5, dur 1.5)
Bar 3: F4 (beat 8, dur 0.5), A4 (beat 8.5, dur 0.5), C5 (beat 9, dur 1), D5 (beat 10, dur 2)
Bar 4: C5 (beat 12, dur 1), A4 (beat 13, dur 1), D4 (beat 14, dur 2)

Story arc, breath between phrases, ends on root."""
    ]
}


def _get_random_melody_example(genre: str) -> str:
    """Get a random melody example for variety"""
    examples = GENRE_MELODY_EXAMPLES.get(genre, GENRE_MELODY_EXAMPLES["emotional"])
    return random.choice(examples)


def _get_layer_specific_prompt(sound_type: SoundType, prompt: str, key: str, bpm: int, bars: int, existing_layers: list[Layer] | None) -> str:
    """Build a specialized prompt for each layer type with genre awareness"""
    beats = bars * 4
    genre = _detect_genre(prompt)
    
    if sound_type == SoundType.PAD:
        chord_example = _get_random_chord_example(genre)
        
        return f"""{genre.upper()} chord progression. Key: {key}. {bars} bars ({beats} beats).
Vibe: {prompt}

INSPIRATION (transpose to {key}, don't copy):
{chord_example}

Output {bars} bars of chords. Use 4-6 note voicings. Velocity 55-70."""

    elif sound_type == SoundType.LEAD:
        melody_example = _get_random_melody_example(genre)
        
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
    system_template = SINGLE_LAYER_SYSTEMS.get(sound_type)
    if not system_template:
        raise ValueError(f"Unknown sound type: {sound_type}")
    
    system = system_template

    # Build layer-specific user prompt
    user_prompt = _get_layer_specific_prompt(
        sound_type, prompt, key, bpm, bars, existing_layers
    )

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
