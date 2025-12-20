"""Sample player engine - converts Sample to MIDI and plays on M8X"""
import mido
import time
import threading
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING
from .models import Sample, Layer, Note, SoundType, SOUND_CHANNELS, note_to_midi, Patch
from .logger import get_logger

if TYPE_CHECKING:
    from .patches import get_patch_by_id

log = get_logger("player")

# Port name patterns for different platforms (matched with 'in' check)
MIDI_PORT_PATTERNS = [
    "MONTAGE M",  # Matches any MONTAGE M port
]


@dataclass
class ScheduledEvent:
    """A MIDI event scheduled at a specific time"""
    time: float           # Time in seconds from start
    message: mido.Message


class SamplePlayer:
    """Plays samples on the Yamaha M8X"""

    def __init__(self, port_name: str | None = None):
        self.port_name = port_name
        self.port: mido.ports.BaseOutput | None = None
        self._playing = False
        self._play_thread: threading.Thread | None = None
        self._on_playback_complete: Callable[[], None] | None = None
        self._current_position: float = 0.0  # Current playback position in seconds

    def connect(self) -> bool:
        """Connect to the MIDI port (auto-detect if not specified)"""
        available = mido.get_output_names()

        # If port specified, try that
        if self.port_name:
            try:
                log.debug(f"Attempting to connect to MIDI port: {self.port_name}")
                self.port = mido.open_output(self.port_name)
                log.info(f"MIDI connected: {self.port_name}")
                self._init_parts()
                return True
            except Exception as e:
                log.error(f"Failed to connect to {self.port_name}: {e}")
                return False

        # Auto-detect by matching port name patterns
        for pattern in MIDI_PORT_PATTERNS:
            for port_name in available:
                if pattern in port_name and "MIDI 1" in port_name:
                    try:
                        log.debug(f"Attempting to connect to MIDI port: {port_name}")
                        self.port = mido.open_output(port_name)
                        self.port_name = port_name
                        log.info(f"MIDI connected: {port_name}")
                        self._init_parts()
                        return True
                    except Exception as e:
                        log.error(f"Failed to connect to {port_name}: {e}")

        log.error(f"No MONTAGE found. Available ports: {available}")
        return False

    def _init_parts(self) -> None:
        """Initialize parts on connection - disable Kbd Ctrl for channels 0-2"""
        for part in range(3):  # Parts 1-3 (Bass, Pad, Lead)
            self._disable_kbd_ctrl(part)
        log.info("Disabled Kbd Ctrl for parts 1-3")

    def disconnect(self):
        """Disconnect from the MIDI port"""
        if self.port:
            self.panic()
            self.port.close()
            self.port = None

    def is_connected(self) -> bool:
        """Check if connected to MIDI port"""
        return self.port is not None

    def list_ports(self) -> list[str]:
        """List available MIDI output ports"""
        return mido.get_output_names()

    def panic(self):
        """Kill all notes on all channels immediately"""
        if not self.port:
            return
        log.debug("MIDI panic: killing all notes")
        for ch in range(16):
            # CC 120: All Sound Off - immediately silences (ignores release)
            self.port.send(mido.Message('control_change', control=120, value=0, channel=ch))
            # CC 123: All Notes Off - stops notes (respects release)
            self.port.send(mido.Message('control_change', control=123, value=0, channel=ch))
            # CC 121: Reset All Controllers
            self.port.send(mido.Message('control_change', control=121, value=0, channel=ch))
            # CC 64: Sustain Pedal Off
            self.port.send(mido.Message('control_change', control=64, value=0, channel=ch))

    def send_program_change(self, channel: int, bank_msb: int, bank_lsb: int, program: int) -> bool:
        """Send bank select and program change to a channel"""
        if not self.port:
            return False

        log.info(f"Program change: ch={channel} bank={bank_msb}/{bank_lsb} prog={program}")

        # Bank Select MSB (CC0)
        self.port.send(mido.Message('control_change', control=0, value=bank_msb, channel=channel))
        # Bank Select LSB (CC32)
        self.port.send(mido.Message('control_change', control=32, value=bank_lsb, channel=channel))
        # Program Change
        self.port.send(mido.Message('program_change', program=program, channel=channel))

        # Disable Keyboard Control for this part to prevent routing issues
        # This fixes the issue where Kbd Ctrl gets enabled after program change
        self._disable_kbd_ctrl(channel)

        return True

    def _disable_kbd_ctrl(self, part: int) -> None:
        """
        Disable Keyboard Control for a part via SysEx.
        When Kbd Ctrl is ON, the part receives MIDI from the local keyboard
        which can interfere with external MIDI control.

        SysEx format (MODX/Montage): F0 43 10 7F 1C 07 31 0p 17 00 F7
        - 43 = Yamaha
        - 10 = Device number
        - 7F 1C 07 = Model ID
        - 31 = Part parameter high address
        - 0p = Part number (0-7 for parts 1-8)
        - 17 = Keyboard Control Switch address
        - 00 = OFF

        Note: Montage M may use different addresses (4-byte vs 3-byte).
        If this doesn't work, check the Montage M Data List PDF.
        """
        if not self.port or part > 7:
            return

        # MODX/Montage classic format
        sysex_data = [
            0x43,  # Yamaha
            0x10,  # Device number
            0x7F,  # Model ID byte 1
            0x1C,  # Model ID byte 2
            0x07,  # Model ID byte 3
            0x31,  # High address (Part parameters)
            part,  # Mid address (Part number 0-7)
            0x17,  # Low address (Keyboard Control Switch)
            0x00,  # Data: OFF
        ]

        try:
            self.port.send(mido.Message('sysex', data=sysex_data))
            log.debug(f"Disabled Kbd Ctrl for part {part + 1}")
        except Exception as e:
            log.warning(f"Failed to send Kbd Ctrl SysEx for part {part}: {e}")

    def select_patch(self, sound_type: SoundType, patch: Patch) -> bool:
        """Select a patch for a sound type channel"""
        channel = SOUND_CHANNELS[sound_type]
        return self.send_program_change(
            channel,
            patch.bank_msb,
            patch.bank_lsb,
            patch.program
        )

    def preview_patch(self, sound_type: SoundType, patch: Patch) -> None:
        """Preview a patch by selecting it and playing a test phrase"""
        if not self.select_patch(sound_type, patch):
            return

        channel = SOUND_CHANNELS[sound_type]

        # Small delay after program change to let synth switch
        time.sleep(0.05)

        # Play a test phrase appropriate for the sound type
        if sound_type == SoundType.BASS:
            notes = [(36, 0.3), (40, 0.3), (43, 0.3)]  # C2, E2, G2
        elif sound_type == SoundType.PAD:
            # Play a chord
            chord = [60, 64, 67]  # C4 major chord
            for note in chord:
                self.port.send(mido.Message('note_on', note=note, velocity=80, channel=channel))
            time.sleep(1.0)
            for note in chord:
                self.port.send(mido.Message('note_off', note=note, velocity=0, channel=channel))
            return
        else:  # LEAD
            notes = [(72, 0.15), (76, 0.15), (79, 0.15), (84, 0.3)]  # C5, E5, G5, C6

        for midi_note, duration in notes:
            self.port.send(mido.Message('note_on', note=midi_note, velocity=80, channel=channel))
            time.sleep(duration)
            self.port.send(mido.Message('note_off', note=midi_note, velocity=0, channel=channel))

    def _compile_sample(self, sample: Sample) -> list[ScheduledEvent]:
        """Convert a Sample to a list of scheduled MIDI events"""
        # Import here to avoid circular imports
        from .patches import get_patch_by_id

        events: list[ScheduledEvent] = []
        beat_duration = 60.0 / sample.bpm

        for layer in sample.layers:
            if layer.muted:
                continue

            channel = SOUND_CHANNELS[layer.sound]

            # Send program change if patch is specified
            if layer.patch_id:
                patch = get_patch_by_id(layer.patch_id)
                if patch:
                    # Bank Select MSB
                    events.append(ScheduledEvent(
                        time=0.0,
                        message=mido.Message(
                            'control_change',
                            control=0,
                            value=patch.bank_msb,
                            channel=channel
                        )
                    ))
                    # Bank Select LSB
                    events.append(ScheduledEvent(
                        time=0.0,
                        message=mido.Message(
                            'control_change',
                            control=32,
                            value=patch.bank_lsb,
                            channel=channel
                        )
                    ))
                    # Program Change
                    events.append(ScheduledEvent(
                        time=0.0,
                        message=mido.Message(
                            'program_change',
                            program=patch.program,
                            channel=channel
                        )
                    ))

            # Set layer volume
            events.append(ScheduledEvent(
                time=0.0,
                message=mido.Message(
                    'control_change',
                    control=7,  # Volume CC
                    value=layer.volume,
                    channel=channel
                )
            ))

            # Set portamento (glide) settings
            events.append(ScheduledEvent(
                time=0.0,
                message=mido.Message(
                    'control_change',
                    control=65,  # Portamento On/Off
                    value=127 if layer.portamento else 0,
                    channel=channel
                )
            ))
            if layer.portamento:
                events.append(ScheduledEvent(
                    time=0.0,
                    message=mido.Message(
                        'control_change',
                        control=5,  # Portamento Time
                        value=layer.portamento_time,
                        channel=channel
                    )
                ))

            for note in layer.notes:
                start_time = note.start * beat_duration
                end_time = (note.start + note.duration) * beat_duration

                # Handle single note or chord
                pitches = note.pitch if isinstance(note.pitch, list) else [note.pitch]

                for pitch_name in pitches:
                    midi_note = note_to_midi(pitch_name)

                    # Note on
                    events.append(ScheduledEvent(
                        time=start_time,
                        message=mido.Message(
                            'note_on',
                            note=midi_note,
                            velocity=note.velocity,
                            channel=channel
                        )
                    ))

                    # Note off
                    events.append(ScheduledEvent(
                        time=end_time,
                        message=mido.Message(
                            'note_off',
                            note=midi_note,
                            velocity=0,
                            channel=channel
                        )
                    ))

        # Sort events by time
        events.sort(key=lambda e: e.time)
        return events

    def play(self, sample: Sample, on_complete: Callable[[], None] | None = None):
        """Play a sample (non-blocking)"""
        if not self.port:
            raise RuntimeError("Not connected to MIDI port")

        self.stop()  # Stop any current playback

        self._on_playback_complete = on_complete
        self._playing = True
        self._current_position = 0.0

        events = self._compile_sample(sample)
        total_duration = sample.duration_seconds

        log.info(f"Starting playback: {len(events)} MIDI events, {total_duration:.1f}s duration")

        def play_thread():
            start_time = time.perf_counter()
            events_sent = 0

            event_index = 0
            while self._playing and event_index < len(events):
                current_time = time.perf_counter() - start_time
                self._current_position = current_time

                # Send all events that should have occurred by now
                while event_index < len(events) and events[event_index].time <= current_time:
                    if self._playing and self.port:
                        msg = events[event_index].message
                        self.port.send(msg)
                        events_sent += 1
                        if msg.type == 'note_on' and msg.velocity > 0:
                            log.debug(f"MIDI: note_on ch={msg.channel} note={msg.note} vel={msg.velocity}")
                        elif msg.type == 'control_change' and msg.control in (5, 65):
                            cc_name = "portamento_time" if msg.control == 5 else "portamento_on"
                            log.debug(f"MIDI: {cc_name} ch={msg.channel} value={msg.value}")
                    event_index += 1

                # Small sleep to prevent busy-waiting
                time.sleep(0.001)

            # Wait for the full duration (for note releases)
            while self._playing and (time.perf_counter() - start_time) < total_duration:
                self._current_position = time.perf_counter() - start_time
                time.sleep(0.01)

            self._playing = False
            self._current_position = 0.0
            log.info(f"Playback finished: sent {events_sent} events")

            if self._on_playback_complete:
                self._on_playback_complete()

        self._play_thread = threading.Thread(target=play_thread, daemon=True)
        self._play_thread.start()

    def play_sync(self, sample: Sample):
        """Play a sample (blocking)"""
        done = threading.Event()
        self.play(sample, on_complete=done.set)
        done.wait()

    def stop(self):
        """Stop playback"""
        if self._playing:
            log.info("Stopping playback")
        self._playing = False
        if self._play_thread:
            self._play_thread.join(timeout=0.5)
            self._play_thread = None
        self.panic()
        self._current_position = 0.0

    def is_playing(self) -> bool:
        """Check if currently playing"""
        return self._playing

    def get_position(self) -> float:
        """Get current playback position in seconds"""
        return self._current_position


# Singleton player instance
_player: SamplePlayer | None = None


def get_player() -> SamplePlayer:
    """Get the global player instance"""
    global _player
    if _player is None:
        _player = SamplePlayer()
    return _player
