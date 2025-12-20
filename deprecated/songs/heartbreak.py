"""808s and Heartbreak style - Kanye West"""
import time
import mido
from midi_utils import send_pitch_bend

def heartbreak_808s(port, channel=0, loops=4):
    """
    808s and Heartbreak style - Kanye West
    Cold, minimal, emotional, lots of space
    Key of C minor
    """
    tempo = 78
    beat = 60 / tempo
    
    chords = {
        'Cm': [48, 55, 60, 63],
        'Ab': [44, 51, 56, 60],
        'Eb': [51, 55, 58, 63],
        'Bb': [46, 53, 58, 62],
        'Fm': [41, 48, 53, 60],
        'Gm': [43, 50, 55, 58],
    }
    
    bass_notes = {'C': 36, 'Ab': 32, 'Eb': 39, 'Bb': 34, 'F': 29, 'G': 31}
    
    def play_808_hit(note, duration, vel=100):
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        time.sleep(duration * beat)
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
    
    def play_cold_chord(notes, duration, vel=55):
        for note in notes:
            port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            time.sleep(0.01)
        time.sleep(duration * beat - 0.05)
        for note in notes:
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
    
    def play_melody_note(note, duration, vel=80, bend=0):
        if bend:
            send_pitch_bend(port, bend, channel)
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        time.sleep(duration * beat)
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        if bend:
            send_pitch_bend(port, 0, channel)
    
    print(f"Playing 808s and Heartbreak style... ({loops} loops)")
    print("  Cold. Minimal. Emotional.")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        
        # Bar 1: Cm
        play_808_hit(bass_notes['C'], 0.5, 110)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Cm'], 2.5, 50)
        play_melody_note(72, 0.75, 75)
        play_melody_note(70, 0.25, 70)
        
        # Bar 2: Ab
        play_808_hit(bass_notes['Ab'], 0.5, 105)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Ab'], 2.5, 48)
        play_melody_note(68, 1.0, 78, -200)
        
        # Bar 3: Eb
        play_808_hit(bass_notes['Eb'], 0.5, 108)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Eb'], 2.0, 52)
        play_melody_note(67, 0.5, 72)
        play_melody_note(70, 0.5, 80)
        play_melody_note(72, 0.5, 85)
        
        # Bar 4: Bb
        play_808_hit(bass_notes['Bb'], 0.5, 100)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Bb'], 2.0, 45)
        play_melody_note(70, 1.5, 82, 300)
        
        # Bar 5: Cm variation
        play_808_hit(bass_notes['C'], 0.25, 115)
        time.sleep(0.25 * beat)
        play_808_hit(bass_notes['C'], 0.25, 90)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Cm'], 2.5, 55)
        play_melody_note(75, 0.5, 88)
        play_melody_note(72, 0.5, 80)
        
        # Bar 6: Fm
        play_808_hit(bass_notes['F'], 0.5, 102)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Fm'], 2.5, 50)
        play_melody_note(68, 1.0, 75)
        
        # Bar 7: Ab
        play_808_hit(bass_notes['Ab'], 0.5, 100)
        time.sleep(0.75 * beat)
        play_cold_chord(chords['Ab'], 2.25, 48)
        play_melody_note(67, 0.5, 70)
        play_melody_note(65, 0.5, 68)
        
        # Bar 8: Gm
        play_808_hit(bass_notes['G'], 0.75, 95)
        time.sleep(0.25 * beat)
        play_cold_chord(chords['Gm'], 2.0, 52)
        play_melody_note(70, 0.5, 78)
        play_melody_note(67, 1.0, 85, -400)
        
        time.sleep(1.0 * beat)
    
    print("808s complete. Welcome to heartbreak.")

def heartbreak_variation(port, channel=0, loops=4):
    """
    Variation of 808s style - More melodic movement
    """
    tempo = 78
    beat = 60 / tempo
    
    chords = {
        'Cm': [48, 55, 60, 63],
        'Ab': [44, 51, 56, 60],
        'Eb': [51, 55, 58, 63],
        'Bb': [46, 53, 58, 62],
        'Fm': [41, 48, 53, 60],
        'Gm': [43, 50, 55, 58],
    }
    
    bass_notes = {'C': 36, 'Ab': 32, 'Eb': 39, 'Bb': 34, 'F': 29, 'G': 31}
    
    def play_808_hit(note, duration, vel=100):
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        time.sleep(duration * beat)
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
    
    def play_cold_chord(notes, duration, vel=55):
        for note in notes:
            port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            time.sleep(0.01)
        time.sleep(duration * beat - 0.05)
        for note in notes:
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))

    def play_melody_note(note, duration, vel=80, bend=0):
        if bend:
            send_pitch_bend(port, bend, channel)
        port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
        time.sleep(duration * beat)
        port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        if bend:
            send_pitch_bend(port, 0, channel)

    print(f"Playing 808s Variation... ({loops} loops)")

    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        
        # Bar 1: Cm - Arpeggiated feel
        play_808_hit(bass_notes['C'], 0.5, 110)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Cm'], 2.0, 50)
        play_melody_note(72, 0.5, 75)   # C5
        play_melody_note(75, 0.5, 78)   # Eb5
        
        # Bar 2: Ab - High variation
        play_808_hit(bass_notes['Ab'], 0.5, 105)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Ab'], 2.0, 48)
        play_melody_note(77, 0.75, 82)  # F5
        play_melody_note(75, 0.25, 75)  # Eb5
        play_melody_note(72, 1.0, 78)   # C5
        
        # Bar 3: Eb - Faster movement
        play_808_hit(bass_notes['Eb'], 0.5, 108)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Eb'], 1.5, 52)
        play_melody_note(79, 0.5, 85)   # G5
        play_melody_note(77, 0.5, 80)   # F5
        play_melody_note(75, 0.5, 82)   # Eb5
        
        # Bar 4: Bb - Resolution with bend
        play_808_hit(bass_notes['Bb'], 0.5, 100)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Bb'], 2.0, 45)
        play_melody_note(74, 2.0, 80, 200) # D5 bend
        
        # Bar 5: Fm - Lower register response
        play_808_hit(bass_notes['F'], 0.5, 102)
        time.sleep(0.5 * beat)
        play_cold_chord(chords['Fm'], 2.0, 50)
        play_melody_note(68, 0.5, 75)   # Ab4
        play_melody_note(65, 0.5, 72)   # F4
        
        # Bar 6: Gm - Turnaround
        play_808_hit(bass_notes['G'], 0.75, 95)
        time.sleep(0.25 * beat)
        play_cold_chord(chords['Gm'], 1.5, 52)
        play_melody_note(67, 0.5, 78)   # G4
        play_melody_note(70, 0.5, 80)   # Bb4
        play_melody_note(74, 0.5, 85)   # D5
        
        time.sleep(1.0 * beat)

    print("Variation complete.")

