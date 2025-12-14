"""Core MIDI utilities for Yamaha MONTAGE M"""
import mido
import time

PORT_NAMES = [
    "MONTAGE M 2 Port1",           # macOS
    "MONTAGE M:MONTAGE M MIDI 1 24:0",  # Linux/Pi
]

def get_port():
    """Open and return the MIDI output port"""
    available = mido.get_output_names()
    for name in PORT_NAMES:
        if name in available:
            return mido.open_output(name)
    raise IOError(f"No MONTAGE found. Available ports: {available}")

def list_ports():
    """List available MIDI ports"""
    print("OUTPUT PORTS:", mido.get_output_names())

def panic(port):
    """Kill all notes on all channels - use when stuck notes happen"""
    for ch in range(16):
        port.send(mido.Message('control_change', control=123, value=0, channel=ch))
        port.send(mido.Message('control_change', control=121, value=0, channel=ch))
        port.send(mido.Message('pitchwheel', pitch=0, channel=ch))
    print("PANIC: All notes off!")

def send_note(port, note, velocity=100, duration=0.5, channel=0):
    """Send a single note"""
    port.send(mido.Message('note_on', note=note, velocity=velocity, channel=channel))
    time.sleep(duration)
    port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))

def send_chord(port, notes, velocity=100, duration=1.0, channel=0):
    """Send a chord (multiple notes simultaneously)"""
    for note in notes:
        port.send(mido.Message('note_on', note=note, velocity=velocity, channel=channel))
    time.sleep(duration)
    for note in notes:
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))

def send_cc(port, cc, value, channel=0):
    """Send a control change message"""
    port.send(mido.Message('control_change', control=cc, value=value, channel=channel))

def send_pitch_bend(port, value, channel=0):
    """Send pitch bend (-8192 to 8191, 0 = center)"""
    port.send(mido.Message('pitchwheel', pitch=value, channel=channel))

def play_scale(port, root=60, scale_type='major', velocity=100, tempo=120, channel=0):
    """Play a scale - root=60 is middle C"""
    scales = {
        'major': [0, 2, 4, 5, 7, 9, 11, 12],
        'minor': [0, 2, 3, 5, 7, 8, 10, 12],
        'pentatonic': [0, 2, 4, 7, 9, 12],
        'blues': [0, 3, 5, 6, 7, 10, 12],
    }
    note_duration = 60 / tempo / 2
    for interval in scales[scale_type]:
        send_note(port, root + interval, velocity, note_duration, channel)

def play_arpeggio(port, root=60, chord_type='maj7', velocity=100, tempo=120, loops=2, channel=0):
    """Play an arpeggio pattern"""
    chords = {
        'maj': [0, 4, 7],
        'min': [0, 3, 7],
        'maj7': [0, 4, 7, 11],
        'min7': [0, 3, 7, 10],
        'dom7': [0, 4, 7, 10],
    }
    note_duration = 60 / tempo / 4
    intervals = chords[chord_type]
    for _ in range(loops):
        for interval in intervals:
            send_note(port, root + interval, velocity, note_duration, channel)
        for interval in reversed(intervals[:-1]):
            send_note(port, root + interval, velocity, note_duration, channel)

def play_chord_progression(port, progression, tempo=90, velocity=90, channel=0):
    """
    Play chord progression
    progression: list of (root_note, chord_type, duration_beats) tuples
    """
    chords = {
        'maj': [0, 4, 7],
        'min': [0, 3, 7],
        'maj7': [0, 4, 7, 11],
        'min7': [0, 3, 7, 10],
        'dom7': [0, 4, 7, 10],
        'dim': [0, 3, 6],
        'aug': [0, 4, 8],
    }
    beat_duration = 60 / tempo
    
    for root, chord_type, beats in progression:
        notes = [root + i for i in chords[chord_type]]
        send_chord(port, notes, velocity, beats * beat_duration, channel)
        time.sleep(0.05)

