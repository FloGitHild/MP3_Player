import sys
import os
import datetime
import pygame
import numpy as np
import tempfile
from settings import Settings
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTreeWidget, QTreeWidgetItem, QTableWidget,
                             QTableWidgetItem, QPushButton, QLabel, QSlider, QMenuBar,
                             QMenu, QFileDialog, QMessageBox, QAbstractItemView, QHeaderView,
                             QSplitter, QDialog, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPainter, QPen
from mutagen.mp3 import MP3
from mutagen import MutagenError


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data = None
        self.setMinimumHeight(50)
        self.setMaximumHeight(60)
    
    def load_waveform(self, filepath):
        try:
            from pydub import AudioSegment

            # 🔥 MP3/WAV laden
            audio = AudioSegment.from_file(filepath)

            # auf mono reduzieren (wichtig für einfache Darstellung)
            samples = np.array(audio.get_array_of_samples())

            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                samples = samples.mean(axis=1)

            samples = samples.astype(float)

            # normalisieren
            samples /= np.max(np.abs(samples))

            # runter-samplen für Performance
            if len(samples) > 5000:
                indices = np.linspace(0, len(samples) - 1, 1000, dtype=int)
                samples = samples[indices]

            self.waveform_data = np.abs(samples)
            self.update()

        except Exception as e:
            print("Waveform error:", e)
            self.waveform_data = None
            self.update()
    
    def paintEvent(self, event):
        if self.waveform_data is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#1db954"))
        pen.setWidth(1)
        painter.setPen(pen)
        width = self.width()
        height = self.height()
        data = self.waveform_data
        step = width / len(data)
        center_y = height / 2
        for i, val in enumerate(data):
            x = int(i * step)
            amp = min(val * center_y * 0.9, center_y * 0.9)
            painter.drawLine(x, int(center_y - amp), x, int(center_y + amp))

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
        
    def fade_in(self, duration_ms=None):
        if self.fading:
            return
        if duration_ms is None:
            duration_ms = self.fade_in_duration
        self.fading = True
        self.fade_volume = 0.0
        steps = 10
        delay = max(1, duration_ms // steps)
        for i in range(steps + 1):
            self.fade_volume = i / steps
            pygame.mixer.music.set_volume(self.fade_volume)
            QThread.msleep(delay)
        pygame.mixer.music.set_volume(1.0)
        self.fading = False
    
    def fade_out(self, duration_ms=None):
        if self.fading:
            return
        if duration_ms is None:
            duration_ms = self.fade_out_duration
        self.fading = True
        steps = 10
        delay = max(1, duration_ms // steps)
        for i in range(steps, -1, -1):
            self.fade_volume = i / steps
            pygame.mixer.music.set_volume(self.fade_volume)
            QThread.msleep(delay)
        pygame.mixer.music.pause()
        pygame.mixer.music.set_volume(1.0)
        self.fading = False
        self.is_paused = True
        
    def run(self):
        while self._running:
            if self.is_playing and not self.is_paused:
                pos = pygame.mixer.music.get_pos()

                if pos >= 0:
                    corrected = pos + self.start_offset

                    # 🔥 verhindert negatives / reset glitch
                    if corrected < 0:
                        corrected = self.start_offset

                    self.position_changed.emit(corrected)

            self.msleep(100)
    
    def load(self, filepath):
        try:
            pygame.mixer.music.load(filepath)
            self.current_file = filepath
            try:
                audio = MP3(filepath)
                self.duration = int(audio.info.length * 1000)
            except:
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


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Music Player")
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(900, 600)
        
        self.settings = Settings()
        
        self.playlist = []
        self.current_track_index = -1
        
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
        self.load_directory(last_folder if last_folder and os.path.isdir(last_folder) else os.path.expanduser("~"))
    
    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        browser_widget = QWidget()
        browser_layout = QVBoxLayout(browser_widget)
        browser_layout.setContentsMargins(10, 10, 5, 10)
        
        browser_label = QLabel("File Browser")
        browser_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        browser_layout.addWidget(browser_label)
        
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser_layout.addWidget(self.file_tree)
        
        add_btn = QPushButton("Add to Playlist")
        add_btn.clicked.connect(self.add_selected_to_playlist)
        browser_layout.addWidget(add_btn)
        
        self.splitter.addWidget(browser_widget)
        
        playlist_widget = QWidget()
        playlist_layout = QVBoxLayout(playlist_widget)
        playlist_layout.setContentsMargins(5, 10, 10, 10)
        
        playlist_label = QLabel("Playlist")
        playlist_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        playlist_layout.addWidget(playlist_label)
        
        self.playlist_table = QTableWidget()
        self.playlist_table.setColumnCount(6)
        self.playlist_table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Year", "Changed", "Duration"])
        self.playlist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.playlist_table.setShowGrid(True)
        self.playlist_table.horizontalHeader().setStretchLastSection(False)
        for i in range(6):
            self.playlist_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        self.playlist_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.playlist_table.itemDoubleClicked.connect(self.play_track_from_playlist)
        playlist_layout.addWidget(self.playlist_table)
        
        btn_layout = QHBoxLayout()
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_from_playlist)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        
        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(40)
        up_btn.clicked.connect(self.move_up)
        btn_layout.addWidget(up_btn)
        
        down_btn = QPushButton("↓")
        down_btn.setFixedWidth(40)
        down_btn.clicked.connect(self.move_down)
        btn_layout.addWidget(down_btn)
        
        playlist_layout.addLayout(btn_layout)
        
        self.splitter.addWidget(playlist_widget)
        self.splitter.setSizes([300, 500])
        
        self.playbar = QWidget()
        self.playbar.setStyleSheet("background-color: #282828; padding: 10px;")
        playbar_layout = QVBoxLayout(self.playbar)
        playbar_layout.setContentsMargins(15, 5, 15, 5)
        
        controls_layout = QHBoxLayout()
        
        self.prev_btn = QPushButton("◀◀")
        self.prev_btn.setFixedSize(40, 40)
        self.prev_btn.clicked.connect(self.previous_track)
        controls_layout.addWidget(self.prev_btn)
        
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(50, 50)
        self.play_btn.setStyleSheet("font-size: 20px; background-color: #1db954; border-radius: 25px;")
        self.play_btn.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self.play_btn)
        
        self.next_btn = QPushButton("▶▶")
        self.next_btn.setFixedSize(40, 40)
        self.next_btn.clicked.connect(self.next_track)
        controls_layout.addWidget(self.next_btn)
        
        controls_layout.addStretch()
        
        self.track_label = QLabel("No track selected")
        self.track_label.setStyleSheet("font-size: 13px; color: #e0e0e0;")
        self.track_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(self.track_label)
        
        controls_layout.addStretch()
        
        playbar_layout.addLayout(controls_layout)
        
        time_layout = QHBoxLayout()
        time_layout.setContentsMargins(0, 0, 0, 0)
        self.current_time_label = QLabel("0:00")
        self.current_time_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.current_time_label.setFixedWidth(40)
        time_layout.addWidget(self.current_time_label)
        
        self.waveform_slider = WaveformSlider()
        self.waveform_slider.setMinimumHeight(70)
        self.waveform_slider.sliderPressed.connect(self.on_slider_pressed)
        self.waveform_slider.sliderReleased.connect(self.on_slider_released)
        self.waveform_slider.positionChanged.connect(self.on_slider_changed)
        time_layout.addWidget(self.waveform_slider, 1)
        
        self.total_time_label = QLabel("0:00")
        self.total_time_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.total_time_label.setFixedWidth(40)
        time_layout.addWidget(self.total_time_label)
        
        playbar_layout.addLayout(time_layout)
        
        self.main_layout.addWidget(self.splitter)
        self.main_layout.addWidget(self.playbar)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #333333; }
            QWidget { color: #cccccc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
            QTreeWidget { background-color: #3a3a3a; border: none; color: #a0a0a0; padding: 10px; }
            QTreeWidget::item { padding: 5px; }
            QTreeWidget::item:selected { background-color: #555555; color: #ffffff; }
            QTreeWidget::item:alternate { background-color: #454545; }
            QTableWidget { background-color: #3a3a3a; border: none; color: #a0a0a0; gridline-color: #505050; }
            QTableWidget::item { padding: 8px; border-right: 1px solid #505050; background-color: #3a3a3a; }
            QTableWidget::item:alternate { background-color: #454545; }
            QTableWidget::item:selected { background-color: #555555; color: #ffffff; }
            QHeaderView::section { background-color: #454545; color: #a0a0a0; padding: 8px; border: none; border-right: 1px solid #505050; }
            QPushButton { background-color: #505050; color: #cccccc; border: none; padding: 8px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #606060; }
            QPushButton:pressed { background-color: #707070; }
            QLabel { color: #cccccc; }
            QSlider::groove:horizontal { background: #505050; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #1db954; width: 14px; margin: -4px 0; border-radius: 7px; }
            QSlider::sub-page:horizontal { background: #1db954; border-radius: 3px; }
            QMenuBar { background-color: #3a3a3a; color: #cccccc; }
            QMenuBar::item:selected { background-color: #505050; }
            QMenu { background-color: #3a3a3a; color: #cccccc; }
            QMenu::item:selected { background-color: #505050; }
            QSplitter::handle { background-color: #555555; width: 3px; }
        """)
        
        self.slider_pressed = False
    
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
        save_playlist_action = QAction("Save Playlist", self)
        save_playlist_action.triggered.connect(self.save_playlist)
        playlist_menu.addAction(save_playlist_action)
        load_playlist_action = QAction("Load Playlist", self)
        load_playlist_action.triggered.connect(self.load_playlist)
        playlist_menu.addSeparator()
        clear_playlist_action = QAction("Clear Playlist", self)
        clear_playlist_action.triggered.connect(self.clear_playlist)
        playlist_menu.addAction(clear_playlist_action)
        
        settings_menu = menubar.addMenu("Settings")
        settings_action = QAction("Preferences", self)
        settings_action.triggered.connect(self.show_settings)
        settings_menu.addAction(settings_action)
        
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setMinimumWidth(350)
        
        layout = QVBoxLayout()
        
        fade_label = QLabel("Fade Settings")
        fade_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(fade_label)
        
        fade_in_btn = QPushButton("Fade In: " + str(self.settings.fade_in_ms) + " ms")
        fade_in_btn.setMinimumHeight(40)
        
        def cycle_fade_in():
            values = [25, 50, 75, 100, 150, 200]
            current = self.settings.fade_in_ms
            idx = values.index(current) if current in values else 0
            next_val = values[(idx + 1) % len(values)]
            self.settings.fade_in_ms = next_val
            fade_in_btn.setText("Fade In: " + str(next_val) + " ms")
            self.audio_player.fade_in_duration = next_val
        
        fade_in_btn.clicked.connect(cycle_fade_in)
        layout.addWidget(fade_in_btn)
        
        fade_out_btn = QPushButton("Fade Out: " + str(self.settings.fade_out_ms) + " ms")
        fade_out_btn.setMinimumHeight(40)
        
        def cycle_fade_out():
            values = [25, 50, 75, 100, 150, 200]
            current = self.settings.fade_out_ms
            idx = values.index(current) if current in values else 0
            next_val = values[(idx + 1) % len(values)]
            self.settings.fade_out_ms = next_val
            fade_out_btn.setText("Fade Out: " + str(next_val) + " ms")
            self.audio_player.fade_out_duration = next_val
        
        fade_out_btn.clicked.connect(cycle_fade_out)
        layout.addWidget(fade_out_btn)
        
        layout.addSpacing(20)
        
        folder_label = QLabel("Folder Settings")
        folder_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(folder_label)
        
        restore_btn = QPushButton("Restore Last Folder: ON" if self.settings.restore_last_folder else "Restore Last Folder: OFF")
        restore_btn.setMinimumHeight(40)
        
        def toggle_restore():
            new_val = not self.settings.restore_last_folder
            self.settings.restore_last_folder = new_val
            restore_btn.setText("Restore Last Folder: ON" if new_val else "Restore Last Folder: OFF")
        
        restore_btn.clicked.connect(toggle_restore)
        layout.addWidget(restore_btn)
        
        layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.setMinimumHeight(40)
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.settings.last_folder = folder
            self.load_directory(folder)
    
    def load_directory(self, path):
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
                folder_path = item.data(0, Qt.ItemDataRole.UserRole)
                self.populate_tree(item, folder_path, lazy=False)
            item.setExpanded(not item.isExpanded())
        elif item_type == "file":
            self.add_to_playlist(path)
    
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
        widget = WaveformWidget()
        widget.load_waveform(filepath)
        return widget.waveform_data
    
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
        
        mtime = os.path.getmtime(filepath)
        date = datetime.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y")
        
        self.playlist.append({
            'filepath': filepath,
            'title': title,
            'artist': artist,
            'year': year,
            'date': date,
            'duration': duration,
            'duration_sec': duration_sec,
            'mtime': mtime
        })
        self.update_playlist_table()
    
    def add_selected_to_playlist(self):
        items = self.file_tree.selectedItems()
        for item in items:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if item_type == "folder":
                self.add_folder_to_playlist(path)
            elif item_type == "file":
                self.add_to_playlist(path)
    
    def add_folder_to_playlist(self, folder_path):
        for root, dirs, files in os.walk(folder_path):
            for file in sorted(files):
                if file.lower().endswith(('.mp3', '.wav')):
                    filepath = os.path.join(root, file)
                    self.add_to_playlist(filepath)
    
    def remove_from_playlist(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()), reverse=True)
        for row in rows:
            if 0 <= row < len(self.playlist):
                self.playlist.pop(row)
        self.update_playlist_table()
        
        if self.current_track_index >= len(self.playlist):
            self.current_track_index = len(self.playlist) - 1
    
    def update_playlist_table(self):
        self.playlist_table.setRowCount(len(self.playlist))
        
        for i, track in enumerate(self.playlist):
            self.playlist_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.playlist_table.setItem(i, 1, QTableWidgetItem(track['title']))
            self.playlist_table.setItem(i, 2, QTableWidgetItem(track['artist']))
            self.playlist_table.setItem(i, 3, QTableWidgetItem(str(track.get('year', ''))))
            self.playlist_table.setItem(i, 4, QTableWidgetItem(str(track.get('date', ''))))
            self.playlist_table.setItem(i, 5, QTableWidgetItem(track['duration']))
    
    def sort_playlist(self, column, reverse=False):
        if column == 1:
            self.playlist.sort(key=lambda x: x['title'].lower(), reverse=reverse)
        elif column == 2:
            self.playlist.sort(key=lambda x: x['artist'].lower(), reverse=reverse)
        elif column == 3:
            self.playlist.sort(key=lambda x: x.get('year', ''), reverse=reverse)
        elif column == 4:
            self.playlist.sort(key=lambda x: x.get('mtime', 0), reverse=reverse)
        elif column == 5:
            self.playlist.sort(key=lambda x: x.get('duration_sec', 0), reverse=reverse)
        self.update_playlist_table()
    
    def on_header_clicked(self, column):
        if column == 0:
            return
        if hasattr(self, 'last_sort_column') and self.last_sort_column == column:
            reverse = not self.last_sort_reverse
        else:
            reverse = False
        self.last_sort_column = column
        self.last_sort_reverse = reverse
        self.sort_playlist(column, reverse)
    
    def move_up(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()))
        for row in rows:
            if row > 0:
                self.playlist[row], self.playlist[row - 1] = self.playlist[row - 1], self.playlist[row]
        self.update_playlist_table()
    
    def move_down(self):
        rows = sorted(set(item.row() for item in self.playlist_table.selectedItems()), reverse=True)
        for row in rows:
            if row < len(self.playlist) - 1:
                self.playlist[row], self.playlist[row + 1] = self.playlist[row + 1], self.playlist[row]
        self.update_playlist_table()
    
    def play_track_from_playlist(self, item):
        row = item.row()
        self.play_track(row)
    
    def play_track(self, index):
        if 0 <= index < len(self.playlist):
            self.current_track_index = index
            track = self.playlist[index]
            
            if self.audio_player.load(track['filepath']):
                self.audio_player.play()
                self.track_label.setText(f"{track['title']} - {track['artist']}")
                self.play_btn.setText("⏸")
                self.playlist_table.selectRow(index)
                data = self.load_waveform(track['filepath'])
                self.waveform_slider.set_waveform(data)
    
    def toggle_play_pause(self):
        if not self.playlist:
            return

        # 🔥 Wenn nichts läuft → ausgewählten Track starten
        if self.current_track_index == -1:
            selected = self.playlist_table.currentRow()

            if selected >= 0:
                self.play_track(selected)
            else:
                self.play_track(0)
            return

        # 🔥 normal play/pause
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
        if self.current_track_index < len(self.playlist) - 1:
            self.play_track(self.current_track_index + 1)
        elif len(self.playlist) > 0:
            self.play_track(0)
    
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
    
    def update_progress(self):
        pos = pygame.mixer.music.get_pos()
        if pos > 0:
            duration = self.audio_player.get_duration()
            if duration > 0:
                value = int(pos * 1000 / duration)
                self.waveform_slider.set_progress(value)
                self.current_time_label.setText(self.format_time(int(pos / 1000)))
                self.total_time_label.setText(self.format_time(int(duration / 1000)))
    
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
    
    def track_finished(self):
        if self.current_track_index < len(self.playlist) - 1:
            self.next_track()
        else:
            self.play_btn.setText("▶")
    
    def format_time(self, seconds):
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"
    
    def save_playlist(self):
        if not self.playlist:
            return
        
        filename, _ = QFileDialog.getSaveFileName(self, "Save Playlist", "", "M3U Playlist (*.m3u)")
        if filename:
            with open(filename, 'w', encoding='utf-8') as f:
                for track in self.playlist:
                    f.write(track['filepath'] + '\n')
            QMessageBox.information(self, "Success", "Playlist saved successfully!")
    
    def load_playlist(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Playlist", "", "M3U Playlist (*.m3u)")
        if filename:
            self.playlist.clear()
            with open(filename, 'r', encoding='utf-8') as f:
                for line in f:
                    filepath = line.strip()
                    if os.path.exists(filepath):
                        self.add_to_playlist(filepath)
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
        table_width = self.playlist_table.width()
        hash_width = int(table_width * 0.05)
        title_width = int(table_width * 0.30)
        artist_width = int(table_width * 0.30)
        year_width = int(table_width * 0.125)
        date_width = int(table_width * 0.1125)
        duration_width = table_width - hash_width - title_width - artist_width - year_width - date_width
        
        self.playlist_table.setColumnWidth(0, hash_width)
        self.playlist_table.setColumnWidth(1, title_width)
        self.playlist_table.setColumnWidth(2, artist_width)
        self.playlist_table.setColumnWidth(3, year_width)
        self.playlist_table.setColumnWidth(4, date_width)
        self.playlist_table.setColumnWidth(5, duration_width)
    
    def closeEvent(self, event):
        self.audio_player.stop_thread()
        super().closeEvent(event)


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
        ratio = x / self.width()
        self.progress = max(0, min(1000, int(ratio * 1000)))
        self.positionChanged.emit(self.progress)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        center = h // 2

        # ===== Waveform (oben + unten!) =====
        if self.waveform_data is not None:
            pen = QPen(QColor("#1db954"))
            painter.setPen(pen)

            step = w / len(self.waveform_data)

            for i, val in enumerate(self.waveform_data):
                x = int(i * step)
                amp = int(val * center * 0.9)
                painter.drawLine(x, center - amp, x, center + amp)

        # ===== Progress Overlay =====
        progress_x = int((self.progress / 1000) * w)
        painter.fillRect(progress_x, 0, w - progress_x, h, QColor(0, 0, 0, 120))

        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(progress_x, 0, progress_x, h)

class WaveformBackground(QWidget):
    def __init__(self, slider, parent=None):
        super().__init__(parent)
        self.slider = slider
        self.waveform_data = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def set_waveform(self, data):
        self.waveform_data = data
        self.update()

    def paintEvent(self, event):
        if self.waveform_data is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        center = h // 2

        # 🔥 dezente Farbe (nicht mehr grell)
        pen = QPen(QColor(80, 200, 120, 120))
        pen.setWidth(1)
        painter.setPen(pen)

        step = max(1, int(len(self.waveform_data) / w))

        for x in range(w):
            idx = x * step
            if idx >= len(self.waveform_data):
                break

            val = self.waveform_data[idx]
            amp = int(val * center * 0.8)

            painter.drawLine(x, center - amp, x, center + amp)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MusicPlayer()
    window.show()
    sys.exit(app.exec())