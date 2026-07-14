from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

import librosa
import numpy as np
import soundfile as sf

from app.models import AnalysisResult, RootEvent

ProgressCallback = Callable[[int, str], None]

LOW_MIDI = 23   # B0
HIGH_MIDI = 60  # C4
HOP_LENGTH = 512
TARGET_SR = 22050

MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    dtype=float,
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    dtype=float,
)
PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}
MINOR_SCALE = {0, 2, 3, 5, 7, 8, 10}


def is_basic_pitch_available() -> bool:
    try:
        import basic_pitch  # noqa: F401
    except Exception:
        return False
    return True


def is_demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
    except Exception:
        return False
    return True


def analyze_audio(
    source_path: str,
    mode: str,
    use_demucs: bool,
    progress: ProgressCallback,
) -> AnalysisResult:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(source)

    cache_dir = _create_cache_dir(source)
    warnings: list[str] = []
    isolated_bass_path: Path | None = None

    progress(3, "音源を確認しています")

    analysis_source = source
    if use_demucs:
        if is_demucs_available():
            progress(6, "Demucsでベースを分離しています")
            try:
                isolated_bass_path = _separate_bass_with_demucs(source, cache_dir)
                analysis_source = isolated_bass_path
            except Exception as exc:
                warnings.append(f"Demucs分離失敗: {exc}")
                progress(10, "分離に失敗したため原曲解析へ切り替えます")
        else:
            warnings.append("Demucsが未導入のため、原曲から低域を抽出しました。")

    progress(14, "音源を読み込んでいます")
    y, sr = librosa.load(str(analysis_source), sr=TARGET_SR, mono=True)
    if y.size == 0:
        raise ValueError("音源データが空です。")

    peak = float(np.max(np.abs(y)))
    if peak > 0:
        y = y / peak

    duration = float(librosa.get_duration(y=y, sr=sr))

    progress(22, "打楽器と持続音を分離しています")
    harmonic, percussive = librosa.effects.hpss(y, margin=(1.0, 4.0))

    progress(28, "ベース帯域を抽出しています")
    bass = _extract_bass_band(harmonic, sr)

    bass_preview_path = cache_dir / "bass_focus.wav"
    sf.write(str(bass_preview_path), bass, sr, subtype="PCM_16")

    progress(35, "テンポと拍位置を解析しています")
    tempo, beat_times = _estimate_tempo_and_beats(percussive, sr, duration)

    progress(43, "キーを解析しています")
    key_name, key_root, key_is_minor = _estimate_key(harmonic, sr)

    ai_events: list[tuple[float, float, int, float]] = []
    if mode == "AI Hybrid":
        if is_basic_pitch_available():
            progress(48, "Basic PitchでAI音程解析を実行しています")
            try:
                ai_events = _run_basic_pitch(analysis_source)
            except Exception as exc:
                warnings.append(f"Basic Pitch解析失敗: {exc}")
        else:
            warnings.append("Basic Pitchが未導入のためPrecision DSPで解析しました。")

    progress(56, "低域の基音候補を追跡しています")
    f0, voiced_prob, frame_times, rms = _estimate_f0(bass, sr, mode)

    progress(68, "拍ごとのルート候補を評価しています")
    segment_candidates, segment_db = _score_segments(
        beat_times=beat_times,
        duration=duration,
        frame_times=frame_times,
        f0=f0,
        voiced_prob=voiced_prob,
        rms=rms,
        ai_events=ai_events,
    )

    progress(78, "前後の音とキーから誤認を補正しています")
    selected = _smooth_root_sequence(
        segment_candidates,
        key_root=key_root,
        key_is_minor=key_is_minor,
    )

    boundaries = _segment_boundaries(beat_times, duration)

    progress(85, "ベースの発音タイミングを追跡しています")
    cue_times = _estimate_root_cue_times(
        bass=bass,
        sr=sr,
        boundaries=boundaries,
        selected=selected,
        ai_events=ai_events,
    )

    roots: list[RootEvent] = []

    for index, midi in enumerate(selected):
        start, end = boundaries[index], boundaries[index + 1]
        score_map = segment_candidates[index]
        score_sum = sum(score_map.values())
        top_score = score_map.get(midi, 0.0) if midi is not None else 0.0
        confidence = 0.0 if score_sum <= 0 else min(1.0, top_score / score_sum)
        if midi is None:
            confidence = max(confidence, 0.05)

        source_label = "AI+DSP" if ai_events else "DSP"
        roots.append(
            RootEvent(
                beat_index=index + 1,
                start=float(start),
                end=float(end),
                midi=midi,
                confidence=float(confidence),
                db=float(segment_db[index]),
                cue_time=cue_times[index],
                source=source_label,
            )
        )

    progress(90, "短い誤検出とオクターブ誤認を整えています")
    _post_process_roots(roots)

    progress(100, "解析完了")
    return AnalysisResult(
        source_path=str(source),
        duration=duration,
        sample_rate=sr,
        tempo=tempo,
        key_name=key_name,
        mode=mode,
        roots=roots,
        beat_times=beat_times.tolist(),
        bass_preview_path=str(bass_preview_path),
        isolated_bass_path=str(isolated_bass_path) if isolated_bass_path else None,
        warnings=warnings,
    )


