from __future__ import annotations

from pathlib import Path
from typing import Callable

import librosa
import numpy as np
import soundfile as sf

ProgressCallback = Callable[[int, str], None]


def render_transformed_audio(
    source_path: str,
    output_path: str,
    tempo_ratio: float,
    semitones: float,
    progress: ProgressCallback,
) -> str:
    source = Path(source_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    progress(8, "音源を読み込んでいます")
    audio, sr = librosa.load(str(source), sr=None, mono=False)

    if audio.ndim == 1:
        channels = [audio]
    else:
        channels = [audio[index] for index in range(audio.shape[0])]

    processed_channels: list[np.ndarray] = []

    for index, channel in enumerate(channels):
        progress(20 + int((index / max(1, len(channels))) * 45), f"チャンネル{index + 1}を変換しています")
        transformed = np.asarray(channel, dtype=np.float32)

        if abs(tempo_ratio - 1.0) > 1e-3:
            transformed = librosa.effects.time_stretch(
                y=transformed,
                rate=float(tempo_ratio),
            )

        if abs(semitones) > 1e-3:
            transformed = librosa.effects.pitch_shift(
                y=transformed,
                sr=sr,
                n_steps=float(semitones),
            )

        processed_channels.append(transformed)

    progress(75, "チャンネルを統合しています")
    minimum_length = min(len(channel) for channel in processed_channels)
    processed_channels = [channel[:minimum_length] for channel in processed_channels]

    if len(processed_channels) == 1:
        output = processed_channels[0]
    else:
        output = np.stack(processed_channels, axis=1)

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.98:
        output = output / peak * 0.98

    progress(88, "WAVを書き出しています")
    sf.write(str(target), output, sr, subtype="PCM_16")
    progress(100, "変換完了")
    return str(target)
