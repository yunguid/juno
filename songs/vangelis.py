"""Vangelis-style cinematic melody - Blade Runner vibes"""
import time
import mido
from midi_utils import send_cc, send_pitch_bend

def vangelis_melody(port, channel=0):
    """
    Vangelis-style cinematic melody - slow, expressive, Blade Runner vibes
    Works best with a lush pad/string sound
    """
    melody = [
        # Opening phrase - rising
        (62, 85, 2.0, 0, 0),       # D4 - held
        (65, 90, 1.5, 0, 0),       # F4
        (67, 95, 2.5, 0, 500),     # G4 - slight bend up
        (69, 100, 3.0, 0, 0),      # A4 - peak, sustained
        
        # Descending answer
        (67, 85, 1.2, 0, 0),       # G4
        (65, 80, 1.0, 0, -400),    # F4 - bend down
        (62, 90, 2.5, 0, 0),       # D4
        
        # Second phrase - more emotional
        (69, 95, 1.5, -300, 0),    # A4 - scoop up
        (72, 100, 2.0, 0, 600),    # C5 - climax with bend
        (71, 90, 1.8, 0, 0),       # B4
        (69, 85, 2.2, 0, -300),    # A4 - falling
        (67, 80, 3.0, 0, 0),       # G4 - resolve
        
        # Final resolution
        (65, 75, 1.5, 0, 0),       # F4
        (64, 80, 1.2, 0, 400),     # E4 - tension
        (62, 90, 4.0, 0, 0),       # D4 - final resolve, long hold
    ]
    
    print("Playing Vangelis-style melody... (Blade Runner vibes)")
    send_cc(port, 1, 40, channel)
    
    for note, vel, dur, bend_start, bend_end in melody:
        send_pitch_bend(port, bend_start, channel)
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        
        if bend_start != bend_end:
            steps = 20
            bend_step = (bend_end - bend_start) / steps
            step_time = dur / steps
            for i in range(steps):
                time.sleep(step_time)
                send_pitch_bend(port, int(bend_start + bend_step * i), channel)
        else:
            time.sleep(dur)
        
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        send_pitch_bend(port, 0, channel)
        time.sleep(0.08)
    
    send_cc(port, 1, 0, channel)
    print("Melody complete.")

def vangelis_melody_variation(port, channel=0):
    """
    Variation of Vangelis style - Rich chords + Melody (Blade Runner 2049 vibes)
    """
    # (Chord Notes), [Melody Notes: (note, vel, dur, bend_start, bend_end)]
    sections = [
        # Dm9 pad - Wide, open sound
        ([38, 50, 57, 60, 64, 69], [ 
            (74, 85, 2.0, 0, 0),       # D5
            (77, 90, 1.5, 0, 0),       # F5
        ]),
        
        # Bbmaj7#11 - Lydian floaty feel
        ([34, 46, 53, 58, 62, 69], [ 
            (79, 95, 2.5, 0, 300),     # G5 bend
            (81, 100, 3.0, 0, 0),      # A5
        ]),
        
        # Gm11 - Deep and mysterious
        ([31, 43, 50, 55, 58, 65], [
            (79, 90, 0.5, 0, 0),       # G5
            (77, 88, 0.5, 0, 0),       # F5
            (74, 85, 0.5, 0, 0),       # D5
            (72, 82, 0.5, 0, 0),       # C5
            (69, 90, 2.0, 0, 0),       # A4
        ]),
        
        # C13sus4 -> C13 - Resolution with tension
        ([36, 48, 55, 60, 64, 67], [
            (72, 92, 1.0, 0, 0),       # C5
            (74, 95, 1.0, 0, 0),       # D5
            (77, 98, 1.0, 0, 500),     # F5 bend
        ]),
        
        # Fmaj9 - Massive final chord
        ([29, 41, 48, 53, 57, 60, 64], [
             (81, 100, 4.0, 0, -200),   # A5 long hold with slight fall
        ]),
    ]
    
    print("Playing Vangelis variation... (Blade Runner 2049 vibes)")
    send_cc(port, 1, 60, channel) # Open filter a bit
    
    for chord_notes, melody_line in sections:
        # Trigger Chord (Pad)
        for c_note in chord_notes:
            port.send(mido.Message('note_on', note=c_note, velocity=60, channel=channel))
            time.sleep(0.02) # Strum slightly
            
        # Play Melody over chord
        for note, vel, dur, bend_start, bend_end in melody_line:
            send_pitch_bend(port, bend_start, channel)
            port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            
            if bend_start != bend_end:
                steps = 20
                bend_step = (bend_end - bend_start) / steps
                step_time = dur / steps
                for i in range(steps):
                    time.sleep(step_time)
                    send_pitch_bend(port, int(bend_start + bend_step * i), channel)
            else:
                time.sleep(dur)
            
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            send_pitch_bend(port, 0, channel)
            time.sleep(0.05)
            
        # Release Chord
        for c_note in chord_notes:
            port.send(mido.Message('note_off', note=c_note, velocity=0, channel=channel))
        time.sleep(0.1)
    
    send_cc(port, 1, 0, channel)
    print("Variation complete.")

