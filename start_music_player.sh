#!/bin/bash

# Prüfe ob ffmpeg installiert ist
if ! command -v ffprobe &> /dev/null; then
    echo "ffprobe wird installiert..."
    sudo apt install -y ffmpeg
fi

# Starte den Music Player
cd "$(dirname "$0")"
source .venv/bin/activate
python music_player.py