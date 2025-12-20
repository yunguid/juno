"""Multi-layer beats using multiple MIDI channels"""
import time
import mido
from midi_utils import send_pitch_bend, panic

def multilayer_beat(port, loops=4):
    """
    Multi-layer beat - CLEAN VERSION
    Ch1: Pads | Ch2: Bass | Ch3: Lead | Ch10: Drums
    """
    CH_PAD = 0
    CH_BASS = 1
    CH_LEAD = 2
    CH_DRUM = 9
    
    tempo = 80
    beat = 60 / tempo
    
    KICK, SNARE, HIHAT = 36, 38, 42
    
    pad_chords = [
        [48, 55, 60, 63],  # Cm
        [44, 51, 56, 60],  # Ab
        [51, 55, 58, 63],  # Eb
        [46, 53, 58, 62],  # Bb
    ]
    bass_roots = [36, 32, 39, 34]
    
    melodies = [
        [(72, 1.5, 95), (70, 0.5, 85), (67, 2.0, 90)],
        [(75, 1.0, 100), (72, 1.0, 88), (70, 2.0, 92)],
        [(67, 0.5, 85), (70, 0.5, 88), (72, 1.0, 95), (75, 2.0, 100)],
        [(75, 1.0, 95), (72, 1.0, 90), (70, 1.0, 88), (67, 1.0, 95)],
    ]

    melodies_variation = [
        [(79, 1.5, 98), (77, 0.5, 88), (75, 1.0, 92), (72, 1.0, 90)], # Higher G, F, Eb, C
        [(80, 1.0, 105), (79, 0.5, 90), (75, 0.5, 92), (72, 2.0, 95)], # Ab, G, Eb, C
        [(72, 0.5, 88), (75, 0.5, 92), (79, 0.5, 95), (82, 0.5, 98), (84, 2.0, 105)], # Run up to C6
        [(82, 1.0, 98), (79, 1.0, 92), (75, 1.0, 90), (74, 1.0, 88)], # Bb, G, Eb, D
    ]
    
    print(f"Playing MULTI-LAYER beat... ({loops} loops)")
    print("  Ch1: Pads | Ch2: Bass | Ch3: Lead | Ch10: Drums")
    
    try:
        for loop in range(loops):
            print(f"  Loop {loop + 1}/{loops}")
            
            # Use variation for even numbered loops (2, 4, etc.)
            current_melodies = melodies_variation if (loop + 1) % 2 == 0 else melodies
            
            for bar in range(4):
                chord = pad_chords[bar]
                bass = bass_roots[bar]
                melody = current_melodies[bar]
                
                # Start pad
                for n in chord:
                    port.send(mido.Message('note_on', note=n, velocity=50, channel=CH_PAD))
                
                # Start bass
                port.send(mido.Message('note_on', note=bass, velocity=100, channel=CH_BASS))
                
                # Play melody and drums
                mel_time = 0
                for note, dur, vel in melody:
                    if mel_time == 0:
                        port.send(mido.Message('note_on', note=KICK, velocity=110, channel=CH_DRUM))
                        port.send(mido.Message('note_off', note=KICK, velocity=0, channel=CH_DRUM))
                    elif mel_time >= 1:
                        port.send(mido.Message('note_on', note=SNARE, velocity=100, channel=CH_DRUM))
                        port.send(mido.Message('note_off', note=SNARE, velocity=0, channel=CH_DRUM))
                    
                    port.send(mido.Message('note_on', note=HIHAT, velocity=70, channel=CH_DRUM))
                    port.send(mido.Message('note_off', note=HIHAT, velocity=0, channel=CH_DRUM))
                    
                    # Melody with bend scoop
                    send_pitch_bend(port, -800, CH_LEAD)
                    port.send(mido.Message('note_on', note=note, velocity=vel, channel=CH_LEAD))
                    
                    steps = 15
                    for i in range(steps):
                        bend = int(-800 + (800 * i / steps))
                        send_pitch_bend(port, bend, CH_LEAD)
                        time.sleep((dur * beat * 0.4) / steps)
                    
                    send_pitch_bend(port, 0, CH_LEAD)
                    time.sleep(dur * beat * 0.5)
                    
                    port.send(mido.Message('note_off', note=note, velocity=0, channel=CH_LEAD))
                    time.sleep(dur * beat * 0.1)
                    
                    mel_time += dur
                
                # Release
                for n in chord:
                    port.send(mido.Message('note_off', note=n, velocity=0, channel=CH_PAD))
                port.send(mido.Message('note_off', note=bass, velocity=0, channel=CH_BASS))
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        panic(port)
    
    print("Multi-layer beat complete!")

def full_beat_single_channel(port, channel=0, loops=4):
    """Full beat on a SINGLE channel - works with any basic setup"""
    tempo = 72
    beat = 60 / tempo
    
    print(f"Playing full beat (single channel)... ({loops} loops)")
    print("  Just have any sound selected on your MONTAGE!")
    
    for loop in range(loops):
        print(f"  Loop {loop + 1}/{loops}")
        
        bars = [
            {'bass': 36, 'chord': [48, 55, 60, 63], 'melody': [(72, 0.5), (70, 0.5), (67, 1.0), (None, 2.0)]},
            {'bass': 32, 'chord': [44, 51, 56, 60], 'melody': [(68, 1.0), (67, 0.5), (63, 0.5), (None, 2.0)]},
            {'bass': 39, 'chord': [51, 55, 58, 63], 'melody': [(67, 0.5), (70, 0.5), (72, 1.0), (75, 1.0), (None, 1.0)]},
            {'bass': 34, 'chord': [46, 53, 58, 62], 'melody': [(70, 2.0), (67, 1.5), (None, 0.5)]},
        ]
        
        for bar_data in bars:
            bass = bar_data['bass']
            chord = bar_data['chord']
            melody = bar_data['melody']
            
            port.send(mido.Message('note_on', note=bass, velocity=95, channel=channel))
            time.sleep(0.1)
            
            for note in chord:
                port.send(mido.Message('note_on', note=note, velocity=55, channel=channel))
                time.sleep(0.015)
            
            time.sleep(0.2)
            
            for note, duration in melody:
                if note:
                    port.send(mido.Message('note_on', note=note, velocity=80, channel=channel))
                time.sleep(duration * beat - 0.05)
                if note:
                    port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
                time.sleep(0.05)
            
            port.send(mido.Message('note_off', note=bass, velocity=0, channel=channel))
            for note in chord:
                port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            
            time.sleep(0.05)
    
    print("Beat complete!")

