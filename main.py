#!/usr/bin/env python3
"""Yamaha MONTAGE M MIDI Controller - Main Menu"""
import sys
from midi_utils import get_port, list_ports, panic, PORT_NAME
from songs import (
    vangelis_melody,
    vangelis_melody_variation,
    vangelis_melody_variation_2,
    rnb_chords,
    rnb_chords_2,
    rnb_dark,
    rnb_gospel,
    rnb_full_song,
    rnb_full_song_variation,
    heartbreak_808s,
    heartbreak_variation,
    multilayer_beat,
    full_beat_single_channel,
    bill_evans_jazz,
)

SONGS = {
    '1': ('Vangelis (Blade Runner)', vangelis_melody),
    '1v': ('Vangelis Variation (Blade Runner 2049)', vangelis_melody_variation),
    '1v2': ('Vangelis Composition #2 (Structured)', vangelis_melody_variation_2),
    '2': ('R&B Neo-Soul (Db major)', rnb_chords),
    '3': ('R&B Frank Ocean (Ab major)', rnb_chords_2),
    '4': ('R&B Dark/Weeknd (C# minor)', rnb_dark),
    '5': ('R&B Gospel (F major)', rnb_gospel),
    '6': ('R&B Full Song w/ Melody (Eb minor)', rnb_full_song),
    '6v': ('R&B Full Song Variation', rnb_full_song_variation),
    '7': ('808s & Heartbreak (C minor)', heartbreak_808s),
    '7v': ('808s Variation (More Melodic)', heartbreak_variation),
    '8': ('Multi-Layer Beat (4 channels)', multilayer_beat),
    '9': ('Single Channel Beat', full_beat_single_channel),
    '10': ('Bill Evans Jazz (Bb Major)', bill_evans_jazz),
}

def print_menu():
    print("\n" + "="*50)
    print("  YAMAHA MONTAGE M - MIDI PATTERN PLAYER")
    print("="*50)
    for key, (name, _) in SONGS.items():
        print(f"  [{key}] {name}")
    print("  [p] PANIC - Kill all notes")
    print("  [l] List MIDI ports")
    print("  [q] Quit")
    print("="*50)

def main():
    print(f"Connecting to {PORT_NAME}...")
    try:
        port = get_port()
        print("Connected!\n")
    except Exception as e:
        print(f"Error connecting: {e}")
        list_ports()
        return
    
    try:
        while True:
            print_menu()
            choice = input("\nSelect song: ").strip().lower()
            
            if choice == 'q':
                break
            elif choice == 'p':
                panic(port)
            elif choice == 'l':
                list_ports()
            elif choice in SONGS:
                name, func = SONGS[choice]
                print(f"\nPlaying: {name}")
                try:
                    # Multi-layer uses different signature
                    if choice in ['8', '9']:
                        loops = input("Loops (default 4): ").strip()
                        loops = int(loops) if loops else 4
                        func(port, loops=loops)
                    else:
                        loops = input("Loops (default 2): ").strip()
                        loops = int(loops) if loops else 2
                        if choice in ['1', '1v', '1v2']:
                            func(port)  # Vangelis doesn't take loops
                        else:
                            func(port, loops=loops)
                except KeyboardInterrupt:
                    print("\n\nInterrupted!")
                    panic(port)
            else:
                print("Invalid choice")
    finally:
        panic(port)
        port.close()
        print("\nDisconnected. Goodbye!")

if __name__ == "__main__":
    main()
