import sys
import os

FFMPEG_EXE_NAME = "ffmpeg.exe"
ICON_FILE_NAME = "app_icon.ico" 

ffmpeg_path_final = "ffmpeg" 
icon_path_final = None

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    application_path = sys._MEIPASS 
    
    path_to_ffmpeg_in_bundle = os.path.join(application_path, FFMPEG_EXE_NAME)
    if os.path.exists(path_to_ffmpeg_in_bundle):
        ffmpeg_path_final = path_to_ffmpeg_in_bundle
    else:
        exe_dir_path = os.path.dirname(sys.executable)
        path_to_ffmpeg_near_exe = os.path.join(exe_dir_path, FFMPEG_EXE_NAME)
        if os.path.exists(path_to_ffmpeg_near_exe):
            ffmpeg_path_final = path_to_ffmpeg_near_exe

    path_to_icon_in_bundle = os.path.join(application_path, ICON_FILE_NAME)
    if os.path.exists(path_to_icon_in_bundle):
        icon_path_final = path_to_icon_in_bundle
    else:
        exe_dir_path = os.path.dirname(sys.executable)
        path_to_icon_near_exe = os.path.join(exe_dir_path, ICON_FILE_NAME)
        if os.path.exists(path_to_icon_near_exe):
            icon_path_final = path_to_icon_near_exe
            
else:
    current_script_dir = os.path.dirname(os.path.abspath(__file__)) 
    project_root_dir = os.path.dirname(current_script_dir)         

    ffmpeg_in_project_root = os.path.join(project_root_dir, FFMPEG_EXE_NAME)
    if os.path.exists(ffmpeg_in_project_root):
        ffmpeg_path_final = ffmpeg_in_project_root
    
    icon_in_project_root = os.path.join(project_root_dir, ICON_FILE_NAME)
    if os.path.exists(icon_in_project_root):
        icon_path_final = icon_in_project_root
    else: 
        icon_in_core = os.path.join(current_script_dir, ICON_FILE_NAME)
        if os.path.exists(icon_in_core):
            icon_path_final = icon_in_core

FFMPEG_PATH = ffmpeg_path_final
APP_ICON_PATH = icon_path_final 

print(f"[Config] Установлен путь к FFmpeg: {FFMPEG_PATH}")
if APP_ICON_PATH: print(f"[Config] Установлен путь к иконке: {APP_ICON_PATH}")
else: print(f"[Config] Путь к иконке не определен.")

DEFAULT_FRAMERATE = 25 
DEFAULT_VIDEO_PRESET = "medium" 
DEFAULT_VIDEO_CRF = "28"      
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_AUDIO_BITRATE = "128k"

# Возвращаем CONTROL_MASK
CONTROL_MASK = 0x0004 # Control key mask for checking Ctrl key press

APP_NAME_FOR_SETTINGS = "VideoConfRecorder"
if sys.platform == "win32": SETTINGS_DIR_BASE = os.getenv('APPDATA')
elif sys.platform == "darwin": SETTINGS_DIR_BASE = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
else: SETTINGS_DIR_BASE = os.getenv('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')

if SETTINGS_DIR_BASE: APP_SETTINGS_DIR = os.path.join(SETTINGS_DIR_BASE, APP_NAME_FOR_SETTINGS)
else: APP_SETTINGS_DIR = os.path.join(os.path.expanduser('~'), f'.{APP_NAME_FOR_SETTINGS.lower()}_settings')

DEFAULT_SETTINGS_FILE_NAME = "settings.json"
NO_AUDIO_DEVICE_SELECTED = "<Нет>" 