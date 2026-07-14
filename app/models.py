from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_note_name(midi: int | None) -> str:
    if midi is None:
        return "REST"
    octave = (midi // 12) - 1
    return f"{NOTE_NAMES[midi % 12]}{octave}"


def note_name_to_midi(note_name: str) -> int | None:
    cleaned = note_name.strip().upper()
    if cleaned in {"REST", "-", "--", "NONE"}:
        return None

    for candidate in sorted(NOTE_NAMES, key=len, reverse=True):
        if cleaned.startswith(candidate):
            octave_text = cleaned[len(candidate) :]
            try:
                octave = int(octave_text)
            except ValueError as exc:
                raise ValueError(f"Invalid note name: {note_name}") from exc
            return (octave + 1) * 12 + NOTE_NAMES.index(candidate)

    raise ValueError(f"Invalid note name: {note_name}")


@dataclass
class RootEvent:
    beat_index: int
    start: float
    end: float
    midi: int | None
    confidence: float
    db: float
    cue_time: float | None = None
    source: str = "DSP"
    manually_edited: bool = False

    @property
    def note_name(self) -> str:
        return midi_to_note_name(self.midi)

    @property
    def pitch_class(self) -> str:
        if self.midi is None:
            return "-"
        return NOTE_NAMES[self.midi % 12]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RootEvent":
        cue_time = payload.get("cue_time", payload.get("start"))
        return cls(
            beat_index=int(payload["beat_index"]),
            start=float(payload["start"]),
            end=float(payload["end"]),
            midi=None if payload.get("midi") is None else int(payload["midi"]),
            confidence=float(payload.get("confidence", 0.0)),
            db=float(payload.get("db", -80.0)),
            cue_time=None if cue_time is None else float(cue_time),
            source=str(payload.get("source", "DSP")),
            manually_edited=bool(payload.get("manually_edited", False)),
        )


@dataclass
class AnalysisResult:
    source_path: str
    duration: float
    sample_rate: int
    tempo: float
    key_name: str
    mode: str
    roots: list[RootEvent] = field(default_factory=list)
    beat_times: list[float] = field(default_factory=list)
    bass_preview_path: str | None = None
    isolated_bass_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def file_name(self) -> str:
        return Path(self.source_path).name

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "bass-catcher-session",
            "version": 1,
            "source_path": self.source_path,
            "duration": self.duration,
            "sample_rate": self.sample_rate,
            "tempo": self.tempo,
            "key_name": self.key_name,
            "mode": self.mode,
            "roots": [asdict(root) for root in self.roots],
            "beat_times": self.beat_times,
            "bass_preview_path": self.bass_preview_path,
            "isolated_bass_path": self.isolated_bass_path,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisResult":
        if payload.get("format") != "bass-catcher-session":
            raise ValueError("Bass Catcher session fileではありません。")

        return cls(
            source_path=str(payload["source_path"]),
            duration=float(payload["duration"]),
            sample_rate=int(payload["sample_rate"]),
            tempo=float(payload.get("tempo", 0.0)),
            key_name=str(payload.get("key_name", "Unknown")),
            mode=str(payload.get("mode", "Loaded session")),
            roots=[RootEvent.from_dict(item) for item in payload.get("roots", [])],
            beat_times=[float(value) for value in payload.get("beat_times", [])],
            bass_preview_path=payload.get("bass_preview_path"),
            isolated_bass_path=payload.get("isolated_bass_path"),
            warnings=[str(item) for item in payload.get("warnings", [])],
        )
