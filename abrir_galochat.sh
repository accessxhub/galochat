#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 -c "import telethon, imageio_ffmpeg" 2>/dev/null || python3 -m pip install -r requirements.txt
exec python3 galochat_app.py
