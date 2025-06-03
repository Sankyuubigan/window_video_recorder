import tkinter as tk
from tkinter import messagebox
import os 
import sys 

initial_logs = []
def early_logger(message): print(message); initial_logs.append(message)

try:
    from config import FFMPEG_PATH 
except ImportError as e_conf:
    early_logger(f"[Main] КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать config.py: {e_conf}")
    sys.exit(1)

early_logger(f"[Config] Установлен путь к FFmpeg (из config.py): {FFMPEG_PATH}")

try:
    from app_gui import ScreenRecorderApp 
except ImportError as e:
    early_logger(f"Критическая ошибка импорта app_gui.py: {e}")
    sys.exit(1)
except Exception as e_generic_app_gui_import:
    early_logger(f"Неожиданная ошибка импорта app_gui.py: {e_generic_app_gui_import}")
    import traceback; early_logger(traceback.format_exc())
    sys.exit(1)

def check_ffmpeg_availability(logger_func=print):
    # ... (без изменений, как в предыдущем ответе) ...
    ffmpeg_path_to_check = FFMPEG_PATH
    if ffmpeg_path_to_check.lower() == "ffmpeg": 
        ffmpeg_path_to_check = os.popen("where ffmpeg").read().strip() 
        if not ffmpeg_path_to_check: 
             ffmpeg_path_to_check = os.popen("which ffmpeg").read().strip()
    
    if os.path.exists(ffmpeg_path_to_check) and os.access(ffmpeg_path_to_check, os.X_OK):
        logger_func(f"[Main] FFmpeg найден: {ffmpeg_path_to_check}")
        return True, f"FFmpeg найден: {ffmpeg_path_to_check}"
    else:
        fallback_path_in_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg_bin", "ffmpeg.exe")
        if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) and os.access(FFMPEG_PATH, os.X_OK): 
             logger_func(f"[Main] FFmpeg найден по пути из config: {FFMPEG_PATH}")
             return True, f"FFmpeg найден: {FFMPEG_PATH}"
        elif os.path.exists(fallback_path_in_bin) and os.access(fallback_path_in_bin, os.X_OK):
             logger_func(f"[Main] FFmpeg найден в ./ffmpeg_bin/ffmpeg.exe.")
             return True, f"FFmpeg найден в ./ffmpeg_bin/ffmpeg.exe."
        else:
            err_msg = f"FFmpeg не найден. Проверьте PATH или '{FFMPEG_PATH}', или ffmpeg_bin."
            logger_func(f"[Main] {err_msg}")
            return False, err_msg

if __name__ == "__main__":
    early_logger("[Main] Приложение использует GDI (PrintWindow) и FFmpeg-Python для захвата.") # Обновлено

    ffmpeg_ok, ffmpeg_message = check_ffmpeg_availability(logger_func=early_logger)
    if not ffmpeg_ok:
        warn_title_ffmpeg = "Предупреждение FFmpeg"
        warn_message_ffmpeg = ffmpeg_message + "\n\nЗапись может не работать без FFmpeg."
        early_logger(f"[Main] {warn_title_ffmpeg}: {warn_message_ffmpeg}")
        try: 
            root_check_ff = tk.Tk(); root_check_ff.withdraw()
            messagebox.showwarning(warn_title_ffmpeg, warn_message_ffmpeg, parent=None)
            root_check_ff.destroy() 
        except: pass
    else:
        early_logger(f"[Main] {ffmpeg_message}")

    app_instance = None; root = None 
    try:
        root = tk.Tk()
        app_instance = ScreenRecorderApp(root) 
        if app_instance and hasattr(app_instance, 'log_buffer'):
            for log_msg in initial_logs: app_instance.log_message(f"[EARLY_LOG] {log_msg}")
        if root.winfo_exists(): root.mainloop()
    except Exception as e_mainloop:
        early_logger(f"[Main] КРИТИЧЕСКАЯ ОШИБКА GUI: {e_mainloop}")
        import traceback; early_logger(traceback.format_exc())
    finally:
        if app_instance and hasattr(app_instance, '_save_app_settings') and hasattr(app_instance, 'master') and app_instance.master.winfo_exists():
            try: app_instance._save_app_settings()
            except: pass
        early_logger("[Main] Приложение завершает работу.")