def vangelis_melody_variation_2(port, channel=0):
    """
    Longer, structured Vangelis composition (Tears in Rain)
    Theme A (Brass) -> Theme B (Tension) -> Climax -> Outro
    """
    print("Playing Vangelis Composition #2 (Tears in Rain style)...")
    
    # --- HELPER FUNCTIONS ---
    def play_chord(notes, vel=55):
        for n in notes:
            port.send(mido.Message('note_on', note=n, velocity=vel, channel=channel))
            time.sleep(0.02)
            
    def release_chord(notes):
        for n in notes:
            port.send(mido.Message('note_off', note=n, velocity=0, channel=channel))

    def play_phrase(melody_data):
        for note, vel, dur, bend_start, bend_end in melody_data:
            send_pitch_bend(port, bend_start, channel)
            port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            
            if bend_start != bend_end:
                steps = 30 # Smoother bends
                bend_step = (bend_end - bend_start) / steps
                step_time = dur / steps
                for i in range(steps):
                    time.sleep(step_time)
                    send_pitch_bend(port, int(bend_start + bend_step * i), channel)
            else:
                time.sleep(dur)
            
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            send_pitch_bend(port, 0, channel)
            time.sleep(0.05)

    # --- SECTION 1: ATMOSPHERE (Gm9) ---
    print("  Section 1: Atmosphere...")
    send_cc(port, 1, 30, channel) # Darker
    chord_1 = [31, 38, 50, 55, 58, 65] # Gm9 (deep)
    play_chord(chord_1, 50)
    time.sleep(2.0)
    
    # Slow rising motif
    play_phrase([
        (58, 70, 1.5, 0, 0),    # Bb3
        (62, 75, 1.5, 0, 0),    # D4
        (65, 80, 2.0, 0, 200),  # F4 bend up
    ])
    release_chord(chord_1)
    time.sleep(0.5)

    # --- SECTION 2: THEME A (Ebmaj7#11) ---
    print("  Section 2: The Awakening...")
    send_cc(port, 1, 65, channel) # Brighter
    chord_2 = [39, 51, 55, 58, 63, 69] # Ebmaj7#11
    play_chord(chord_2, 65)
    
    play_phrase([
        (74, 95, 1.5, 0, 0),       # D5
        (75, 90, 0.5, 0, 0),       # Eb5
        (79, 100, 2.5, 0, 400),    # G5 soaring
        (77, 90, 1.5, 0, -200),    # F5 fall
        (74, 85, 2.0, 0, 0),       # D5
    ])
    release_chord(chord_2)
    time.sleep(0.2)

    # --- SECTION 3: TENSION (Cm11 -> D7alt) ---
    print("  Section 3: Tension...")
    chord_3 = [36, 48, 55, 58, 62] # Cm11
    play_chord(chord_3, 60)
    
    play_phrase([
        (72, 85, 1.0, 0, 0),       # C5
        (70, 80, 1.0, 0, 0),       # Bb4
        (67, 85, 2.0, 0, 0),       # G4
    ])
    release_chord(chord_3)
    
    # The V chord (D7alt)
    chord_4 = [38, 48, 54, 57, 63] # D7#9#5
    play_chord(chord_4, 70)
    send_cc(port, 1, 80, channel) # Very bright
    
    play_phrase([
        (66, 90, 0.5, 0, 0),       # F#4
        (69, 95, 0.5, 0, 0),       # A4
        (72, 100, 0.5, 0, 0),      # C5
        (75, 105, 2.5, 0, 300),    # Eb5 (tension!)
    ])
    release_chord(chord_4)

    # --- SECTION 4: CLIMAX & RESOLUTION (Gm -> F -> Eb) ---
    print("  Section 4: Release...")
    send_cc(port, 1, 90, channel) # Max brightness
    
    # Gm
    play_chord([43, 50, 55, 58, 62], 75)
    play_phrase([(79, 110, 2.0, -200, 0)]) # G5
    release_chord([43, 50, 55, 58, 62])
    
    # F
    play_chord([41, 48, 53, 57, 60], 70)
    play_phrase([(77, 100, 1.5, 0, 0)]) # F5
    release_chord([41, 48, 53, 57, 60])
    
    # Ebmaj9 (Final)
    send_cc(port, 1, 50, channel) # Soften
    chord_final = [39, 46, 53, 58, 62, 65]
    play_chord(chord_final, 60)
    
    play_phrase([
        (74, 85, 1.0, 0, 0),      # D5
        (72, 80, 1.0, 0, 0),      # C5
        (70, 75, 1.0, 0, 0),      # Bb4
        (67, 70, 4.0, 0, 0),      # G4 fade out
    ])
    
    time.sleep(1.0)
    release_chord(chord_final)
    send_cc(port, 1, 0, channel)
    print("Composition complete.")

