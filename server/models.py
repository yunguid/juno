"""Sample schema and data models for Juno"""
from pydantic import BaseModel, Field
from typing import Literal
from enum import Enum


class SoundType(str, Enum):
    BASS = "bass"
    PAD = "pad"
    LEAD = "lead"


# MIDI channel mapping for each sound type
SOUND_CHANNELS = {
    SoundType.BASS: 0,   # Channel 1
    SoundType.PAD: 1,    # Channel 2
    SoundType.LEAD: 2,   # Channel 3
}


class Note(BaseModel):
    """A single note or chord in a layer"""
    pitch: str | list[str]  # "C4" or ["C4", "E4", "G4"] for chords
    start: float            # Start time in beats (0 = beginning)
    duration: float         # Duration in beats
    velocity: int = Field(default=80, ge=1, le=127)


class Layer(BaseModel):
    """A single layer/track in the sample"""
    id: str                           # Unique identifier
    name: str                         # Display name (e.g., "dreamy pad")
    sound: SoundType                  # Which sound to use
    notes: list[Note]                 # The notes in this layer
    muted: bool = False               # Whether layer is muted
    volume: int = Field(default=100, ge=0, le=127)  # Layer volume (CC7)
    portamento: bool = False          # Enable glide between notes (CC65)
    portamento_time: int = Field(default=40, ge=0, le=127)  # Glide speed (CC5)


class Sample(BaseModel):
    """Complete sample definition"""
    id: str                           # Unique identifier
    name: str                         # User-facing name
    prompt: str = ""                  # Original user prompt
    key: str = "C minor"              # Musical key
    bpm: int = Field(default=90, ge=40, le=200)
    time_signature: tuple[int, int] = (4, 4)
    bars: int = Field(default=4, ge=1, le=32)
    layers: list[Layer]

    @property
    def duration_beats(self) -> float:
        """Total duration in beats"""
        return self.bars * self.time_signature[0]

    @property
    def duration_seconds(self) -> float:
        """Total duration in seconds"""
        return self.duration_beats * (60 / self.bpm)


class GenerateRequest(BaseModel):
    """Request to generate a new sample"""
    prompt: str
    bpm: int | None = None
    bars: int | None = None


class StartSessionRequest(BaseModel):
    """Request to start a new step-by-step session"""
    prompt: str
    key: str = "C minor"
    bpm: int = 90
    bars: int = 4


class GenerateLayerRequest(BaseModel):
    """Request to generate a specific layer"""
    sound: SoundType


class LayerEditRequest(BaseModel):
    """Request to edit a specific layer"""
    sample_id: str
    layer_id: str
    prompt: str  # e.g., "make it more melodic" or "add some variation"


class AddLayerRequest(BaseModel):
    """Request to add a new layer to existing sample"""
    sample_id: str
    prompt: str
    sound: SoundType


# Note name to MIDI number conversion
NOTE_TO_MIDI = {}
for octave in range(-1, 10):
    for i, note in enumerate(['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']):
        midi_num = (octave + 1) * 12 + i
        if 0 <= midi_num <= 127:
            NOTE_TO_MIDI[f"{note}{octave}"] = midi_num
            # Also support flats
            flat_map = {'C#': 'Db', 'D#': 'Eb', 'F#': 'Gb', 'G#': 'Ab', 'A#': 'Bb'}
            if note in flat_map:
                NOTE_TO_MIDI[f"{flat_map[note]}{octave}"] = midi_num


def note_to_midi(note_name: str) -> int:
    """Convert note name (e.g., 'C4') to MIDI number (e.g., 60)"""
    if note_name not in NOTE_TO_MIDI:
        raise ValueError(f"Invalid note name: {note_name}")
    return NOTE_TO_MIDI[note_name]
