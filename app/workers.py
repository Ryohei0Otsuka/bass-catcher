from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from app.audio_analysis import analyze_audio
from app.audio_processing import render_transformed_audio


class AnalysisWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source_path: str,
        mode: str,
        use_demucs: bool,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.mode = mode
        self.use_demucs = use_demucs

    def run(self) -> None:
        try:
            result = analyze_audio(
                self.source_path,
                self.mode,
                self.use_demucs,
                lambda value, message: self.progress.emit(value, message),
            )
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.completed.emit(result)


class TransformWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        source_path: str,
        output_path: str,
        tempo_ratio: float,
        semitones: float,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.output_path = output_path
        self.tempo_ratio = tempo_ratio
        self.semitones = semitones

    def run(self) -> None:
        try:
            path = render_transformed_audio(
                source_path=self.source_path,
                output_path=self.output_path,
                tempo_ratio=self.tempo_ratio,
                semitones=self.semitones,
                progress=lambda value, message: self.progress.emit(value, message),
            )
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.completed.emit(path)