def _create_cache_dir(source: Path) -> Path:
    root = Path(tempfile.gettempdir()) / "BassCatcher"
    root.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(char if char.isalnum() else "_" for char in source.stem)[:48]
    target = root / safe_stem
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _separate_bass_with_demucs(source: Path, cache_dir: Path) -> Path:
    """Separate the bass stem inside the current process.

    Calling ``sys.executable -m demucs.separate`` does not work reliably once
    the application is frozen as an EXE, because ``sys.executable`` points to
    BassCatcher.exe rather than a normal Python interpreter.
    """
    from demucs.api import Separator, save_audio

    output_dir = cache_dir / "demucs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "bass.wav"

    separator = Separator(
        model="htdemucs",
        device="cpu",
        shifts=1,
        split=True,
        overlap=0.25,
        progress=False,
        jobs=0,
    )
    _, separated = separator.separate_audio_file(source)

    bass = separated.get("bass")
    if bass is None:
        raise RuntimeError("Demucsの解析結果にbassステムがありません。")

    save_audio(
        bass,
        str(output_path),
        samplerate=separator.samplerate,
        clip="rescale",
        bits_per_sample=16,
    )

    if not output_path.exists():
        raise FileNotFoundError("Demucsのbass.wavを保存できませんでした。")

    return output_path


def _extract_bass_band(y: np.ndarray, sr: int) -> np.ndarray:
    n_fft = 4096
    spectrum = librosa.stft(y, n_fft=n_fft, hop_length=HOP_LENGTH, window="hann")
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    low = 26.0
    full = 360.0
    fade_end = 520.0

    mask = np.zeros_like(frequencies, dtype=float)
    pass_band = (frequencies >= low) & (frequencies <= full)
    mask[pass_band] = 1.0

    fade = (frequencies > full) & (frequencies < fade_end)
    mask[fade] = 0.5 * (
        1.0 + np.cos(np.pi * (frequencies[fade] - full) / (fade_end - full))
    )

    low_fade = (frequencies >= 18.0) & (frequencies < low)
    mask[low_fade] = (frequencies[low_fade] - 18.0) / (low - 18.0)

    filtered = spectrum * mask[:, np.newaxis]
    bass = librosa.istft(filtered, hop_length=HOP_LENGTH, length=len(y))
    bass = librosa.util.normalize(bass)
    return bass.astype(np.float32)


def _estimate_tempo_and_beats(
    percussive: np.ndarray,
    sr: int,
    duration: float,
) -> tuple[float, np.ndarray]:
    onset = librosa.onset.onset_strength(
        y=percussive,
        sr=sr,
        hop_length=HOP_LENGTH,
        aggregate=np.median,
    )
    tempo_value, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sr,
        hop_length=HOP_LENGTH,
        units="frames",
    )
    tempo = float(np.asarray(tempo_value).reshape(-1)[0]) if np.size(tempo_value) else 120.0
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0

    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP_LENGTH)
    beat_times = beat_times[(beat_times >= 0) & (beat_times < duration)]

    if len(beat_times) < 2:
        interval = 60.0 / tempo
        beat_times = np.arange(0.0, duration, interval, dtype=float)

    if len(beat_times) == 0 or beat_times[0] > 0.15:
        beat_times = np.insert(beat_times, 0, 0.0)

    return tempo, beat_times.astype(float)


