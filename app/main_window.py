from __future__ import annotations

import tempfile
import traceback
import wave
from pathlib import Path

import numpy as np

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.audio_analysis import is_basic_pitch_available, is_demucs_available
from app.exporters import (
    export_csv,
    export_musicxml,
    export_pdf,
    export_session,
    load_session,
)
from app.models import AnalysisResult, RootEvent, midi_to_note_name
from app.widgets.cyber_panel import CyberPanel
from app.widgets.piano_keyboard import PianoKeyboard
from app.widgets.pitch_timeline import PitchTimeline
from app.workers import AnalysisWorker, TransformWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Bass Catcher｜ベース耳コピ支援")
        self.resize(1480, 900)
        self.setMinimumSize(1120, 700)

        self.source_path: Path | None = None
        self.analysis_result: AnalysisResult | None = None
        self.sources: dict[str, Path] = {}
        self.loop_a_ms = 0
        self.loop_b_ms = 0
        self.selected_root_index: int | None = None
        self.analysis_worker: AnalysisWorker | None = None
        self.transform_worker: TransformWorker | None = None
        self._pending_restore_position = 0
        self._pending_transform_tempo = 1.0
        self._pending_transform_semitones = 0
        self._last_notified_root_index: int | None = None
        self._detected_note_effects: dict[int, QSoundEffect] = {}

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.82)

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)

        self._build_ui()
        self._connect_signals()
        self._apply_styles()
        self._update_optional_engine_labels()
        self._prepare_detected_note_sounds()

        self.statusBar().showMessage("準備完了｜音源を読み込んでください")

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 16, 20, 16)
        root_layout.setSpacing(11)

        root_layout.addLayout(self._create_header())
        root_layout.addWidget(self._create_file_strip())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.addWidget(self._create_timeline_panel())
        splitter.addWidget(self._create_analysis_panel())
        splitter.setSizes([980, 380])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root_layout.addWidget(splitter, 1)

        root_layout.addWidget(self._create_transport_panel())

    def _create_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(14)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(0)

        title = QLabel("BASS // CATCHER")
        title.setObjectName("appTitle")
        self._add_neon_shadow(title, "#00F6FF", 24)

        subtitle = QLabel("ベースルート音解析・耳コピ支援")
        subtitle.setObjectName("appSubtitle")

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        self.system_status = QLabel("● 待機中")
        self.system_status.setObjectName("systemStatus")

        self.load_session_button = QPushButton("解析を読み込む")
        self.load_session_button.setObjectName("headerButton")

        self.import_button = QPushButton("音源を読み込む")
        self.import_button.setObjectName("primaryButton")

        header.addLayout(title_layout)
        header.addStretch(1)
        header.addWidget(self.system_status)
        header.addWidget(self.load_session_button)
        header.addWidget(self.import_button)
        return header

    def _create_file_strip(self) -> CyberPanel:
        panel = CyberPanel(accent="#FF2BD6")
        panel.setFixedHeight(66)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(17, 10, 17, 10)
        layout.setSpacing(12)

        label = QLabel("読み込み音源")
        label.setObjectName("sectionLabel")

        self.file_label = QLabel("音源が選択されていません")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(150)
        self.source_combo.addItem("原曲")

        self.duration_chip = QLabel("長さ --:--")
        self.duration_chip.setObjectName("dataChip")

        layout.addWidget(label)
        layout.addWidget(self._divider())
        layout.addWidget(self.file_label, 1)
        layout.addWidget(QLabel("再生音源"))
        layout.addWidget(self.source_combo)
        layout.addWidget(self.duration_chip)
        return panel

    def _create_timeline_panel(self) -> CyberPanel:
        panel = CyberPanel(accent="#00F6FF")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        axis = QLabel("音程表示 // B0 — C4")
        axis.setObjectName("sectionLabel")

        self.analysis_state_label = QLabel("解析：待機中")
        self.analysis_state_label.setObjectName("analysisState")

        header.addWidget(axis)
        header.addStretch(1)
        header.addWidget(self.analysis_state_label)

        canvas = QHBoxLayout()
        canvas.setSpacing(0)
        self.keyboard = PianoKeyboard()
        self.timeline = PitchTimeline()
        canvas.addWidget(self.keyboard)
        canvas.addWidget(self.timeline, 1)

        layout.addLayout(header)
        layout.addLayout(canvas, 1)
        return panel

    def _create_analysis_panel(self) -> CyberPanel:
        panel = CyberPanel(accent="#FF2BD6")
        panel.setMinimumWidth(350)
        panel.setMaximumWidth(470)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 12, 13, 12)
        layout.setSpacing(10)

        title = QLabel("解析・編集")
        title.setObjectName("sectionLabel")

        mode_layout = QGridLayout()
        mode_layout.setHorizontalSpacing(8)
        mode_layout.setVerticalSpacing(8)

        mode_layout.addWidget(QLabel("解析モード"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("高精度解析", "Precision DSP")
        self.mode_combo.addItem("AI併用解析", "AI Hybrid")
        self.mode_combo.addItem("高速解析", "Fast")
        mode_layout.addWidget(self.mode_combo, 0, 1)

        self.demucs_check = QCheckBox("Demucsでベースを分離")
        mode_layout.addWidget(self.demucs_check, 1, 0, 1, 2)

        self.engine_info = QLabel("")
        self.engine_info.setObjectName("mutedLabel")
        self.engine_info.setWordWrap(True)
        mode_layout.addWidget(self.engine_info, 2, 0, 1, 2)

        self.analyze_button = QPushButton("ルート音を解析")
        self.analyze_button.setObjectName("actionButton")
        self.analyze_button.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        stats = QGridLayout()
        stats.setSpacing(7)
        self.root_chip = QLabel("ルート --")
        self.root_chip.setObjectName("dataChip")
        self.key_chip = QLabel("キー --")
        self.key_chip.setObjectName("dataChip")
        self.tempo_chip = QLabel("BPM ---")
        self.tempo_chip.setObjectName("dataChip")
        self.confidence_chip = QLabel("確信度 --")
        self.confidence_chip.setObjectName("dataChip")
        stats.addWidget(self.root_chip, 0, 0)
        stats.addWidget(self.key_chip, 0, 1)
        stats.addWidget(self.tempo_chip, 1, 0)
        stats.addWidget(self.confidence_chip, 1, 1)

        edit_group = QGroupBox("ルート音を修正")
        edit_layout = QGridLayout(edit_group)

        self.note_combo = QComboBox()
        self.note_combo.addItem("休符", None)
        for midi in range(23, 61):
            self.note_combo.addItem(midi_to_note_name(midi), midi)

        self.apply_note_button = QPushButton("選択音を反映")
        self.apply_note_button.setEnabled(False)
        self.mark_rest_button = QPushButton("休符にする")
        self.mark_rest_button.setEnabled(False)

        edit_layout.addWidget(self.note_combo, 0, 0, 1, 2)
        edit_layout.addWidget(self.apply_note_button, 1, 0)
        edit_layout.addWidget(self.mark_rest_button, 1, 1)

        self.root_table = QTableWidget(0, 5)
        self.root_table.setHorizontalHeaderLabels(["拍", "時刻", "ルート", "確信度", "dB"])
        self.root_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.root_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.root_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.root_table.verticalHeader().setVisible(False)
        self.root_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.root_table.horizontalHeader().setStretchLastSection(True)

        export_layout = QGridLayout()
        self.pdf_button = QPushButton("PDF出力")
        self.csv_button = QPushButton("CSV出力")
        self.musicxml_button = QPushButton("MusicXML出力")
        self.save_session_button = QPushButton("解析を保存")
        for button in (
            self.pdf_button,
            self.csv_button,
            self.musicxml_button,
            self.save_session_button,
        ):
            button.setEnabled(False)
        export_layout.addWidget(self.pdf_button, 0, 0)
        export_layout.addWidget(self.csv_button, 0, 1)
        export_layout.addWidget(self.musicxml_button, 1, 0)
        export_layout.addWidget(self.save_session_button, 1, 1)

        layout.addWidget(title)
        layout.addLayout(mode_layout)
        layout.addWidget(self.analyze_button)
        layout.addWidget(self.progress_bar)
        layout.addLayout(stats)
        layout.addWidget(edit_group)
        layout.addWidget(self.root_table, 1)
        layout.addLayout(export_layout)
        return panel

    def _create_transport_panel(self) -> CyberPanel:
        panel = CyberPanel(accent="#00F6FF")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 13)
        layout.setSpacing(9)

        seek = QHBoxLayout()
        self.current_time_label = QLabel("00:00")
        self.current_time_label.setObjectName("timeLabel")
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setEnabled(False)
        self.duration_label = QLabel("00:00")
        self.duration_label.setObjectName("timeLabel")
        seek.addWidget(self.current_time_label)
        seek.addWidget(self.position_slider, 1)
        seek.addWidget(self.duration_label)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.play_button = QPushButton("▶ 再生")
        self.stop_button = QPushButton("■ 停止")
        self.back_button = QPushButton("« 5秒")
        self.forward_button = QPushButton("5秒 »")
        for button in (self.play_button, self.stop_button, self.back_button, self.forward_button):
            button.setEnabled(False)

        self.loop_a_button = QPushButton("A点設定")
        self.loop_b_button = QPushButton("B点設定")
        self.loop_check = QCheckBox("区間ループ")
        self.loop_check.setEnabled(False)

        volume_label = QLabel("音量")
        volume_label.setObjectName("controlLabel")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(82)
        self.volume_slider.setFixedWidth(130)
        self.volume_value = QLabel("082%")
        self.volume_value.setObjectName("controlValue")

        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.back_button)
        controls.addWidget(self.forward_button)
        controls.addSpacing(8)
        controls.addWidget(self.loop_a_button)
        controls.addWidget(self.loop_b_button)
        controls.addWidget(self.loop_check)

        self.detected_note_sound_check = QCheckBox("検出音をピアノで鳴らす")
        self.detected_note_sound_check.setChecked(False)
        self.detected_note_sound_check.setToolTip(
            "再生中、拍ごとの検出ルート音を短いピアノ音で通知します"
        )

        controls.addWidget(self.detected_note_sound_check)
        controls.addStretch(1)
        controls.addWidget(volume_label)
        controls.addWidget(self.volume_slider)
        controls.addWidget(self.volume_value)

        transform = QHBoxLayout()
        transform.setSpacing(8)
        transform.addWidget(QLabel("再生テンポ"))

        self.tempo_ratio = QDoubleSpinBox()
        self.tempo_ratio.setRange(0.50, 1.50)
        self.tempo_ratio.setSingleStep(0.05)
        self.tempo_ratio.setValue(1.00)
        self.tempo_ratio.setDecimals(2)
        self.tempo_ratio.setSuffix(" 倍")

        transform.addWidget(self.tempo_ratio)
        transform.addWidget(QLabel("キー変更"))

        self.key_shift = QSpinBox()
        self.key_shift.setRange(-12, 12)
        self.key_shift.setValue(0)
        self.key_shift.setSuffix(" 半音")

        self.render_button = QPushButton("練習音源を作成")
        self.render_button.setEnabled(False)
        self.reset_audio_button = QPushButton("原曲に戻す")
        self.reset_audio_button.setEnabled(False)

        transform.addWidget(self.key_shift)
        transform.addWidget(self.render_button)
        transform.addWidget(self.reset_audio_button)
        transform.addStretch(1)

        layout.addLayout(seek)
        layout.addLayout(controls)
        layout.addLayout(transform)
        return panel

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self._open_audio)
        self.load_session_button.clicked.connect(self._load_session)
        self.source_combo.currentTextChanged.connect(self._change_monitor_source)

        self.analyze_button.clicked.connect(self._start_analysis)

        self.play_button.clicked.connect(self._toggle_playback)
        self.stop_button.clicked.connect(self.player.stop)
        self.back_button.clicked.connect(lambda: self._seek_relative(-5000))
        self.forward_button.clicked.connect(lambda: self._seek_relative(5000))
        self.loop_a_button.clicked.connect(self._set_loop_a)
        self.loop_b_button.clicked.connect(self._set_loop_b)

        self.volume_slider.valueChanged.connect(self._set_volume)
        self.tempo_ratio.valueChanged.connect(self._set_playback_rate)
        self.position_slider.sliderMoved.connect(self._seek_to_position)

        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._player_error)

        self.timeline.note_selected.connect(self._select_root_from_user)
        self.timeline.seek_requested.connect(self._seek_to_position)

        self.root_table.itemSelectionChanged.connect(self._table_selection_changed)
        self.detected_note_sound_check.toggled.connect(
            self._detected_note_sound_toggled
        )
        self.apply_note_button.clicked.connect(self._apply_root_edit)
        self.mark_rest_button.clicked.connect(self._mark_root_rest)

        self.pdf_button.clicked.connect(self._export_pdf)
        self.csv_button.clicked.connect(self._export_csv)
        self.musicxml_button.clicked.connect(self._export_musicxml)
        self.save_session_button.clicked.connect(self._save_session)

        self.render_button.clicked.connect(self._start_transform)
        self.reset_audio_button.clicked.connect(self._reset_audio_source)

    def _open_audio(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "音源を選択",
            str(Path.home()),
            "音声ファイル (*.mp3 *.wav *.flac *.m4a *.aac *.ogg);;すべてのファイル (*.*)",
        )
        if not filename:
            return
        self._load_audio_path(Path(filename))

    def _load_audio_path(self, path: Path) -> None:
        self.source_path = path
        self.sources = {"原曲": path}
        self.analysis_result = None
        self.selected_root_index = None
        self._last_notified_root_index = None

        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("原曲")
        self.source_combo.blockSignals(False)

        self.player.stop()
        self.tempo_ratio.blockSignals(True)
        self.tempo_ratio.setValue(1.0)
        self.tempo_ratio.blockSignals(False)
        self.key_shift.setValue(0)
        self.player.setPlaybackRate(1.0)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

        self.file_label.setText(path.name.upper())
        self.file_label.setToolTip(str(path))
        self.timeline.set_result(None)
        self.root_table.setRowCount(0)

        for button in (
            self.play_button,
            self.stop_button,
            self.back_button,
            self.forward_button,
            self.loop_a_button,
            self.loop_b_button,
            self.render_button,
            self.reset_audio_button,
        ):
            button.setEnabled(True)
        self.loop_check.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.analyze_button.setEnabled(True)

        self._set_export_enabled(False)
        self.system_status.setText("● 音源読込済")
        self.analysis_state_label.setText("解析：実行可能")
        self.statusBar().showMessage(f"音源を読み込みました｜{path.name}")

    def _start_analysis(self) -> None:
        if self.source_path is None:
            return
        if self.analysis_worker and self.analysis_worker.isRunning():
            return

        mode = str(self.mode_combo.currentData())
        use_demucs = self.demucs_check.isChecked()

        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.analysis_state_label.setText("解析：実行中")

        self.analysis_worker = AnalysisWorker(
            str(self.source_path),
            mode,
            use_demucs,
        )
        self.analysis_worker.progress.connect(self._analysis_progress)
        self.analysis_worker.completed.connect(self._analysis_completed)
        self.analysis_worker.failed.connect(self._analysis_failed)
        self.analysis_worker.start()

    def _analysis_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        self.statusBar().showMessage(message)

    def _analysis_completed(self, result: AnalysisResult) -> None:
        self.analysis_result = result
        self.timeline.set_result(result)
        self._populate_root_table()
        self.key_chip.setText(f"キー {self._display_key_name(result.key_name)}")
        self.tempo_chip.setText(f"BPM {result.tempo:.1f}")
        self.root_chip.setText("ルート --")
        self.confidence_chip.setText("確信度 --")

        if result.bass_preview_path and Path(result.bass_preview_path).exists():
            self.sources["ベース強調"] = Path(result.bass_preview_path)
        if result.isolated_bass_path and Path(result.isolated_bass_path).exists():
            self.sources["分離ベース"] = Path(result.isolated_bass_path)
        self._refresh_source_combo()

        self._set_export_enabled(True)
        self._set_busy(False)
        self.analysis_state_label.setText(
            f"解析：{self._analysis_mode_label(result.mode)} 完了"
        )
        self.system_status.setText("● 解析完了")
        self.statusBar().showMessage(
            f"解析完了｜{len(result.roots)}拍｜{self._display_key_name(result.key_name)}｜{result.tempo:.1f} BPM"
        )

        if result.warnings:
            QMessageBox.warning(
                self,
                "解析は完了しました",
                "\n".join(result.warnings),
            )

    def _analysis_failed(self, details: str) -> None:
        self._set_busy(False)
        self.analysis_state_label.setText("解析：エラー")
        self.system_status.setText("● 解析エラー")
        self.progress_bar.setValue(0)
        QMessageBox.critical(
            self,
            "解析エラー",
            self._friendly_error(details),
        )

    def _populate_root_table(self) -> None:
        if self.analysis_result is None:
            self.root_table.setRowCount(0)
            return

        self.root_table.setRowCount(len(self.analysis_result.roots))
        for row, root in enumerate(self.analysis_result.roots):
            values = [
                str(root.beat_index),
                self._format_seconds(int(root.start * 1000)),
                self._display_note_name(root),
                f"{root.confidence * 100:.0f}%",
                f"{root.db:.1f}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if root.manually_edited:
                    item.setForeground(QColor("#EFFF75"))
                elif root.confidence < 0.42:
                    item.setForeground(QColor("#FF68DD"))
                self.root_table.setItem(row, column, item)

    def _select_root(self, index: int) -> None:
        if self.analysis_result is None or not 0 <= index < len(self.analysis_result.roots):
            return

        self.selected_root_index = index
        root = self.analysis_result.roots[index]
        self.timeline.set_selected_index(index)

        self.root_table.blockSignals(True)
        self.root_table.selectRow(index)
        self.root_table.scrollToItem(self.root_table.item(index, 0))
        self.root_table.blockSignals(False)

        combo_index = self.note_combo.findData(root.midi)
        if combo_index >= 0:
            self.note_combo.setCurrentIndex(combo_index)

        self.root_chip.setText(f"ルート {self._display_note_name(root)}")
        self.confidence_chip.setText(f"確信度 {root.confidence * 100:.0f}%")
        self.apply_note_button.setEnabled(True)
        self.mark_rest_button.setEnabled(True)

    def _select_root_from_user(self, index: int) -> None:
        self._select_root(index)
        self._play_detected_note(index, force=True)

    def _table_selection_changed(self) -> None:
        rows = self.root_table.selectionModel().selectedRows()
        if rows:
            index = rows[0].row()
            self._select_root(index)
            self._play_detected_note(index, force=True)

    def _apply_root_edit(self) -> None:
        if self.analysis_result is None or self.selected_root_index is None:
            return
        root = self.analysis_result.roots[self.selected_root_index]
        root.midi = self.note_combo.currentData()
        root.manually_edited = True
        root.confidence = 1.0
        root.source = "MANUAL"
        self._populate_root_table()
        self._select_root(self.selected_root_index)
        self.timeline.update()
        self.statusBar().showMessage(
            f"修正しました｜第{root.beat_index}拍 = {self._display_note_name(root)}"
        )

    def _mark_root_rest(self) -> None:
        index = self.note_combo.findData(None)
        self.note_combo.setCurrentIndex(index)
        self._apply_root_edit()

    def _change_monitor_source(self, label: str) -> None:
        path = self.sources.get(label)
        if path is None or not path.exists():
            return
        position = self.player.position()
        self._last_notified_root_index = None
        was_playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self._pending_restore_position = position
        QTimer.singleShot(250, self._restore_source_position)
        if was_playing:
            QTimer.singleShot(350, self.player.play)

    def _restore_source_position(self) -> None:
        self.player.setPosition(self._pending_restore_position)
        self.player.setPlaybackRate(float(self.tempo_ratio.value()))

    def _refresh_source_combo(self) -> None:
        current = self.source_combo.currentText()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItems(self.sources.keys())
        index = self.source_combo.findText(current)
        self.source_combo.setCurrentIndex(max(0, index))
        self.source_combo.blockSignals(False)

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek_to_position(self, position_ms: int) -> None:
        self._last_notified_root_index = None
        self.player.setPosition(position_ms)

    def _seek_relative(self, delta_ms: int) -> None:
        target = max(0, min(self.player.duration(), self.player.position() + delta_ms))
        self._seek_to_position(target)

    def _set_loop_a(self) -> None:
        self.loop_a_ms = self.player.position()
        if self.loop_b_ms and self.loop_b_ms <= self.loop_a_ms:
            self.loop_b_ms = 0
        self.statusBar().showMessage(f"ループ開始点 A｜{self._format_seconds(self.loop_a_ms)}")

    def _set_loop_b(self) -> None:
        self.loop_b_ms = self.player.position()
        if self.loop_b_ms <= self.loop_a_ms:
            self.loop_a_ms = 0
        self.statusBar().showMessage(f"ループ終了点 B｜{self._format_seconds(self.loop_b_ms)}")

    def _set_volume(self, value: int) -> None:
        self.audio_output.setVolume(value / 100)
        self.volume_value.setText(f"{value:03d}%")

    def _set_playback_rate(self, value: float) -> None:
        """Apply the tempo control immediately to the active player.

        The rendered practice WAV also uses this value, but live preview is
        handled by QMediaPlayer so changing the spin box is audible at once.
        """
        rate = max(0.50, min(1.50, float(value)))
        self.player.setPlaybackRate(rate)
        self.statusBar().showMessage(f"再生テンポ：{rate:.2f}倍")

    def _prepare_detected_note_sounds(self) -> None:
        """Create and preload short piano-like WAV notes for B0 through C4."""
        cache_dir = Path(tempfile.gettempdir()) / "BassCatcher" / "detected_notes"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for midi in range(23, 61):
            wav_path = cache_dir / f"piano_{midi}.wav"
            if not wav_path.exists():
                self._write_piano_note_wav(wav_path, midi)

            effect = QSoundEffect(self)
            effect.setLoopCount(1)
            effect.setVolume(0.34)
            effect.setSource(QUrl.fromLocalFile(str(wav_path)))
            self._detected_note_effects[midi] = effect

    @staticmethod
    def _write_piano_note_wav(path: Path, midi: int) -> None:
        sample_rate = 22050
        duration = 0.62
        frequency = 440.0 * (2.0 ** ((midi - 69) / 12.0))
        t = np.arange(int(sample_rate * duration), dtype=np.float64) / sample_rate

        attack = 1.0 - np.exp(-t / 0.0035)
        decay_time = 0.24 + min(0.20, 55.0 / max(frequency, 1.0) * 0.10)
        envelope = attack * np.exp(-t / decay_time)

        tone = (
            1.00 * np.sin(2.0 * np.pi * frequency * t)
            + 0.52 * np.sin(2.0 * np.pi * frequency * 2.0 * t + 0.04)
            + 0.28 * np.sin(2.0 * np.pi * frequency * 3.0 * t + 0.09)
            + 0.14 * np.sin(2.0 * np.pi * frequency * 4.0 * t + 0.15)
            + 0.07 * np.sin(2.0 * np.pi * frequency * 5.0 * t + 0.21)
            + 0.10 * np.sin(2.0 * np.pi * frequency * 1.003 * t)
        )

        rng = np.random.default_rng(midi)
        hammer = rng.normal(0.0, 1.0, len(t)) * np.exp(-t / 0.012) * 0.08
        samples = (tone * envelope) + hammer
        peak = float(np.max(np.abs(samples))) or 1.0
        pcm = np.int16(np.clip(samples / peak * 0.78, -1.0, 1.0) * 32767)

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())

    def _play_detected_note(self, index: int, *, force: bool = False) -> None:
        if not self.detected_note_sound_check.isChecked():
            return
        if self.analysis_result is None:
            return
        if not 0 <= index < len(self.analysis_result.roots):
            return
        if not force and index == self._last_notified_root_index:
            return

        root = self.analysis_result.roots[index]
        if root.midi is None:
            self._last_notified_root_index = index
            return

        effect = self._detected_note_effects.get(root.midi)
        if effect is None:
            return

        effect.stop()
        effect.play()
        self._last_notified_root_index = index

    def _detected_note_sound_toggled(self, enabled: bool) -> None:
        self._last_notified_root_index = None
        if not enabled:
            for effect in self._detected_note_effects.values():
                effect.stop()
            self.statusBar().showMessage("検出音のピアノ通知：OFF")
            return
        self.statusBar().showMessage("検出音のピアノ通知：ON")

    def _duration_changed(self, duration_ms: int) -> None:
        self.position_slider.setRange(0, max(0, duration_ms))
        self.duration_label.setText(self._format_seconds(duration_ms))
        self.duration_chip.setText(f"長さ {self._format_seconds(duration_ms)}")
        self.timeline.set_duration(duration_ms)

    def _position_changed(self, position_ms: int) -> None:
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position_ms)
        self.current_time_label.setText(self._format_seconds(position_ms))
        self.timeline.set_position(position_ms)

        if (
            self.loop_check.isChecked()
            and self.loop_b_ms > self.loop_a_ms
            and position_ms >= self.loop_b_ms
        ):
            self.player.setPosition(self.loop_a_ms)

        if self.analysis_result is not None:
            index = self._root_index_for_position(position_ms / 1000)
            if index is not None:
                if index != self.selected_root_index:
                    self._select_root(index)
                if self.player.playbackState() == QMediaPlayer.PlayingState:
                    self._play_detected_note(index)

    def _root_index_for_position(self, seconds: float) -> int | None:
        if self.analysis_result is None:
            return None
        for index, root in enumerate(self.analysis_result.roots):
            if root.start <= seconds < root.end:
                return index
        return None

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText("Ⅱ 一時停止")
            self.system_status.setText("● 再生中")
        elif state == QMediaPlayer.PausedState:
            self.play_button.setText("▶ 再生")
            self.system_status.setText("● 一時停止中")
        else:
            self.play_button.setText("▶ 再生")
            self._last_notified_root_index = None
            if self.source_path is not None:
                self.system_status.setText("● 音源読込済")

    def _player_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.NoError:
            return
        QMessageBox.critical(self, "再生エラー", error_string or "音源を再生できませんでした。")

    def _start_transform(self) -> None:
        if self.source_path is None:
            return
        if self.transform_worker and self.transform_worker.isRunning():
            return

        tempo = float(self.tempo_ratio.value())
        semitones = int(self.key_shift.value())
        self._pending_transform_tempo = tempo
        self._pending_transform_semitones = semitones

        output_dir = Path(tempfile.gettempdir()) / "BassCatcher" / "practice"
        output_dir.mkdir(parents=True, exist_ok=True)

        # A unique filename prevents QMediaPlayer from reusing a cached WAV
        # when the user renders the same song again with different settings.
        tempo_code = int(round(tempo * 100))
        key_code = f"p{semitones}" if semitones >= 0 else f"m{abs(semitones)}"
        unique_id = self._next_practice_render_id()
        target = output_dir / (
            f"{self.source_path.stem}_practice_t{tempo_code:03d}_k{key_code}_{unique_id}.wav"
        )

        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.transform_worker = TransformWorker(
            source_path=str(self.source_path),
            output_path=str(target),
            tempo_ratio=tempo,
            semitones=float(semitones),
        )
        self.transform_worker.progress.connect(self._analysis_progress)
        self.transform_worker.completed.connect(self._transform_completed)
        self.transform_worker.failed.connect(self._transform_failed)
        self.transform_worker.start()

    def _transform_completed(self, path: str) -> None:
        rendered_path = Path(path)
        self.sources["練習音源"] = rendered_path
        self._refresh_source_combo()

        # Tempo/key are already baked into the rendered WAV. Reset live
        # playback to 1.00x so the tempo is not applied a second time.
        self.tempo_ratio.blockSignals(True)
        self.tempo_ratio.setValue(1.0)
        self.tempo_ratio.blockSignals(False)
        self.key_shift.setValue(0)
        self.player.setPlaybackRate(1.0)

        # Force a reload even when "練習音源" was already selected.
        self.source_combo.blockSignals(True)
        index = self.source_combo.findText("練習音源")
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        self._change_monitor_source("練習音源")

        self._set_busy(False)
        self.statusBar().showMessage(
            "練習音源を作成しました"
            f"｜テンポ {self._pending_transform_tempo:.2f}倍"
            f"｜キー {self._pending_transform_semitones:+d}半音"
        )

    def _transform_failed(self, details: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "音源変換エラー", self._friendly_error(details))

    def _reset_audio_source(self) -> None:
        if "原曲" in self.sources:
            self.source_combo.setCurrentText("原曲")
        self.tempo_ratio.setValue(1.0)
        self.key_shift.setValue(0)
        self.player.setPlaybackRate(1.0)

    @staticmethod
    def _next_practice_render_id() -> str:
        from time import time_ns

        return str(time_ns())

    def _export_pdf(self) -> None:
        if self.analysis_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "ルート譜PDFを保存",
            str(Path.home() / f"{self.source_path.stem if self.source_path else 'bass'}_root_chart.pdf"),
            "PDF (*.pdf)",
        )
        if path:
            export_pdf(self.analysis_result, path)
            self.statusBar().showMessage(f"PDFを保存しました｜{path}")

    def _export_csv(self) -> None:
        if self.analysis_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVを保存",
            str(Path.home() / f"{self.source_path.stem if self.source_path else 'bass'}_roots.csv"),
            "CSV (*.csv)",
        )
        if path:
            export_csv(self.analysis_result, path)
            self.statusBar().showMessage(f"CSVを保存しました｜{path}")

    def _export_musicxml(self) -> None:
        if self.analysis_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "MusicXMLを保存",
            str(Path.home() / f"{self.source_path.stem if self.source_path else 'bass'}_roots.musicxml"),
            "MusicXML (*.musicxml)",
        )
        if path:
            export_musicxml(self.analysis_result, path)
            self.statusBar().showMessage(f"MusicXMLを保存しました｜{path}")

    def _save_session(self) -> None:
        if self.analysis_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "解析セッションを保存",
            str(Path.home() / f"{self.source_path.stem if self.source_path else 'bass'}.basscatcher.json"),
            "Bass Catcher解析ファイル (*.basscatcher.json);;JSON (*.json)",
        )
        if path:
            export_session(self.analysis_result, path)
            self.statusBar().showMessage(f"解析結果を保存しました｜{path}")

    def _load_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "解析セッションを開く",
            str(Path.home()),
            "Bass Catcher解析ファイル (*.basscatcher.json *.json)",
        )
        if not path:
            return

        try:
            result = load_session(path)
        except Exception as exc:
            QMessageBox.critical(self, "セッション読込エラー", str(exc))
            return

        source = Path(result.source_path)
        if not source.exists():
            QMessageBox.warning(
                self,
                "元音源が見つかりません",
                "解析結果は開けますが、元音源の再生はできません。",
            )
            self.analysis_result = result
            self.timeline.set_result(result)
            self._populate_root_table()
            self._set_export_enabled(True)
            return

        self._load_audio_path(source)
        self.analysis_result = result
        self.timeline.set_result(result)
        self._populate_root_table()
        self.key_chip.setText(f"キー {self._display_key_name(result.key_name)}")
        self.tempo_chip.setText(f"BPM {result.tempo:.1f}")
        self._set_export_enabled(True)
        if result.bass_preview_path and Path(result.bass_preview_path).exists():
            self.sources["ベース強調"] = Path(result.bass_preview_path)
        if result.isolated_bass_path and Path(result.isolated_bass_path).exists():
            self.sources["分離ベース"] = Path(result.isolated_bass_path)
        self._refresh_source_combo()
        self.analysis_state_label.setText("解析：保存データを読込済")

    def _set_export_enabled(self, enabled: bool) -> None:
        for button in (
            self.pdf_button,
            self.csv_button,
            self.musicxml_button,
            self.save_session_button,
        ):
            button.setEnabled(enabled)

    def _set_busy(self, busy: bool) -> None:
        self.analyze_button.setEnabled(not busy and self.source_path is not None)
        self.render_button.setEnabled(not busy and self.source_path is not None)
        self.import_button.setEnabled(not busy)
        self.load_session_button.setEnabled(not busy)
        self.mode_combo.setEnabled(not busy)
        self.demucs_check.setEnabled(not busy)
        if busy:
            self.system_status.setText("● 処理中")

    def _update_optional_engine_labels(self) -> None:
        basic = "利用可" if is_basic_pitch_available() else "未導入"
        demucs = "利用可" if is_demucs_available() else "未導入"
        self.engine_info.setText(f"Basic Pitch：{basic}\nDemucs：{demucs}")
        self.demucs_check.setEnabled(is_demucs_available())

    @staticmethod
    def _display_note_name(root: RootEvent) -> str:
        return "休符" if root.midi is None else root.note_name

    @staticmethod
    def _display_key_name(key_name: str) -> str:
        return "不明" if key_name == "Unknown" else key_name

    @staticmethod
    def _analysis_mode_label(mode: str) -> str:
        labels = {
            "Precision DSP": "高精度解析",
            "AI Hybrid": "AI併用解析",
            "Fast": "高速解析",
            "Loaded session": "保存データ",
        }
        return labels.get(mode, mode)

    @staticmethod
    def _divider() -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.VLine)
        frame.setObjectName("divider")
        frame.setFixedHeight(28)
        return frame

    @staticmethod
    def _format_seconds(milliseconds: int) -> str:
        seconds = max(0, milliseconds) // 1000
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _friendly_error(details: str) -> str:
        lines = [line for line in details.strip().splitlines() if line.strip()]
        if not lines:
            return "不明なエラーが発生しました。"
        return "\n".join(lines[-10:])

    @staticmethod
    def _add_neon_shadow(widget: QWidget, color: str, blur: int) -> None:
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(color))
        widget.setGraphicsEffect(shadow)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#root {
                background: #020409;
                color: #DDFBFF;
            }
            QWidget {
                font-family: "Yu Gothic UI", "Meiryo", sans-serif;
                font-size: 12px;
            }
            QLabel#appTitle {
                color: #D9FFFF;
                font-family: "Consolas", monospace;
                font-size: 27px;
                font-weight: 900;
                letter-spacing: 3px;
            }
            QLabel#appSubtitle {
                color: #5B7F8D;
                font-family: "Consolas", monospace;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#systemStatus {
                color: #00F6FF;
                border: 1px solid #155B66;
                border-radius: 5px;
                background: rgba(0, 246, 255, 16);
                padding: 8px 11px;
                font-family: "Consolas", monospace;
                font-weight: 800;
            }
            QLabel#sectionLabel {
                color: #A9F9FF;
                font-family: "Consolas", monospace;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 1px;
            }
            QLabel#fileLabel {
                color: #FF73E1;
                font-family: "Consolas", monospace;
                font-weight: 800;
            }
            QLabel#analysisState {
                color: #B34FAB;
                font-family: "Consolas", monospace;
                font-size: 9px;
                font-weight: 700;
            }
            QLabel#mutedLabel {
                color: #607583;
                font-family: "Consolas", monospace;
                font-size: 9px;
            }
            QLabel#dataChip {
                min-width: 84px;
                padding: 7px 8px;
                border: 1px solid #543052;
                border-radius: 4px;
                background: rgba(255, 43, 214, 13);
                color: #E27AD8;
                font-family: "Consolas", monospace;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#timeLabel, QLabel#controlValue {
                color: #C9FBFF;
                font-family: "Consolas", monospace;
                font-weight: 800;
            }
            QLabel#controlLabel {
                color: #6E8793;
                font-family: "Consolas", monospace;
                font-size: 10px;
                font-weight: 800;
            }
            QFrame#divider {
                color: #4B234A;
                background: #4B234A;
                max-width: 1px;
            }
            QPushButton {
                min-height: 34px;
                padding: 0 13px;
                border: 1px solid #234B57;
                border-radius: 5px;
                background: #08121A;
                color: #BFEFF4;
                font-family: "Consolas", monospace;
                font-weight: 800;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background: #0D2630;
                border-color: #00D7E2;
            }
            QPushButton:pressed {
                background: #05090E;
                border-color: #FF2BD6;
            }
            QPushButton:disabled {
                color: #3A4851;
                background: #06090D;
                border-color: #16222A;
            }
            QPushButton#primaryButton {
                min-height: 42px;
                color: #051014;
                background: #00F6FF;
                border-color: #BCFDFF;
            }
            QPushButton#primaryButton:hover {
                color: #0A040B;
                background: #FF55DC;
                border-color: #FFD0F5;
            }
            QPushButton#actionButton {
                min-height: 40px;
                color: #FFFFFF;
                background: rgba(255, 43, 214, 38);
                border-color: #AF2D9B;
            }
            QPushButton#actionButton:hover {
                background: #B91EA0;
                border-color: #FF8DE6;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                min-height: 32px;
                padding: 0 8px;
                border: 1px solid #244956;
                border-radius: 4px;
                background: #071018;
                color: #D8FBFF;
                selection-background-color: #71306E;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QCheckBox {
                color: #8CC4CB;
                font-family: "Consolas", monospace;
                font-size: 10px;
                font-weight: 700;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border: 1px solid #24606A;
                background: #050A0E;
            }
            QCheckBox::indicator:checked {
                background: #00DCE6;
                border-color: #A8FAFF;
            }
            QSlider::groove:horizontal {
                height: 5px;
                border-radius: 2px;
                background: #101D27;
                border: 1px solid #17313D;
            }
            QSlider::sub-page:horizontal {
                border-radius: 2px;
                background: #00DCE6;
            }
            QSlider::handle:horizontal {
                width: 15px;
                margin: -6px 0;
                border-radius: 7px;
                background: #FFFFFF;
                border: 2px solid #00F6FF;
            }
            QProgressBar {
                min-height: 18px;
                border: 1px solid #234A56;
                border-radius: 4px;
                background: #050A0F;
                color: #D6FFFF;
                text-align: center;
                font-family: "Consolas", monospace;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background: #00DDE8;
                border-radius: 3px;
            }
            QGroupBox {
                border: 1px solid #3D2640;
                border-radius: 6px;
                margin-top: 9px;
                padding-top: 9px;
                color: #D36AC9;
                font-family: "Consolas", monospace;
                font-weight: 800;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 9px;
                padding: 0 5px;
            }
            QTableWidget {
                background: #04080D;
                alternate-background-color: #08111A;
                color: #C8E9ED;
                gridline-color: #17303A;
                border: 1px solid #1E3D48;
                selection-background-color: #143F4B;
                selection-color: #FFFFFF;
                font-family: "Consolas", monospace;
                font-size: 10px;
            }
            QHeaderView::section {
                background: #0B1B24;
                color: #7EC9D0;
                border: none;
                border-right: 1px solid #1D3B45;
                padding: 5px;
                font-family: "Consolas", monospace;
                font-size: 9px;
                font-weight: 800;
            }
            QSplitter::handle {
                background: #07131A;
                width: 5px;
            }
            QStatusBar {
                color: #547582;
                background: #010207;
                border-top: 1px solid #122630;
                font-family: "Consolas", monospace;
                font-size: 10px;
            }
            QToolTip {
                color: #D9FFFF;
                background: #07131B;
                border: 1px solid #00C5CF;
                padding: 5px;
            }
            """
        )
