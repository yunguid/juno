"""Export samples to MIDI files for Ableton import"""
import io
import mido
from .models import Sample, SoundType, SOUND_CHANNELS, note_to_midi


def sample_to_midi_file(sample: Sample) -> bytes:
    """Convert a Sample to a standard MIDI file (bytes)"""
    mid = mido.MidiFile(type=1)  # Type 1 = multiple tracks

    # Ticks per beat (standard resolution)
    ticks_per_beat = 480
    mid.ticks_per_beat = ticks_per_beat

    # Create tempo track
    tempo_track = mido.MidiTrack()
    mid.tracks.append(tempo_track)

    # Set tempo (microseconds per beat)
    tempo = mido.bpm2tempo(sample.bpm)
    tempo_track.append(mido.MetaMessage('set_tempo', tempo=tempo, time=0))
    tempo_track.append(mido.MetaMessage('time_signature',
                                         numerator=sample.time_signature[0],
                                         denominator=sample.time_signature[1],
                                         time=0))
    tempo_track.append(mido.MetaMessage('track_name', name=sample.name, time=0))
    tempo_track.append(mido.MetaMessage('end_of_track', time=0))

    # Create a track for each layer
    for layer in sample.layers:
        if layer.muted:
            continue

        track = mido.MidiTrack()
        mid.tracks.append(track)

        channel = SOUND_CHANNELS[layer.sound]

        # Track name
        track.append(mido.MetaMessage('track_name', name=layer.name, time=0))

        # Collect all events with their absolute tick times
        events = []

        for note in layer.notes:
            start_ticks = int(note.start * ticks_per_beat)
            duration_ticks = int(note.duration * ticks_per_beat)
            end_ticks = start_ticks + duration_ticks

            # Handle single note or chord
            pitches = note.pitch if isinstance(note.pitch, list) else [note.pitch]

            for pitch_name in pitches:
                midi_note = note_to_midi(pitch_name)

                events.append({
                    'type': 'note_on',
                    'time': start_ticks,
                    'note': midi_note,
                    'velocity': note.velocity,
                    'channel': channel
                })
                events.append({
                    'type': 'note_off',
                    'time': end_ticks,
                    'note': midi_note,
                    'velocity': 0,
                    'channel': channel
                })

        # Sort events by time
        events.sort(key=lambda e: (e['time'], e['type'] == 'note_on'))

        # Convert to delta times and add to track
        current_time = 0
        for event in events:
            delta = event['time'] - current_time
            current_time = event['time']

            if event['type'] == 'note_on':
                track.append(mido.Message(
                    'note_on',
                    note=event['note'],
                    velocity=event['velocity'],
                    channel=event['channel'],
                    time=delta
                ))
            else:
                track.append(mido.Message(
                    'note_off',
                    note=event['note'],
                    velocity=0,
                    channel=event['channel'],
                    time=delta
                ))

        track.append(mido.MetaMessage('end_of_track', time=0))

    # Write to bytes
    buffer = io.BytesIO()
    mid.save(file=buffer)
    return buffer.getvalue()
