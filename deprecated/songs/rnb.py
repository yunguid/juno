"""R&B chord progressions - Neo-soul, Frank Ocean, Weeknd, Gospel vibes"""
import time
import mido

def rnb_chords(port, channel=0, loops=2):
    """Emotional R&B progression - neo-soul vibes (Db major)"""
    tempo = 65
    beat = 60 / tempo
    
    progression = [
        ([49, 56, 60, 63, 65], 75, 4),  # Dbmaj9
        ([46, 53, 58, 60, 65], 70, 4),  # Bbm9
        ([42, 54, 58, 61, 63], 80, 4),  # Gbmaj9
        ([43, 51, 55, 60, 63], 75, 2),  # Ab/G
        ([44, 51, 56, 60, 62], 78, 2),  # Ab13
        ([49, 56, 60, 63, 65], 72, 4),  # Dbmaj9
        ([51, 58, 62, 65, 67], 70, 4),  # Ebm9
        ([44, 51, 56, 59, 62], 75, 2),  # Ab9sus4
        ([44, 48, 56, 59, 67], 80, 2),  # Ab7#9
    ]
    
    print(f"Playing emotional R&B progression... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for notes, vel, beats in progression:
            for i, note in enumerate(notes):
                port.send(mido.Message('note_on', note=note, velocity=vel - (4-i)*3, channel=channel))
                time.sleep(0.03)
            time.sleep(beats * beat - 0.15)
            for note in notes:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            time.sleep(0.05)
    
    print("Progression complete.")

def rnb_chords_2(port, channel=0, loops=2):
    """Frank Ocean / Daniel Caesar vibes (Ab major)"""
    tempo = 58
    beat = 60 / tempo
    
    progression = [
        ([44, 48, 55, 60, 63], 72, 4),  # Abmaj7
        ([41, 48, 53, 60, 63], 68, 4),  # Fm9
        ([49, 53, 60, 63, 67], 75, 4),  # Dbmaj7#11
        ([51, 56, 58, 63, 65], 70, 2),  # Eb9sus4
        ([51, 55, 58, 63, 67], 78, 2),  # Eb13
        ([48, 55, 58, 62, 67], 70, 4),  # Cm9
        ([41, 48, 53, 58, 63], 72, 2),  # Fm11
        ([46, 53, 58, 60, 65], 80, 2),  # Bbm9
        ([51, 56, 60, 63, 65], 75, 2),  # Dbmaj9/Eb
        ([44, 51, 55, 60, 67], 70, 2),  # Abmaj9
    ]
    
    print(f"Playing R&B progression #2 (Frank Ocean vibes)... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for notes, vel, beats in progression:
            for i, note in enumerate(notes):
                port.send(mido.Message('note_on', note=note, velocity=vel - (4-i)*2, channel=channel))
                time.sleep(0.025)
            time.sleep(beats * beat - 0.12)
            for note in notes:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            time.sleep(0.04)
    
    print("Progression complete.")

def rnb_dark(port, channel=0, loops=2):
    """Dark R&B - The Weeknd / 6lack vibes (C# minor)"""
    tempo = 62
    beat = 60 / tempo
    
    progression = [
        ([49, 52, 56, 61, 64], 70, 4),  # C#m9
        ([45, 49, 56, 60, 63], 72, 4),  # Amaj7#11
        ([42, 49, 54, 57, 61], 68, 4),  # F#m11
        ([44, 48, 51, 56, 59], 80, 2),  # G#7#9
        ([44, 48, 51, 56, 57], 82, 2),  # G#7b9
        ([49, 52, 56, 61, 64], 70, 4),  # C#m9
        ([52, 56, 59, 63, 66], 75, 4),  # Emaj9
        ([51, 54, 57, 62], 72, 2),       # D#m7b5
        ([44, 49, 51, 56, 59], 78, 2),  # G#7sus4
        ([49, 52, 56, 60, 64], 74, 4),  # C#m(maj9)
    ]
    
    print(f"Playing dark R&B progression (Weeknd vibes)... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for notes, vel, beats in progression:
            for i, note in enumerate(notes):
                port.send(mido.Message('note_on', note=note, velocity=vel - (4-i)*2, channel=channel))
                time.sleep(0.02)
            time.sleep(beats * beat - 0.1)
            for note in notes:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            time.sleep(0.04)
    
    print("Progression complete.")

def rnb_gospel(port, channel=0, loops=2):
    """Gospel-influenced R&B - Kirk Franklin meets D'Angelo (F major)"""
    tempo = 55
    beat = 60 / tempo
    
    progression = [
        ([41, 48, 53, 57, 60], 75, 4),        # Fmaj9
        ([38, 45, 50, 53, 57, 60], 72, 4),    # Dm11
        ([46, 50, 53, 58, 62, 65], 80, 4),    # Bbmaj9#11
        ([45, 48, 52, 55, 60], 70, 2),        # Am7
        ([43, 50, 55, 58, 62], 75, 2),        # Gm9
        ([48, 53, 55, 58, 62, 65], 82, 2),    # C13sus4
        ([48, 52, 55, 58, 62, 65], 85, 2),    # C13
        ([45, 48, 53, 57, 60, 65], 78, 4),    # Fmaj9/A
        ([50, 53, 58, 62, 65], 72, 2),        # Bbmaj7/D
        ([47, 50, 53, 56, 59], 80, 2),        # Bdim7
        ([48, 53, 57, 60, 65], 75, 4),        # Fmaj9/C
    ]
    
    print(f"Playing gospel R&B progression (Kirk Franklin vibes)... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for notes, vel, beats in progression:
            for i, note in enumerate(notes):
                port.send(mido.Message('note_on', note=note, velocity=vel - (5-i)*2, channel=channel))
                time.sleep(0.035)
            time.sleep(beats * beat - 0.2)
            for note in notes:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            time.sleep(0.06)
    
    print("Progression complete.")

def rnb_full_song(port, channel=0, loops=2):
    """Full R&B piece with melody (Eb minor)"""
    tempo = 58
    beat = 60 / tempo
    
    def play_chord_with_melody(chord_notes, melody_sequence, chord_vel=65):
        for i, note in enumerate(chord_notes):
            port.send(mido.Message('note_on', note=note, velocity=chord_vel - i*2, channel=channel))
            time.sleep(0.02)
        
        for note, vel, duration in melody_sequence:
            if note:
                port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            time.sleep(duration * beat)
            if note:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        
        for note in chord_notes:
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        time.sleep(0.03)
    
    song_sections = [
        ([51, 54, 58, 62, 66], [(75, 85, 1.0), (73, 80, 0.5), (70, 90, 1.5), (68, 75, 0.5), (66, 85, 0.5)]),
        ([47, 54, 59, 62, 66], [(68, 88, 1.2), (70, 82, 0.8), (73, 95, 1.5), (70, 78, 0.5)]),
        ([44, 47, 51, 55, 60], [(68, 80, 0.75), (66, 75, 0.75), (63, 85, 1.0), (None, 0, 0.5), (66, 78, 1.0)]),
        ([46, 51, 53, 58, 63], [(70, 90, 1.0), (68, 85, 0.5), (70, 95, 0.5)]),
        ([46, 50, 53, 58, 63], [(73, 100, 1.2), (70, 85, 0.8)]),
        ([51, 54, 58, 62, 66], [(68, 82, 1.0), (66, 78, 1.0), (63, 90, 2.0)]),
        ([42, 54, 58, 61, 66], [(66, 85, 0.75), (68, 80, 0.75), (70, 88, 1.0), (73, 75, 0.5), (75, 92, 1.0)]),
        ([49, 53, 56, 60, 63], [(73, 88, 1.5), (70, 80, 0.5), (68, 75, 0.5), (66, 82, 1.5)]),
        ([51, 54, 58, 62, 67], [(63, 80, 1.0), (66, 75, 0.5), (63, 88, 2.5)]),
    ]
    
    print(f"Playing full R&B song with melody (Eb minor)... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for chord, melody in song_sections:
            play_chord_with_melody(chord, melody)
        time.sleep(0.5)
    
    print("Song complete.")

def rnb_full_song_variation(port, channel=0, loops=2):
    """Full R&B piece variation - More intricate melody (Eb minor)"""
    tempo = 58
    beat = 60 / tempo
    
    def play_chord_with_melody(chord_notes, melody_sequence, chord_vel=65):
        for i, note in enumerate(chord_notes):
            port.send(mido.Message('note_on', note=note, velocity=chord_vel - i*2, channel=channel))
            time.sleep(0.02)
        
        for note, vel, duration in melody_sequence:
            if note:
                port.send(mido.Message('note_on', note=note, velocity=vel, channel=channel))
            time.sleep(duration * beat)
            if note:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        
        for note in chord_notes:
            port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
        time.sleep(0.03)
    
    song_sections_var = [
        # Ebm9 - More syncopated
        ([51, 54, 58, 62, 66], [(75, 88, 0.75), (78, 85, 0.25), (75, 82, 1.0), (73, 78, 0.5), (70, 75, 0.5), (66, 85, 1.0)]),
        # Bmaj9 - Pentatonic run
        ([47, 54, 59, 62, 66], [(66, 85, 0.5), (68, 88, 0.5), (70, 90, 0.5), (73, 95, 1.0), (78, 100, 1.5)]),
        # Abm9 - Falling phrases
        ([44, 47, 51, 55, 60], [(75, 90, 0.75), (73, 85, 0.25), (70, 82, 1.0), (66, 78, 0.5), (63, 75, 1.5)]),
        # Bb7alt - Tension
        ([46, 51, 53, 58, 63], [(70, 95, 0.5), (73, 90, 0.5), (76, 92, 0.5), (75, 95, 0.5)]),
    ]
    
    print(f"Playing R&B song variation... ({loops} loops)")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        for chord, melody in song_sections_var:
            play_chord_with_melody(chord, melody)
        time.sleep(0.5)
    
    print("Song variation complete.")