def _estimate_key(harmonic: np.ndarray, sr: int) -> tuple[str, int, bool]:
    try:
        chroma = librosa.feature.chroma_cqt(
            y=harmonic,
            sr=sr,
            hop_length=HOP_LENGTH,
        )
        energy = np.nan_to_num(np.mean(chroma, axis=1))
    except Exception:
        chroma = librosa.feature.chroma_stft(
            y=harmonic,
            sr=sr,
            hop_length=HOP_LENGTH,
        )
        energy = np.nan_to_num(np.mean(chroma, axis=1))

    if np.max(energy) <= 0:
        return "Unknown", 0, False

    energy = energy / (np.linalg.norm(energy) + 1e-9)
    major_profile = MAJOR_PROFILE / np.linalg.norm(MAJOR_PROFILE)
    minor_profile = MINOR_PROFILE / np.linalg.norm(MINOR_PROFILE)

    best_score = -np.inf
    best_root = 0
    best_minor = False

    for root in range(12):
        major_score = float(np.dot(energy, np.roll(major_profile, root)))
        minor_score = float(np.dot(energy, np.roll(minor_profile, root)))

        if major_score > best_score:
            best_score = major_score
            best_root = root
            best_minor = False
        if minor_score > best_score:
            best_score = minor_score
            best_root = root
            best_minor = True

    mode_name = "minor" if best_minor else "major"
    return f"{PITCH_CLASSES[best_root]} {mode_name}", best_root, best_minor


