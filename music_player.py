import sys
import os
import datetime
import pygame
import numpy as np
import tempfile
from settings import Settings
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QAbstractItemView, QHeaderView, QSplitter, QDialog,
    QSizePolicy, QLineEdit, QListWidget, QListWidgetItem, QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QColor, QPainter, QPen, QKeyEvent, QPolygon
from mutagen.mp3 import MP3
from mutagen._util import MutagenError

NORMALIZE_RMS_TARGET = 9000.0
NORMALIZE_MAX_CLIP = 32767
WAVEFORM_RESOLUTION = 1000
LEVEL_WINDOW = 2205


class AudioPlayer(QThread):
    position_changed = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        pygame.mixer.init()
        pygame.mixer.pre_init(44100, -16, 2, 1024)
        self.current_file = None
        self.is_playing = False
        self.is_paused = False
        self._running = True
        self.duration = 0
        self.start_offset = 0
        self.fade_volume = 1.0
        self.fading = False
        self.fade_in_duration = 50
        self.fade_out_duration = 50
        self.target_volume = 1.0

    def fade_in(self, duration_ms=None):
        if self.fading:
            return
        duration_ms = duration_ms if duration_ms is not None else self.fade_in_duration
        self.fading = True
        self.fade_volume = 0.0
        steps = 10
        delay = max(1, duration_ms // steps)
        for i in range(steps + 1):
            self.fade_volume = i / steps
            pygame.mixer.music.set_volume(self.fade_volume * self.target_volume)
            QThread.msleep(delay)
        pygame.mixer.music.set_volume(self.target_volume)
        self.fading = False

    def fade_out(self, duration_ms=None):
        if self.fading:
            return
        duration_ms = duration_ms if duration_ms is not None else self.fade_out_duration
        self.fading = True
        steps = 10
        delay = max(1, duration_ms // steps)
        for i in range(steps, -1, -1):
            self.fade_volume = i / steps
            pygame.mixer.music.set_volume(self.fade_volume)
            QThread.msleep(delay)
        pygame.mixer.music.pause()
        pygame.mixer.music.set_volume(self.target_volume)
        self.fading = False
        self.is_paused = True

    def run(self):
        while self._running:
            if self.is_playing and not self.is_paused:
                pos = pygame.mixer.music.get_pos()
                if pos >= 0:
                    corrected = max(pos + self.start_offset, self.start_offset)
                    self.position_changed.emit(corrected)

                if (
                    not pygame.mixer.music.get_busy()
                    and self.is_playing
                    and not self.is_paused
                    and self.duration > 0
                ):
                    self.is_playing = False
                    self.finished.emit()
            self.msleep(5)

    def load(self, filepath):
        try:
            pygame.mixer.music.load(filepath)
            self.current_file = filepath
            try:
                audio = MP3(filepath)
                self.duration = int(audio.info.length * 1000)
            except Exception:
                self.duration = 0
            return True
        except Exception as e:
            print(f"Error loading file: {e}")
            return False

    def play(self):
        if self.current_file:
            self.start_offset = 0
            pygame.mixer.music.set_volume(0)
            pygame.mixer.music.play()
            self.is_playing = True
            self.is_paused = False
            self.fade_in()

    def pause(self):
        self.fade_out()
        self.is_paused = True

    def unpause(self):
        pygame.mixer.music.set_volume(0)
        pygame.mixer.music.unpause()
        self.is_paused = False
        self.fade_in()

    def stop(self):
        pygame.mixer.music.stop()
        self.is_playing = False

    def seek(self, position):
        self.start_offset = position
        pygame.mixer.music.stop()
        pygame.mixer.music.set_volume(0)
        pygame.mixer.music.play(1, position / 1000)
        self.is_playing = True
        self.is_paused = False
        self.fade_in()

    def get_duration(self):
        return self.duration

    def is_playing_state(self):
        return self.is_playing and not self.is_paused

    def stop_thread(self):
        self._running = False
        self.wait()


class SoundAnalyzer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.peak = 0.0
        self.clipped = False
        self.history = [0.0] * 32
        self.setMinimumWidth(70)
        self.setMinimumHeight(200)
        self.setStyleSheet("background-color: #3a3a3a;")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)

    def set_level(self, value, clipped=False):
        self.level = max(0.0, min(1.0, value))
        self.peak = max(self.peak, self.level)
        self.clipped = clipped
        self.history.append(self.level)
        self.history = self.history[-32:]

    def reset(self):
        self.level = 0.0
        self.peak = 0.0
        self.clipped = False
        self.history = [0.0] * 32

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        margin = 4
        bar_width = w - margin * 2
        bar_height = h - margin * 2 - 50
        bar_top = margin + 6

        painter.fillRect(
            int(margin - 1), int(bar_top - 1),
            int(bar_width + 2), int(bar_height + 2),
            QColor("#2a2a2a"),
        )

        segments = 20
        seg_height = bar_height / segments
        seg_gap = 2

        for i in range(segments):
            seg_y = int(bar_top + bar_height - (i + 1) * seg_height)
            seg_level = i / segments
            if seg_level <= self.level:
                if i < segments * 0.7:
                    color = QColor("#1db954")
                elif i < segments * 0.85:
                    color = QColor("#f0c000")
                else:
                    color = QColor("#e74c3c")
                painter.fillRect(
                    int(margin), seg_y,
                    int(bar_width), int(seg_height - seg_gap),
                    color,
                )
            else:
                painter.fillRect(
                    int(margin), seg_y,
                    int(bar_width), int(seg_height - seg_gap),
                    QColor("#454545"),
                )

        peak_y = int(bar_top + bar_height - self.peak * bar_height)
        painter.fillRect(int(margin), peak_y - 1, int(bar_width), 2, QColor("#ffffff"))

        clip_color = QColor("#4a9eff") if self.clipped else QColor("#454545")
        painter.fillRect(int(margin), int(margin), int(bar_width), 4, clip_color)

        history_y = int(bar_top + bar_height + 8)
        history_h = h - history_y - 2
        if history_h > 10 and len(self.history) > 1:
            step = bar_width / (len(self.history) - 1)
            pen = QPen(QColor("#1db954"))
            pen.setWidth(1)
            painter.setPen(pen)
            for i in range(1, len(self.history)):
                x1 = int(margin + (i - 1) * step)
                x2 = int(margin + i * step)
                y1 = int(history_y + history_h - self.history[i - 1] * history_h)
                y2 = int(history_y + history_h - self.history[i] * history_h)
                painter.drawLine(x1, y1, x2, y2)


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Music Player")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(900, 600)
        self.settings = Settings()
        self.playlist = []
        self.current_track_index = -1
        self.slider_pressed = False
        self._cached_audio = None
        self._cached_track = -1
        self.shuffle_enabled = False
        self._shuffle_history = []

        last_folder = ""
        if self.settings.restore_last_folder:
            last_folder = self.settings.last_folder

        self.audio_player = AudioPlayer()
        self.audio_player.position_changed.connect(self.update_position)
        self.audio_player.finished.connect(self.track_finished)
        self.audio_player.fade_in_duration = self.settings.fade_in_ms
        self.audio_player.fade_out_duration = self.settings.fade_out_ms
        self.audio_player.start()

        self.setup_ui()
        self.setup_menu()
        self.load_directory(
            last_folder if last_folder and os.path.isdir(last_folder)
            else os.path.expanduser("~")
        )

    # ─── UI Setup helpers ────────────────────────────────────────────────────

    def _setup_file_browser(self):
        browser_widget = QWidget()
        layout = QVBoxLayout(browser_widget)
        layout.setContentsMargins(10, 10, 5, 10)

        header_layout = QHBoxLayout()
        label = QLabel("File Browser")
        label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search songs...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3a3a3a;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #1db954;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        header_layout.addWidget(self.search_input)
        layout.addLayout(header_layout)

        self.search_stack = QStackedWidget()

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_stack.addWidget(self.file_tree)

        self.search_results = QListWidget()
        self.search_results.itemClicked.connect(self.on_search_item_clicked)
        self.search_results.itemDoubleClicked.connect(self.on_search_item_double_clicked)
        self.search_stack.addWidget(self.search_results)

        self.search_stack.setCurrentIndex(0)
        layout.addWidget(self.search_stack)

        add_btn = QPushButton("Add to Playlist")
        add_btn.clicked.connect(self.add_selected_to_playlist)
        layout.addWidget(add_btn)

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)

        self.splitter.addWidget(browser_widget)

    def _setup_playlist_panel(self):
        playlist_widget = QWidget()
        layout = QVBoxLayout(playlist_widget)
        layout.setContentsMargins(5, 10, 10, 10)

        header = QHBoxLayout()
        header.addWidget(QLabel("Playlist"))
        for label_text, handler in [
            ("Load Playlist", self.load_playlist),
            ("Save Playlist", self.save_playlist),
            ("Clear Playlist", self.clear_playlist),
        ]:
            btn = QPushButton(label_text)
            btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
            btn.clicked.connect(handler)
            header.addWidget(btn)
        header.addStretch()
        layout.addLayout(header)

        self.playlist_table = QTableWidget()
        self.playlist_table.setColumnCount(5)
        self.playlist_table.setHorizontalHeaderLabels(["Title", "Artist", "Year", "Date Created", "Duration"])
        self.playlist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.playlist_table.setShowGrid(True)
        self.playlist_table.verticalHeader().setVisible(False)
        self.playlist_table.horizontalHeader().setStretchLastSection(False)
        for i in range(5):
            self.playlist_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        self.playlist_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.playlist_table.cellDoubleClicked.connect(self.play_track_from_cell)
        layout.addWidget(self.playlist_table)

        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_from_playlist)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        for symbol, handler in [("↑", self.move_up), ("↓", self.move_down)]:
            btn = QPushButton(symbol)
            btn.setFixedWidth(40)
            btn.clicked.connect(handler)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        self.splitter.addWidget(playlist_widget)

    def _setup_analyzer_panel(self):
        analyzer_widget = QWidget()
        analyzer_widget.setMinimumWidth(80)
        analyzer_widget.setMaximumWidth(100)
        layout = QVBoxLayout(analyzer_widget)
        layout.setContentsMargins(3, 10, 3, 10)
        label = QLabel("Level")
        label.setStyleSheet("font-size: 12px; font-weight: bold; color: #ffffff;")
        layout.addWidget(label)
        self.sound_analyzer = SoundAnalyzer()
        layout.addWidget(self.sound_analyzer)
        self.splitter.addWidget(analyzer_widget)
        self.splitter.setSizes([300, 500, 90])

    def _setup_playbar(self):
        self.playbar = QWidget()
        self.playbar.setStyleSheet("background-color: #282828; padding: 10px;")
        layout = QVBoxLayout(self.playbar)
        layout.setContentsMargins(15, 5, 15, 5)

        self.play_btn = None
        controls = QHBoxLayout()
        for symbol, handler, size in [
            ("◀◀", self.previous_track, 40),
            ("▶", self.toggle_play_pause, 50),
            ("▶▶", self.next_track, 40),
            ("🔀", self.toggle_shuffle, 40),
        ]:
            btn = QPushButton(symbol)
            btn.setFixedSize(size, size)
            if symbol == "▶":
                btn.setStyleSheet("font-size: 20px; background-color: #1db954; border-radius: 25px;")
            btn.clicked.connect(handler)
            controls.addWidget(btn)
            if symbol == "▶":
                self.play_btn = btn
            if symbol == "🔀":
                self.shuffle_btn = btn
                self.shuffle_btn.setStyleSheet("font-size: 16px;")
        controls.addStretch()
        self.track_label = QLabel("No track selected")
        self.track_label.setStyleSheet("font-size: 13px; color: #e0e0e0;")
        self.track_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.track_label)
        controls.addStretch()
        layout.addLayout(controls)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(5, 0, 5, 0)
        self.current_time_label = QLabel("0:00")
        self.current_time_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.current_time_label.setFixedWidth(45)
        time_row.addWidget(self.current_time_label)
        self.waveform_slider = WaveformSlider()
        self.waveform_slider.setMinimumHeight(70)
        self.waveform_slider.sliderPressed.connect(self.on_slider_pressed)
        self.waveform_slider.sliderReleased.connect(self.on_slider_released)
        self.waveform_slider.positionChanged.connect(self.on_slider_changed)
        time_row.addWidget(self.waveform_slider, 1)
        self.total_time_label = QLabel("0:00")
        self.total_time_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.total_time_label.setFixedWidth(45)
        time_row.addWidget(self.total_time_label)
        layout.addLayout(time_row)

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self._setup_file_browser()
        self._setup_playlist_panel()
        self._setup_analyzer_panel()
        self._setup_playbar()
        self.main_layout.addWidget(self.splitter)
        self.main_layout.addWidget(self.playbar)
        self.setStyleSheet("""
            QMainWindow { background-color: #333333; }
            QWidget { color: #cccccc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
            QTreeWidget { background-color: #3a3a3a; border: none; color: #a0a0a0; padding: 10px; }
            QTreeWidget::item { padding: 5px; }
            QTreeWidget::item:selected { background-color: #555555; color: #ffffff; }
            QTreeWidget::item:alternate { background-color: #454545; }
            QTreeWidget QScrollBar:vertical { background: #3a3a3a; }
            QTreeWidget QScrollBar::handle:vertical { background: #1db954; border-radius: 4px; min-height: 30px; }
            QTreeWidget QScrollBar::add-line:vertical, QTreeWidget QScrollBar::sub-line:vertical { height: 0px; }
            QListWidget { background-color: #3a3a3a; border: none; color: #a0a0a0; padding: 10px; }
            QListWidget::item { padding: 5px; color: #a0a0a0; }
            QListWidget::item:hover { background-color: #454545; }
            QTableWidget { background-color: #3a3a3a; border: none; color: #a0a0a0; gridline-color: #505050; }
            QTableWidget::item { padding: 8px; border-right: 1px solid #505050; background-color: #3a3a3a; }
            QTableWidget::item:alternate { background-color: #454545; }
            QTableWidget::item:selected { background-color: #555555; color: #ffffff; }
            QTableWidget QScrollBar:vertical { background: #3a3a3a; }
            QTableWidget QScrollBar::handle:vertical { background: #1db954; border-radius: 4px; min-height: 30px; }
            QTableWidget QScrollBar::add-line:vertical, QTableWidget QScrollBar::sub-line:vertical { height: 0px; }
            QHeaderView::section { background-color: #454545; color: #a0a0a0; padding: 8px; border: none; border-right: 1px solid #505050; }
            QPushButton { background-color: #505050; color: #cccccc; border: none; padding: 8px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #606060; }
            QPushButton:pressed { background-color: #707070; }
            QLabel { color: #cccccc; }
            QSlider::groove:horizontal { background: #505050; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #1db954; width: 14px; margin: -4px 0; border-radius: 7px; }
            QSlider::sub-page:horizontal { background: #1db954; border-radius: 3px; }
            QMenuBar { background-color: #454545; color: #ffffff; }
            QMenuBar::item:selected { background-color: #555555; color: #ffffff; }
            QMenu { background-color: #3a3a3a; color: #ffffff; }
            QMenu::item:selected { background-color: #555555; color: #ffffff; }
            QSplitter::handle { background-color: #555555; width: 3px; }
        """)

    def setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        open_folder_action = QAction("Open Folder", self)
        open_folder_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_folder_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        playlist_menu = menubar.addMenu("Playlist")
        for label_text, handler in [
            ("Load Playlist", self.load_playlist),
            ("Save Playlist", self.save_playlist),
            ("Clear Playlist", self.clear_playlist),
        ]:
            action = QAction(label_text, self)
            action.triggered.connect(handler)
            playlist_menu.addAction(action)

        settings_menu = menubar.addMenu("Settings")
        settings_action = QAction("Preferences", self)
        settings_action.triggered.connect(self.show_settings)
        settings_menu.addAction(settings_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ─── Settings dialog ──────────────────────────────────────────────────────

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setMinimumWidth(350)
        layout = QVBoxLayout()

        def section_header(text):
            label = QLabel(text)
            label.setStyleSheet("font-weight: bold; font-size: 14px;")
            layout.addWidget(label)

        def cycle_button(label_text, values, getter, setter):
            btn = QPushButton(f"{label_text}: {getter()} ms")
            btn.setMinimumHeight(40)
            def callback():
                current = getter()
                idx = values.index(current) if current in values else 0
                next_val = values[(idx + 1) % len(values)]
                setter(next_val)
                btn.setText(f"{label_text}: {next_val} ms")
            btn.clicked.connect(callback)
            layout.addWidget(btn)

        def toggle_button(label_text, getter, setter):
            btn = QPushButton(f"{label_text}: {'ON' if getter() else 'OFF'}")
            btn.setMinimumHeight(40)
            def callback():
                new_val = not getter()
                setter(new_val)
                btn.setText(f"{label_text}: {'ON' if new_val else 'OFF'}")
            btn.clicked.connect(callback)
            layout.addWidget(btn)

        section_header("Fade Settings")
        cycle_button(
            "Fade In", [25, 50, 75, 100, 150, 200],
            lambda: self.settings.fade_in_ms,
            lambda v: setattr(self.audio_player, 'fade_in_duration', v) or setattr(self.settings, 'fade_in_ms', v),
        )
        cycle_button(
            "Fade Out", [25, 50, 75, 100, 150, 200],
            lambda: self.settings.fade_out_ms,
            lambda v: setattr(self.audio_player, 'fade_out_duration', v) or setattr(self.settings, 'fade_out_ms', v),
        )

        layout.addSpacing(20)
        section_header("Folder Settings")
        toggle_button(
            "Restore Last Folder",
            lambda: self.settings.restore_last_folder,
            lambda v: setattr(self.settings, 'restore_last_folder', v),
        )

        layout.addSpacing(20)
        section_header("Volume Settings")
        toggle_button(
            "Normalize Volume",
            lambda: self.settings.normalize_volume,
            lambda v: setattr(self.settings, 'normalize_volume', v),
        )
        toggle_button(
            "Limiter (0dB)",
            lambda: self.settings.limiter,
            lambda v: setattr(self.settings, 'limiter', v),
        )

        layout.addSpacing(20)
        section_header("Display Settings")
        toggle_button(
            "Show Waveform",
            lambda: self.settings.show_waveform,
            lambda v: setattr(self.settings, 'show_waveform', v),
        )

        layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.setMinimumHeight(40)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        dialog.setLayout(layout)
        dialog.exec()

    # ─── File browser ─────────────────────────────────────────────────────────

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.settings.last_folder = folder
            self.load_directory(folder)

    def load_directory(self, path):
        self.current_directory = path
        self.file_tree.clear()
        self.populate_tree(None, path, lazy=False)

    def populate_tree(self, parent, path, lazy=True):
        try:
            for item in sorted(os.listdir(path)):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    tree_item = QTreeWidgetItem([item])
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, item_path)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole + 1, "folder")
                    if lazy:
                        dummy = QTreeWidgetItem(["..."])
                        dummy.setData(0, Qt.ItemDataRole.UserRole, "")
                        tree_item.addChild(dummy)
                    else:
                        self.populate_tree(tree_item, item_path, lazy=False)
                    if parent:
                        parent.addChild(tree_item)
                    else:
                        self.file_tree.addTopLevelItem(tree_item)
                elif item.lower().endswith(('.mp3', '.wav')):
                    tree_item = QTreeWidgetItem([item])
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, item_path)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole + 1, "file")
                    if parent:
                        parent.addChild(tree_item)
                    else:
                        self.file_tree.addTopLevelItem(tree_item)
        except PermissionError:
            pass

    def on_item_double_clicked(self, item, column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if item_type == "folder":
            if item.childCount() == 1 and item.child(0).data(0, Qt.ItemDataRole.UserRole) == "":
                item.takeChildren()
                self.populate_tree(item, path, lazy=False)
            item.setExpanded(not item.isExpanded())
        elif item_type == "file":
            self.add_to_playlist(path)

    # ─── Slider / waveform ────────────────────────────────────────────────────

    def on_slider_pressed(self):
        self.slider_pressed = True
        self.slider_was_playing = self.audio_player.is_playing_state()
        if self.slider_was_playing:
            self.audio_player.pause()

    def on_slider_released(self):
        duration = self.audio_player.get_duration()
        if duration > 0:
            position = int(self.waveform_slider.progress * duration / 1000)
            self.audio_player.seek(position)
            self.current_time_label.setText(self.format_time(int(position / 1000)))
        if self.slider_was_playing:
            self.audio_player.unpause()
            self.play_btn.setText("⏸")
        self.slider_pressed = False

    def on_slider_changed(self, value):
        if self.slider_pressed:
            duration = self.audio_player.get_duration()
            if duration > 0:
                pos_ms = int(value * duration / 1000)
                self.current_time_label.setText(self.format_time(int(pos_ms / 1000)))

    def load_waveform(self, filepath):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            samples = np.array(audio.get_array_of_samples())
            bits = audio.sample_width * 8
            max_val = float(2 ** (bits - 1))
            if audio.channels == 2:
                frames = samples.reshape((-1, 2)).astype(np.float32)
                left = np.abs(frames[:, 0]) / max_val
                right = np.abs(frames[:, 1]) / max_val
                data = np.vstack([left, right])
            else:
                mono = samples.astype(np.float32)
                data = np.abs(mono) / max_val

            # Average samples into WAVEFORM_RESOLUTION buckets
            if data.ndim == 2:
                total = data.shape[1]
                if total > WAVEFORM_RESOLUTION:
                    bucket_size = total // WAVEFORM_RESOLUTION
                    trimmed = bucket_size * WAVEFORM_RESOLUTION
                    data = data[:, :trimmed].reshape(2, WAVEFORM_RESOLUTION, bucket_size).mean(axis=2)
            else:
                total = len(data)
                if total > WAVEFORM_RESOLUTION:
                    bucket_size = total // WAVEFORM_RESOLUTION
                    trimmed = bucket_size * WAVEFORM_RESOLUTION
                    data = data[:trimmed].reshape(WAVEFORM_RESOLUTION, bucket_size).mean(axis=1)

            print("Waveform geladen:", data.shape if data is not None else None)
            return data
        except Exception as e:
            print("Waveform error:", e)
            return None

    # ─── Playlist management ──────────────────────────────────────────────────

    def add_to_playlist(self, filepath):
        title = os.path.splitext(os.path.basename(filepath))[0]
        artist = "Unknown Artist"
        year = ""
        duration_sec = 0
        duration = "0:00"
        try:
            audio = MP3(filepath)
            if audio.tags:
                if 'TIT2' in audio.tags:
                    title = audio.tags['TIT2'].text[0] if audio.tags['TIT2'].text else title
                if 'TPE1' in audio.tags:
                    artist = audio.tags['TPE1'].text[0] if audio.tags['TPE1'].text else artist
                if 'TDRC' in audio.tags:
                    year = str(audio.tags['TDRC'].text[0]) if audio.tags['TDRC'].text else ""
                elif 'TYER' in audio.tags:
                    year = str(audio.tags['TYER'].text[0]) if audio.tags['TYER'].text else ""
            duration_sec = int(audio.info.length)
            duration = self.format_time(duration_sec)
        except (MutagenError, AttributeError):
            pass
        ctime = os.path.getctime(filepath)
        date = datetime.datetime.fromtimestamp(ctime).strftime("%d.%m.%Y")
        self.playlist.append({
            'filepath': filepath,
            'title': title,
            'artist': artist,
            'year': year,
            'date': date,
            'duration': duration,
            'duration_sec': duration_sec,
            'ctime': ctime,
        })
        self.update_playlist_table()

    def add_selected_to_playlist(self):
        if hasattr(self, 'search_input') and self.search_input.text().strip():
            for i in range(self.search_results.count()):
                item = self.search_results.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    filepath = item.data(Qt.ItemDataRole.UserRole)
                    if filepath:
                        self.add_to_playlist(filepath)
            return
        for item in self.file_tree.selectedItems():
            path = item.data(0, Qt.ItemDataRole.UserRole)
            item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if item_type == "folder":
                self.add_folder_to_playlist(path)
            elif item_type == "file":
                self.add_to_playlist(path)

    def add_folder_to_playlist(self, folder_path):
        for root, _, files in os.walk(folder_path):
            for file in sorted(files):
                if file.lower().endswith(('.mp3', '.wav')):
                    self.add_to_playlist(os.path.join(root, file))

    def on_search_text_changed(self, text):
        query = text.strip()
        if query:
            self.search_timer.stop()
            self.search_timer.start(200)
        else:
            self.search_timer.stop()
            self.search_results.clear()
            self.search_stack.setCurrentIndex(0)

    def perform_search(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self.search_results.clear()
            self.search_stack.setCurrentIndex(0)
            return
        self.search_results.clear()
        results = []
        root = getattr(self, 'current_directory', None) or os.path.expanduser("~")
        try:
            for dirpath, _, filenames in os.walk(root):
                for f in filenames:
                    if f.lower().endswith(('.mp3', '.wav')) and query in f.lower():
                        results.append(os.path.join(dirpath, f))
        except PermissionError:
            pass
        results.sort(key=lambda x: os.path.basename(x).lower())
        for filepath in results:
            name = os.path.basename(filepath)
            item = QListWidgetItem(name)
            item.setToolTip(filepath)
            item.setData(Qt.ItemDataRole.UserRole, filepath)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.search_results.addItem(item)
        if not results:
            no_match = QListWidgetItem("No songs found")
            no_match.setFlags(no_match.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            no_match.setForeground(QColor("#888888"))
            self.search_results.addItem(no_match)
        self.search_stack.setCurrentIndex(1)

    def on_search_item_clicked(self, item):
        current = item.checkState()
        item.setCheckState(Qt.CheckState.Unchecked if current == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def on_search_item_double_clicked(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole)
        if filepath:
            self.add_to_playlist(filepath)

    def remove_from_playlist(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()), reverse=True)
        for row in rows:
            if 0 <= row < len(self.playlist):
                self.playlist.pop(row)
        self.update_playlist_table()
        if self.current_track_index >= len(self.playlist):
            self.current_track_index = max(len(self.playlist) - 1, -1)

    def update_playlist_table(self):
        self.playlist_table.setRowCount(len(self.playlist))
        for i, track in enumerate(self.playlist):
            self.playlist_table.setItem(i, 0, QTableWidgetItem(track['title']))
            self.playlist_table.setItem(i, 1, QTableWidgetItem(track['artist']))
            self.playlist_table.setItem(i, 2, QTableWidgetItem(str(track.get('year', ''))))
            self.playlist_table.setItem(i, 3, QTableWidgetItem(str(track.get('date', ''))))
            self.playlist_table.setItem(i, 4, QTableWidgetItem(track['duration']))

    def sort_playlist(self, column, reverse=False):
        keys = ['title', 'artist', 'year', 'ctime', 'duration_sec']
        if 0 <= column < len(keys):
            self.playlist.sort(
                key=lambda x: str(x.get(keys[column], "" if column != 4 else 0)).lower(),
                reverse=reverse,
            )
        self.update_playlist_table()

    def on_header_clicked(self, column):
        if hasattr(self, 'last_sort_column') and self.last_sort_column == column:
            reverse = not self.last_sort_reverse
        else:
            reverse = False
        self.last_sort_column = column
        self.last_sort_reverse = reverse
        self.sort_playlist(column, reverse)

    def move_up(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()))
        if not rows:
            return
        playing_row = self.current_track_index
        new_rows = []
        for row in rows:
            if row > 0:
                self.playlist[row], self.playlist[row - 1] = self.playlist[row - 1], self.playlist[row]
                new_rows.append(row - 1)
                if row == playing_row:
                    playing_row = row - 1
            else:
                new_rows.append(row)
        self.current_track_index = playing_row
        self.update_playlist_table()
        for row in new_rows:
            self.playlist_table.selectRow(row)

    def move_down(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()), reverse=True)
        if not rows:
            return
        playing_row = self.current_track_index
        new_rows = []
        for row in rows:
            if row < len(self.playlist) - 1:
                self.playlist[row], self.playlist[row + 1] = self.playlist[row + 1], self.playlist[row]
                new_rows.append(row + 1)
                if row == playing_row:
                    playing_row = row + 1
            else:
                new_rows.append(row)
        self.current_track_index = playing_row
        self.update_playlist_table()
        for row in new_rows:
            self.playlist_table.selectRow(row)

    # ─── Playback ─────────────────────────────────────────────────────────────

    def play_track_from_cell(self, row, column):
        self.play_track(row)

    def play_track(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        self.current_track_index = index
        track = self.playlist[index]
        self.audio_player.stop()
        QThread.msleep(50)

        filepath = track['filepath']
        original_duration = track['duration_sec'] * 1000

        # Step 1: Normalize? → creates temp WAV
        # Step 2: Limiter? → applied inside normalize process (if normalize ON)
        #         OR if normalize OFF but limiter ON → still creates temp WAV for limiter
        if self.settings.normalize_volume:
            filepath = self._normalize_audio(filepath)
        elif self.settings.limiter:
            # No normalize, but limiter needs processing → create temp with limiter only
            filepath = self._apply_limiter(filepath)

        self.audio_player.target_volume = 1.0
        if self.audio_player.load(filepath):
            self.audio_player.duration = original_duration
            self.audio_player.play()
            self.track_label.setText(f"{track['title']} - {track['artist']}")
            self.play_btn.setText("⏸")
            self.playlist_table.selectRow(index)
            if self.settings.show_waveform:
                self.waveform_slider.set_waveform(self.load_waveform(filepath))
            else:
                self.waveform_slider.set_waveform(None)

    def _normalize_audio(self, filepath):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            samples = np.array(audio.get_array_of_samples()).astype(np.float32)
            
            if audio.channels == 2:
                frames = samples.reshape((-1, 2))
                
                # Normalize to target RMS
                rms = np.sqrt(np.mean(frames ** 2))
                if rms > 0:
                    frames = frames * (NORMALIZE_RMS_TARGET / rms)
                
                # Apply limiter if enabled (clip to 0dB)
                if self.settings.limiter:
                    frames = np.clip(frames, -32767, 32767)
                else:
                    frames = np.clip(frames, -32768, 32767)
                
                interleaved = frames.astype(np.int16).reshape(-1)
                normalized = AudioSegment(
                    interleaved.tobytes(),
                    frame_rate=audio.frame_rate,
                    sample_width=2,
                    channels=2,
                )
            else:
                # Mono
                rms = np.sqrt(np.mean(samples ** 2))
                if rms > 0:
                    samples = samples * (NORMALIZE_RMS_TARGET / rms)
                
                if self.settings.limiter:
                    samples = np.clip(samples, -32767, 32767)
                else:
                    samples = np.clip(samples, -32768, 32767)
                
                normalized = AudioSegment(
                    samples.astype(np.int16).tobytes(),
                    frame_rate=audio.frame_rate,
                    sample_width=2,
                    channels=1,
                )
            
            temp_path = os.path.join(tempfile.gettempdir(), "normalized_track.wav")
            normalized.export(temp_path, format="wav")
            return temp_path
        except Exception as e:
            print("Audio processing error:", e)
            return filepath

    def _apply_limiter(self, filepath):
        """Apply limiter only (no normalization), creating a temp WAV."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            samples = np.array(audio.get_array_of_samples()).astype(np.float32)
            
            if audio.channels == 2:
                frames = samples.reshape((-1, 2))
                frames = np.clip(frames, -32767, 32767)
                interleaved = frames.astype(np.int16).reshape(-1)
                processed = AudioSegment(
                    interleaved.tobytes(),
                    frame_rate=audio.frame_rate,
                    sample_width=2,
                    channels=2,
                )
            else:
                samples = np.clip(samples, -32767, 32767)
                processed = AudioSegment(
                    samples.astype(np.int16).tobytes(),
                    frame_rate=audio.frame_rate,
                    sample_width=2,
                    channels=1,
                )
            
            temp_path = os.path.join(tempfile.gettempdir(), "limited_track.wav")
            processed.export(temp_path, format="wav")
            return temp_path
        except Exception as e:
            print("Limiter error:", e)
            return filepath

    def toggle_play_pause(self):
        if not self.playlist:
            return
        if self.current_track_index == -1:
            selected = self.playlist_table.currentRow()
            self.play_track(selected if selected >= 0 else 0)
            return
        if self.audio_player.is_playing_state():
            self.audio_player.pause()
            self.play_btn.setText("▶")
        elif self.audio_player.is_paused:
            self.audio_player.unpause()
            self.play_btn.setText("⏸")

    def previous_track(self):
        if self.current_track_index > 0:
            self.play_track(self.current_track_index - 1)

    def next_track(self):
        if self.shuffle_enabled and self.playlist:
            available = [i for i in range(len(self.playlist)) if i not in self._shuffle_history]
            if not available:
                self._shuffle_history = []
                available = list(range(len(self.playlist)))
            next_idx = available[np.random.randint(0, len(available))]
            self._shuffle_history.append(self.current_track_index)
            if len(self._shuffle_history) > 5:
                self._shuffle_history.pop(0)
            self.play_track(next_idx)
        elif self.current_track_index < len(self.playlist) - 1:
            self.play_track(self.current_track_index + 1)
        elif self.playlist:
            self.play_track(0)

    def toggle_shuffle(self):
        self.shuffle_enabled = not self.shuffle_enabled
        self._shuffle_history = []
        if self.shuffle_enabled:
            self.shuffle_btn.setStyleSheet("font-size: 16px; background-color: #1db954; border-radius: 5px;")
        else:
            self.shuffle_btn.setStyleSheet("font-size: 16px;")

    def update_position(self, pos):
        if self.slider_pressed:
            return
        duration = self.audio_player.get_duration()
        if duration <= 0:
            return
        value = int(pos * 1000 / duration)
        self.waveform_slider.set_progress(value)
        self.current_time_label.setText(self.format_time(int(pos / 1000)))
        self.total_time_label.setText(self.format_time(int(duration / 1000)))

        if self.audio_player.is_playing_state() and self.current_track_index >= 0:
            try:
                from pydub import AudioSegment
                if self._cached_track != self.current_track_index:
                    filepath = self.playlist[self.current_track_index]['filepath']
                    audio = AudioSegment.from_file(filepath)
                    self._cached_audio = audio
                    raw = np.array(audio.get_array_of_samples()).astype(np.float32)
                    if audio.channels == 2:
                        raw = raw.reshape((-1, 2)).mean(axis=1)
                    self._cached_samples = raw
                    self._cached_track = self.current_track_index

                total = len(self._cached_samples)
                if total > 0 and duration > 0:
                    idx = int((pos / duration) * total)
                    start = max(0, idx - LEVEL_WINDOW // 2)
                    end = min(total, idx + LEVEL_WINDOW // 2)
                    chunk = self._cached_samples[start:end]
                    if len(chunk) > 0:
                        level = np.sqrt(np.mean(chunk ** 2)) / 32767.0
                        self.sound_analyzer.set_level(min(1.0, level * 3), level > 1.0)
            except Exception:
                pass

    def track_finished(self):
        if self.shuffle_enabled and self.playlist:
            available = [i for i in range(len(self.playlist)) if i not in self._shuffle_history]
            if not available:
                self._shuffle_history = []
                available = list(range(len(self.playlist)))
            next_idx = available[np.random.randint(0, len(available))]
            self._shuffle_history.append(self.current_track_index)
            if len(self._shuffle_history) > 5:
                self._shuffle_history.pop(0)
            self.play_track(next_idx)
        elif self.current_track_index < len(self.playlist) - 1:
            self.next_track()
        else:
            self.play_btn.setText("▶")

    # ─── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def format_time(seconds):
        return f"{seconds // 60}:{seconds % 60:02d}"

    def save_playlist(self):
        if not self.playlist:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save Playlist", "", "JSON Playlist (*.json)")
        if filename:
            if not filename.endswith('.json'):
                filename += '.json'
            import json
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.playlist, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Success", "Playlist saved successfully!")

    def load_playlist(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Playlist", "", "JSON Playlist (*.json)")
        if filename:
            import json
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.playlist.clear()
            for track in data:
                if os.path.exists(track['filepath']):
                    self.playlist.append(track)
            self.update_playlist_table()
            QMessageBox.information(self, "Success", "Playlist loaded successfully!")

    def clear_playlist(self):
        self.playlist.clear()
        self.current_track_index = -1
        self.audio_player.stop()
        self.update_playlist_table()
        self.track_label.setText("No track selected")
        self.play_btn.setText("▶")

    def show_about(self):
        QMessageBox.about(self, "About", "Simple Music Player\n\nA lightweight MP3/WAV player built with PyQt6.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_proportional_widths()

    def apply_proportional_widths(self):
        w = self.playlist_table.width()
        col_widths = [int(w * x) for x in [0.30, 0.30, 0.125, 0.125]]
        col_widths.append(w - sum(col_widths))
        for i, cw in enumerate(col_widths):
            self.playlist_table.setColumnWidth(i, cw)

    def closeEvent(self, event):
        self.audio_player.stop_thread()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play_pause()
        elif event.key() == Qt.Key.Key_Left:
            self.previous_track()
        elif event.key() == Qt.Key.Key_Right:
            self.next_track()
        else:
            super().keyPressEvent(event)


class WaveformSlider(QWidget):
    positionChanged = pyqtSignal(int)
    sliderPressed = pyqtSignal()
    sliderReleased = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data = None
        self.progress = 0
        self.dragging = False
        self.setMinimumHeight(70)

    def set_waveform(self, data):
        self.waveform_data = data
        self.update()

    def set_progress(self, value):
        self.progress = value
        self.update()

    def mousePressEvent(self, event):
        self.dragging = True
        self.sliderPressed.emit()
        self.update_pos(event.position().x())

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.update_pos(event.position().x())

    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.sliderReleased.emit()

    def update_pos(self, x):
        ratio = max(0, min(1, x / self.width()))
        self.progress = int(ratio * 1000)
        self.positionChanged.emit(self.progress)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        center = h // 2

        if self.waveform_data is not None:
            data = self.waveform_data
            if isinstance(data, np.ndarray) and data.ndim == 2:
                left, right = data[0], data[1]
                n = min(len(left), len(right))
                if n > 0:
                    step = w / (n - 1) if n > 1 else w
                    # Left channel (green, symmetric around center)
                    painter.setPen(QPen(QColor(29, 185, 84, 180), 1))
                    for i in range(n - 1):
                        x1 = int(i * step)
                        x2 = int((i + 1) * step)
                        y1_up = center - int(left[i] * center * 0.9)
                        y2_up = center - int(left[i + 1] * center * 0.9)
                        y1_down = center + int(left[i] * center * 0.9)
                        y2_down = center + int(left[i + 1] * center * 0.9)
                        painter.drawLine(x1, y1_up, x2, y2_up)
                        painter.drawLine(x1, y1_down, x2, y2_down)
                    # Right channel (blue, symmetric around center, layered on top)
                    painter.setPen(QPen(QColor(59, 130, 246, 180), 1))
                    for i in range(n - 1):
                        x1 = int(i * step)
                        x2 = int((i + 1) * step)
                        y1_up = center - int(right[i] * center * 0.9)
                        y2_up = center - int(right[i + 1] * center * 0.9)
                        y1_down = center + int(right[i] * center * 0.9)
                        y2_down = center + int(right[i + 1] * center * 0.9)
                        painter.drawLine(x1, y1_up, x2, y2_up)
                        painter.drawLine(x1, y1_down, x2, y2_down)
            elif isinstance(data, (list, tuple)):
                mono = np.array(data, dtype=float)
                n = len(mono)
                if n > 0:
                    step = w / (n - 1) if n > 1 else w
                    painter.setPen(QPen(QColor("#1db954"), 1))
                    for i in range(n - 1):
                        x1 = int(i * step)
                        x2 = int((i + 1) * step)
                        y1_up = center - int(mono[i] * center * 0.9)
                        y2_up = center - int(mono[i + 1] * center * 0.9)
                        y1_down = center + int(mono[i] * center * 0.9)
                        y2_down = center + int(mono[i + 1] * center * 0.9)
                        painter.drawLine(x1, y1_up, x2, y2_up)
                        painter.drawLine(x1, y1_down, x2, y2_down)

        # Legend
        if self.waveform_data is not None and isinstance(self.waveform_data, np.ndarray) and self.waveform_data.ndim == 2:
            painter.setPen(QPen(QColor(29, 185, 84, 220), 2))
            painter.drawLine(10, 15, 25, 15)
            painter.setPen(QPen(QColor(29, 185, 84, 220)))
            painter.drawText(30, 19, "L")
            painter.setPen(QPen(QColor(59, 130, 246, 220), 2))
            painter.drawLine(50, 15, 65, 15)
            painter.setPen(QPen(QColor(59, 130, 246, 220)))
            painter.drawText(70, 19, "R")

        progress_x = int((self.progress / 1000) * w)
        painter.fillRect(progress_x, 0, w - progress_x, h, QColor(0, 0, 0, 120))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(progress_x, 0, progress_x, h)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MusicPlayer()
    window.show()
    sys.exit(app.exec())
