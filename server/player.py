"""Sample player engine - converts Sample to MIDI and plays on M8X"""
import mido
import time
import threading
from dataclasses import dataclass
from typing import Callable
from .models import Sample, Layer, Note, SoundType, SOUND_CHANNELS, note_to_midi
from .logger import get_logger

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
                        return True
                    except Exception as e:
                        log.error(f"Failed to connect to {port_name}: {e}")
        
        log.error(f"No MONTAGE found. Available ports: {available}")
        return False

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

    def _compile_sample(self, sample: Sample) -> list[ScheduledEvent]:
        """Convert a Sample to a list of scheduled MIDI events"""
        events: list[ScheduledEvent] = []
        beat_duration = 60.0 / sample.bpm

        for layer in sample.layers:
            if layer.muted:
                continue

            channel = SOUND_CHANNELS[layer.sound]

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