def _estimate_f0(
    bass: np.ndarray,
    sr: int,
    mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    frame_length = 2048 if mode == "Fast" else 4096
    fmin = librosa.note_to_hz("B0")
    fmax = librosa.note_to_hz("E4")

    rms = librosa.feature.rms(
        y=bass,
        frame_length=frame_length,
        hop_length=HOP_LENGTH,
    )[0]
    frame_times = librosa.frames_to_time(
        np.arange(len(rms)),
        sr=sr,
        hop_length=HOP_LENGTH,
    )

    if mode == "Fast":
        f0 = librosa.yin(
            bass,
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            frame_length=frame_length,
            hop_length=HOP_LENGTH,
        )
        threshold = np.percentile(rms, 35) if len(rms) else 0.0
        voiced_prob = np.clip(rms / (np.percentile(rms, 90) + 1e-9), 0.0, 1.0)
        f0 = np.where(rms >= threshold, f0, np.nan)
    else:
        f0, voiced_flag, voiced_prob = librosa.pyin(
            bass,
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            frame_length=frame_length,
            hop_length=HOP_LENGTH,
            fill_na=np.nan,
        )
        voiced_prob = np.nan_to_num(voiced_prob, nan=0.0)
        f0 = np.where(voiced_flag, f0, np.nan)

    length = min(len(f0), len(voiced_prob), len(frame_times), len(rms))
    return (
        np.asarray(f0[:length], dtype=float),
        np.asarray(voiced_prob[:length], dtype=float),
        np.asarray(frame_times[:length], dtype=float),
        np.asarray(rms[:length], dtype=float),
    )


def _run_basic_pitch(source: Path) -> list[tuple[float, float, int, float]]:
    from basic_pitch.inference import predict

    _, _, note_events = predict(
        str(source),
        minimum_frequency=float(librosa.note_to_hz("B0")),
        maximum_frequency=float(librosa.note_to_hz("C4")),
    )

    parsed: list[tuple[float, float, int, float]] = []
    for event in note_events:
        try:
            start = float(event[0])
            end = float(event[1])
            midi = int(round(float(event[2])))
            amplitude = float(event[3]) if len(event) > 3 else 0.7
        except (TypeError, ValueError, IndexError):
            continue
        if LOW_MIDI <= midi <= HIGH_MIDI and end > start:
            parsed.append((start, end, midi, max(0.0, amplitude)))
    return parsed


def _segment_boundaries(beat_times: np.ndarray | Iterable[float], duration: float) -> np.ndarray:
    beats = np.asarray(list(beat_times), dtype=float)
    beats = beats[(beats >= 0) & (beats < duration)]
    if len(beats) == 0:
        beats = np.array([0.0], dtype=float)
    if beats[0] > 0.05:
        beats = np.insert(beats, 0, 0.0)

    boundaries = list(beats)
    if boundaries[-1] < duration:
        boundaries.append(duration)
    return np.asarray(boundaries, dtype=float)


def _score_segments(
    beat_times: np.ndarray,
    duration: float,
    frame_times: np.ndarray,
    f0: np.ndarray,
    voiced_prob: np.ndarray,
    rms: np.ndarray,
    ai_events: list[tuple[float, float, int, float]],
) -> tuple[list[dict[int | None, float]], list[float]]:
    boundaries = _segment_boundaries(beat_times, duration)
    normalized_rms = rms / (np.percentile(rms, 95) + 1e-9)
    normalized_rms = np.clip(normalized_rms, 0.0, 1.5)

    all_candidates: list[dict[int | None, float]] = []
    segment_db: list[float] = []

    for segment_index in range(len(boundaries) - 1):
        start = boundaries[segment_index]
        end = boundaries[segment_index + 1]
        frame_mask = (frame_times >= start) & (frame_times < end)

        scores: dict[int | None, float] = defaultdict(float)
        selected_rms = rms[frame_mask]
        db = (
            float(librosa.amplitude_to_db(np.array([np.mean(selected_rms) + 1e-10]))[0])
            if selected_rms.size
            else -80.0
        )
        segment_db.append(db)

        segment_duration = max(0.05, end - start)
        indices = np.where(frame_mask)[0]

        for frame_index in indices:
            frequency = f0[frame_index]
            if not np.isfinite(frequency) or frequency <= 0:
                continue

            midi = int(round(float(librosa.hz_to_midi(frequency))))
            while midi > HIGH_MIDI:
                midi -= 12
            while midi < LOW_MIDI:
                midi += 12
            if not LOW_MIDI <= midi <= HIGH_MIDI:
                continue

            position = (frame_times[frame_index] - start) / segment_duration
            beat_head_weight = 1.25 - (0.35 * min(1.0, position))
            probability = max(0.05, float(voiced_prob[frame_index]))
            energy = max(0.03, float(normalized_rms[frame_index]))
            weight = probability * energy * beat_head_weight

            scores[midi] += weight

            # Mild support for the octave below, useful when the second harmonic dominates.
            if midi - 12 >= LOW_MIDI:
                scores[midi - 12] += weight * 0.13

        for ai_start, ai_end, ai_midi, ai_amplitude in ai_events:
            overlap = max(0.0, min(end, ai_end) - max(start, ai_start))
            if overlap <= 0:
                continue
            overlap_ratio = overlap / segment_duration
            scores[ai_midi] += max(0.05, ai_amplitude) * overlap_ratio * 1.45

        if scores:
            strongest = max(scores.values())
            floor = strongest * 0.10
            scores = {midi: score for midi, score in scores.items() if score >= floor}
            scores[None] = max(0.01, strongest * 0.05)
        else:
            scores = {None: 1.0}

        all_candidates.append(scores)

    return all_candidates, segment_db



def _estimate_root_cue_times(
    bass: np.ndarray,
    sr: int,
    boundaries: np.ndarray,
    selected: list[int | None],
    ai_events: list[tuple[float, float, int, float]],
) -> list[float | None]:
    """Estimate when the bass actually attacks inside each beat segment.

    The old notification path fired at every beat head, including sustained
    notes. That produced a rigid metronome-like feel. This function uses bass
    onsets and Basic Pitch note starts so notifications follow real attacks.
    """

    cue_hop = 256
    onset_env = librosa.onset.onset_strength(
        y=bass,
        sr=sr,
        hop_length=cue_hop,
        aggregate=np.median,
    )
    onset_env = np.nan_to_num(onset_env, nan=0.0, posinf=0.0, neginf=0.0)

    peak = float(np.max(onset_env)) if onset_env.size else 0.0
    if peak > 0:
        onset_env = onset_env / peak

    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=cue_hop,
        units="frames",
        backtrack=True,
        pre_max=3,
        post_max=3,
        pre_avg=7,
        post_avg=7,
        delta=0.075,
        wait=1,
    )
    onset_times = librosa.frames_to_time(
        onset_frames,
        sr=sr,
        hop_length=cue_hop,
    )
    onset_strengths = np.array(
        [
            float(onset_env[min(max(int(frame), 0), len(onset_env) - 1)])
            if len(onset_env)
            else 0.0
            for frame in onset_frames
        ],
        dtype=float,
    )

    cue_times: list[float | None] = []

    for index, midi in enumerate(selected):
        if midi is None:
            cue_times.append(None)
            continue

        start = float(boundaries[index])
        end = float(boundaries[index + 1])
        search_start = max(0.0, start - 0.085)
        search_end = max(search_start, end - 0.045)

        # Basic Pitch note starts are the most direct cue when available.
        matching_ai = [
            event
            for event in ai_events
            if search_start <= event[0] < search_end
            and event[2] % 12 == midi % 12
        ]
        if matching_ai:
            chosen = max(matching_ai, key=lambda event: (event[3], -event[0]))
            cue_times.append(max(0.0, float(chosen[0])))
            continue

        candidate_indices = np.where(
            (onset_times >= search_start) & (onset_times < search_end)
        )[0]
        if candidate_indices.size:
            best_index = max(
                candidate_indices.tolist(),
                key=lambda candidate: (
                    onset_strengths[candidate],
                    -onset_times[candidate],
                ),
            )
            cue_times.append(max(0.0, float(onset_times[best_index])))
            continue

        # When the note changes but no reliable onset was found, keep one
        # fallback cue at the beat head. Sustained notes remain silent.
        previous_midi = selected[index - 1] if index > 0 else None
        if index == 0 or previous_midi != midi:
            cue_times.append(start)
        else:
            cue_times.append(None)

    return cue_times

