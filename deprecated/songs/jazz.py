"""Bill Evans style Jazz - Rich harmonies and lyrical melodies"""
import time
import random
import mido
from midi_utils import send_pitch_bend

def bill_evans_jazz(port, channel=0, loops=2):
    """
    Bill Evans inspired Jazz - Rootless voicings, lyrical melody, swing feel
    Key: Bb Major (mostly)
    """
    tempo = 110
    beat = 60 / tempo
    swing_ratio = 0.6 # For swing feel logic if we implemented strict quantization, but here we'll play loosely

    def play_note(note, vel, duration):
        # Add slight humanization to velocity and timing
        vel = max(1, min(127, int(vel + random.randint(-5, 5))))
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        return note

    def stop_note(note):
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))

    def play_chord(notes, vel, duration):
        active_notes = []
        # Strum chords slightly
        for n in notes:
            active_notes.append(play_note(n, vel, 0))
            time.sleep(random.uniform(0.01, 0.03))
        
        time.sleep(duration * beat - (len(notes) * 0.02))
        
        for n in active_notes:
            stop_note(n)
            
    def play_jazz_bar(chord_notes, melody_notes):
        """
        chord_notes: list of midi numbers
        melody_notes: list of tuples (note, velocity, start_time, duration)
                      start_time is relative to bar start in beats
        """
        # Trigger chord at start (beat 1) - slightly anticipated or delayed
        # But for simplicity, we'll just play chord on 1, maybe anticipating melody
        
        # We need a timeline event system for this to sound real, 
        # but let's do a simpler linear approach:
        # We will iterate through beats.
        
        # Actually, let's just execute the sequence.
        # Start chord
        active_chord_notes = []
        for n in chord_notes:
            # Randomize velocity for inner voices vs top voice
            v = 55 + random.randint(-5, 5)
            port.send(mido.Message('note_on', note=n, velocity=v, channel=channel))
            active_chord_notes.append(n)
            time.sleep(0.01) # strum
            
        current_beat = 0
        last_event_end = 0
        
        # Sort melody by start time
        melody_notes.sort(key=lambda x: x[2])
        
        for note, vel, start, dur in melody_notes:
            # Wait until start time
            wait_time = (start - current_beat) * beat
            if wait_time > 0:
                time.sleep(wait_time)
                current_beat = start
            
            # Play note
            if note:
                port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
                # We won't block for the full duration here to allow overlap, 
                # but for this simple script, we might need to block or handle note_offs separately.
                # To keep it simple: we sleep for duration. 
                # This prevents polyphony in melody (which is fine for a lead line).
                time.sleep(dur * beat)
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
                current_beat += dur
            else:
                # Rest
                time.sleep(dur * beat)
                current_beat += dur
                
        # Wait for remainder of the measure (assuming 4/4)
        remainder = 4.0 - current_beat
        if remainder > 0:
            time.sleep(remainder * beat)
            
        # Release chord
        for n in active_chord_notes:
            port.send(mido.Message('note_off', note=n, velocity=0, channel=channel))

    print(f"Playing Bill Evans style Jazz... ({loops} loops)")
    print("  II-V-I progressions with rootless voicings")

    # Progression: Cm9 | F13b9 | Bbmaj9 | G7alt
    
    # Cm9 (Rootless): Eb-G-Bb-D (Eb3, G3, Bb3, D4) -> 51, 55, 58, 62
    chord_ii = [51, 55, 58, 62] 
    
    # F13b9 (Rootless): Eb-Gb-A-D (Eb3, Gb3, A3, D4) -> 51, 54, 57, 62
    chord_v = [51, 54, 57, 62]
    
    # Bbmaj9 (Rootless): D-F-A-C (D3, F3, A3, C4) -> 50, 53, 57, 60
    chord_i = [50, 53, 57, 60]
    
    # G7alt (Rootless): F-Ab-B-E (F3, Ab3, B3, E4) -> 53, 56, 59, 64
    chord_vi = [53, 56, 59, 64]

    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        
        # Bar 1: Cm9
        # Melody: G - F - Eb - D - C (descending run)
        melody_1 = [
            (67, 85, 0.0, 0.75), # G
            (65, 80, 0.75, 0.25), # F
            (63, 82, 1.0, 0.5),   # Eb
            (62, 75, 1.5, 0.5),   # D
            (60, 78, 2.0, 1.0),   # C (target 9th)
            (None, 0, 3.0, 1.0)   # Rest
        ]
        play_jazz_bar(chord_ii, melody_1)

        # Bar 2: F13b9
        # Melody: Gb - A - C - Eb (arpeggiating the altered dom)
        melody_2 = [
            (54, 75, 0.0, 0.66), # Gb
            (57, 78, 0.66, 0.66), # A
            (60, 82, 1.32, 0.66), # C
            (63, 85, 1.98, 1.02), # Eb
            (62, 70, 3.0, 0.5),   # D (anticipating next chord)
            (None, 0, 3.5, 0.5)
        ]
        play_jazz_bar(chord_v, melody_2)

        # Bar 3: Bbmaj9
        # Melody: F - D - Bb - A (lyrical)
        melody_3 = [
            (65, 85, 0.0, 1.5),   # F
            (62, 75, 1.5, 0.5),   # D
            (58, 70, 2.0, 0.5),   # Bb
            (57, 72, 2.5, 1.5),   # A (maj7)
        ]
        play_jazz_bar(chord_i, melody_3)

        # Bar 4: G7alt
        # Melody: Ab - B - Eb - G (altered tension)
        melody_4 = [
            (56, 75, 0.0, 0.5),   # Ab
            (59, 78, 0.5, 0.5),   # B
            (63, 82, 1.0, 0.5),   # Eb
            (67, 88, 1.5, 1.5),   # G (root, but high)
            (68, 70, 3.0, 0.5),   # Ab (flat 9)
            (67, 60, 3.5, 0.5),   # G
        ]
        play_jazz_bar(chord_vi, melody_4)

    # Final Chord: Bb6/9
    final_chord = [46, 50, 53, 57, 60, 62, 67] # Low Bb -> Chord
    print("  Ending.")
    for n in final_chord:
        port.send(mido.Message('note_on', note=n, velocity=50 + random.randint(0,10), channel=channel))
        time.sleep(0.05)
    
    time.sleep(3.0)
    for n in final_chord:
        port.send(mido.Message('note_off', note=n, velocity=0, channel=channel))
    
    print("Jazz session complete.")



