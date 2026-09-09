import base64
import secrets
import wave
from datetime import datetime, timezone
from pathlib import Path

import struct


RECORDINGS_DIR = Path("data/recordings")


class CallRecorder:
    """Creates a stereo WAV: caller on left, assistant on right."""

    def __init__(self, call_id: str):
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_call_id = "".join(char for char in call_id if char.isalnum() or char in "-_")[:50]
        self.filename = f"{stamp}-{safe_call_id or secrets.token_hex(5)}-{secrets.token_hex(6)}.wav"
        self.path = RECORDINGS_DIR / self.filename
        self._wav = wave.open(str(self.path), "wb")
        self._wav.setnchannels(2)
        self._wav.setsampwidth(2)
        self._wav.setframerate(8000)

    def write_pcmu(self, payload: str, channel: str) -> None:
        mono = self._ulaw_to_pcm16(base64.b64decode(payload))
        silence = b"\x00\x00" * (len(mono) // 2)
        frame = self._interleave(mono, silence) if channel == "caller" else self._interleave(silence, mono)
        self._wav.writeframesraw(frame)

    @staticmethod
    def _interleave(left: bytes, right: bytes) -> bytes:
        return b"".join(left[i:i + 2] + right[i:i + 2] for i in range(0, len(left), 2))

    @staticmethod
    def _ulaw_to_pcm16(encoded: bytes) -> bytes:
        """Decode G.711 mu-law without the removed Python `audioop` module."""
        samples: list[int] = []
        for byte in encoded:
            value = (~byte) & 0xFF
            magnitude = ((value & 0x0F) << 3) + 0x84
            magnitude <<= (value & 0x70) >> 4
            samples.append((0x84 - magnitude) if value & 0x80 else (magnitude - 0x84))
        return struct.pack(f"<{len(samples)}h", *samples)

    def close(self) -> Path:
        self._wav.close()
        return self.path