def _smooth_root_sequence(
    candidates: list[dict[int | None, float]],
    key_root: int,
    key_is_minor: bool,
) -> list[int | None]:
    if not candidates:
        return []

    scale = MINOR_SCALE if key_is_minor else MAJOR_SCALE

    states_per_segment: list[list[int | None]] = []
    for score_map in candidates:
        ranked = sorted(
            (item for item in score_map.items() if item[0] is not None),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        states = [midi for midi, _ in ranked]
        states.append(None)
        states_per_segment.append(states)

    costs: list[dict[int | None, float]] = []
    back: list[dict[int | None, int | None]] = []

    first_cost: dict[int | None, float] = {}
    first_back: dict[int | None, int | None] = {}

    for state in states_per_segment[0]:
        first_cost[state] = _emission_score(candidates[0], state, key_root, scale)
        first_back[state] = None

    costs.append(first_cost)
    back.append(first_back)

    for index in range(1, len(candidates)):
        current_costs: dict[int | None, float] = {}
        current_back: dict[int | None, int | None] = {}

        for state in states_per_segment[index]:
            emission = _emission_score(candidates[index], state, key_root, scale)
            best_previous = None
            best_value = -np.inf

            for previous, previous_value in costs[index - 1].items():
                value = previous_value + _transition_score(previous, state) + emission
                if value > best_value:
                    best_value = value
                    best_previous = previous

            current_costs[state] = best_value
            current_back[state] = best_previous

        costs.append(current_costs)
        back.append(current_back)

    final_state = max(costs[-1], key=costs[-1].get)
    sequence: list[int | None] = [final_state]

    for index in range(len(candidates) - 1, 0, -1):
        final_state = back[index][final_state]
        sequence.append(final_state)

    sequence.reverse()
    return sequence


def _emission_score(
    score_map: dict[int | None, float],
    state: int | None,
    key_root: int,
    scale: set[int],
) -> float:
    total = sum(score_map.values()) + 1e-9
    probability = max(1e-7, score_map.get(state, 1e-7) / total)
    score = math.log(probability)

    if state is None:
        return score - 0.18

    degree = (state % 12 - key_root) % 12
    score += 0.10 if degree in scale else -0.07

    # Prefer playable root register while not forbidding higher positions.
    if state > 52:
        score -= 0.05 * (state - 52)

    return score


def _transition_score(previous: int | None, current: int | None) -> float:
    if previous is None and current is None:
        return 0.12
    if previous is None or current is None:
        return -0.16
    if previous == current:
        return 0.24

    distance = abs(current - previous)
    if distance <= 5:
        return -0.025 * distance
    if distance <= 12:
        return -0.13 - (0.018 * (distance - 5))
    return -0.35 - (0.035 * (distance - 12))


def _post_process_roots(roots: list[RootEvent]) -> None:
    if len(roots) < 3:
        return

    for index in range(1, len(roots) - 1):
        previous = roots[index - 1]
        current = roots[index]
        following = roots[index + 1]

        if (
            previous.midi is not None
            and following.midi == previous.midi
            and current.midi is not None
            and current.midi != previous.midi
            and current.confidence < 0.42
        ):
            current.midi = previous.midi
            current.confidence = min(previous.confidence, following.confidence) * 0.85

        if current.midi is not None and previous.midi is not None:
            if abs(current.midi - previous.midi) == 12 and current.confidence < 0.48:
                current.midi = previous.midi
