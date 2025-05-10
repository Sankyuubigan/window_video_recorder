import sys
import os

# Определение пути к FFmpeg
# Если программа запущена как замороженный .exe (PyInstaller)
if getattr(sys, 'frozen', False):
    # Путь к исполняемому файлу приложения
    application_path = os.path.dirname(sys.executable)
    # Согласно build.py (add_binary "ffmpeg_bin/ffmpeg.exe:."), ffmpeg.exe будет в корне сборки
    ffmpeg_exe_path = os.path.join(application_path, "ffmpeg.exe")
else:
    # Если запускается из исходников, предполагаем, что ffmpeg.exe в подпапке ffmpeg_bin
    # относительно корня проекта (где лежит config.py) или просто 'ffmpeg' если он в PATH
    application_path = os.path.dirname(os.path.abspath(__file__)) # Каталог, где лежит config.py
    ffmpeg_exe_path_local = os.path.join(application_path, "ffmpeg_bin", "ffmpeg.exe")
    
    # Проверяем, существует ли локальный ffmpeg.exe в ffmpeg_bin
    if os.path.exists(ffmpeg_exe_path_local):
        ffmpeg_exe_path = ffmpeg_exe_path_local
    else:
        # Если локальный не найден, полагаемся на PATH
        ffmpeg_exe_path = "ffmpeg" 

FFMPEG_PATH = ffmpeg_exe_path
print(f"[Config] Установлен путь к FFmpeg: {FFMPEG_PATH}")

DEFAULT_FRAMERATE = 25 
DEFAULT_VIDEO_PRESET = "ultrafast"
DEFAULT_VIDEO_CRF = "23" 
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_AUDIO_BITRATE = "192k"