"""Song modules for Yamaha MONTAGE M"""
from .vangelis import vangelis_melody, vangelis_melody_variation, vangelis_melody_variation_2
from .rnb import rnb_chords, rnb_chords_2, rnb_dark, rnb_gospel, rnb_full_song, rnb_full_song_variation
from .heartbreak import heartbreak_808s, heartbreak_variation
from .multilayer import multilayer_beat, full_beat_single_channel
from .jazz import bill_evans_jazz

__all__ = [
    'vangelis_melody',
    'vangelis_melody_variation',
    'vangelis_melody_variation_2',
    'rnb_chords',
    'rnb_chords_2', 
    'rnb_dark',
    'rnb_gospel',
    'rnb_full_song',
    'rnb_full_song_variation',
    'heartbreak_808s',
    'heartbreak_variation',
    'multilayer_beat',
    'full_beat_single_channel',
    'bill_evans_jazz',
]

