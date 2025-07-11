import tkinter as tk
from tkinter import messagebox
import os 
import sys 

initial_logs = []
def early_logger(message): print(message); initial_logs.append(message)

# Пробуем импортировать config, но если не получится, приложение не сможет работать.
# try-except здесь для логирования, но sys.exit(1) все равно необходим.
try:
    from config import FFMPEG_PATH 
except ImportError as e_conf:
    early_logger(f"[Main] КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать config.py: {e_conf}")
    # Попытка показать messagebox, если Tkinter доступен хотя бы базово
    try:
        root_err = tk.Tk(); root_err.withdraw()
        messagebox.showerror("Критическая ошибка", f"Не удалось загрузить конфигурацию (config.py): {e_conf}\nПриложение не может запуститься.")
        root_err.destroy()
    except Exception as e_msgbox:
        early_logger(f"[Main] Не удалось показать messagebox об ошибке config: {e_msgbox}")
    sys.exit(1)
except Exception as e_conf_generic: # Другие возможные ошибки при импорте config
    early_logger(f"[Main] НЕОЖИДАННАЯ КРИТИЧЕСКАЯ ОШИБКА при импорте config.py: {e_conf_generic}")
    import traceback; early_logger(traceback.format_exc())
    sys.exit(1)


early_logger(f"[Config] Установлен путь к FFmpeg (из config.py): {FFMPEG_PATH}")

# Аналогично для app_gui
try:
    from app_gui import ScreenRecorderApp 
except ImportError as e_app_gui_imp:
    early_logger(f"[Main] КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать app_gui.py: {e_app_gui_imp}")
    try:
        root_err_gui = tk.Tk(); root_err_gui.withdraw()
        messagebox.showerror("Критическая ошибка", f"Не удалось загрузить основной модуль GUI (app_gui.py): {e_app_gui_imp}\nПриложение не может запуститься.")
        root_err_gui.destroy()
    except Exception as e_msgbox_gui:
        early_logger(f"[Main] Не удалось показать messagebox об ошибке app_gui: {e_msgbox_gui}")
    sys.exit(1)
except Exception as e_generic_app_gui_import:
    early_logger(f"[Main] НЕОЖИДАННАЯ КРИТИЧЕСКАЯ ОШИБКА при импорте app_gui.py: {e_generic_app_gui_import}")
    import traceback; early_logger(traceback.format_exc())
    sys.exit(1)

def check_ffmpeg_availability(logger_func=print):
    ffmpeg_path_to_check = FFMPEG_PATH
    # Если FFMPEG_PATH просто "ffmpeg", пытаемся найти его в системном PATH
    if ffmpeg_path_to_check.lower() == "ffmpeg": 
        # Используем shutil.which для кросс-платформенного поиска
        import shutil
        found_path = shutil.which("ffmpeg")
        if found_path:
            logger_func(f"[Main] FFmpeg найден в PATH: {found_path}")
            return True, f"FFmpeg найден в PATH: {found_path}"
        else: # Если shutil.which не нашел, пробуем старые методы для информации
            path_from_where = os.popen("where ffmpeg").read().strip().split('\n')[0] if os.name == 'nt' else os.popen("which ffmpeg").read().strip()
            if path_from_where:
                 logger_func(f"[Main] FFmpeg (через os.popen) найден: {path_from_where}")
                 return True, f"FFmpeg найден: {path_from_where}"
            # Если и это не помогло, значит его нет в PATH
    
    # Если FFMPEG_PATH указан конкретно (не "ffmpeg") или если не найден в PATH
    if os.path.exists(ffmpeg_path_to_check) and os.access(ffmpeg_path_to_check, os.X_OK):
        logger_func(f"[Main] FFmpeg найден по пути (из config или прямой): {ffmpeg_path_to_check}")
        return True, f"FFmpeg найден: {ffmpeg_path_to_check}"
    
    # Если дошли сюда, FFmpeg не найден ни в PATH, ни по прямому пути из config (если он не "ffmpeg")
    err_msg = f"FFmpeg не найден. Проверьте системный PATH или путь в config.py ('{FFMPEG_PATH}')."
    logger_func(f"[Main] {err_msg}")
    return False, err_msg


if __name__ == "__main__":
    early_logger("[Main] Приложение использует GDI (PrintWindow) и FFmpeg-Python для захвата.") 

    ffmpeg_ok, ffmpeg_message = check_ffmpeg_availability(logger_func=early_logger)
    if not ffmpeg_ok:
        warn_title_ffmpeg = "Предупреждение FFmpeg"
        warn_message_ffmpeg = ffmpeg_message + "\n\nЗапись может не работать без FFmpeg."
        early_logger(f"[Main] {warn_title_ffmpeg}: {warn_message_ffmpeg}")
        try: 
            root_check_ff = tk.Tk(); root_check_ff.withdraw()
            messagebox.showwarning(warn_title_ffmpeg, warn_message_ffmpeg, parent=None)
            root_check_ff.destroy() 
        except Exception as e_msg_ff: # Ловим ошибку, если Tkinter еще не готов
            early_logger(f"[Main] Не удалось показать messagebox о FFmpeg: {e_msg_ff}")
            pass 
    else:
        early_logger(f"[Main] {ffmpeg_message}") # Логируем путь, если найден

    app_instance = None; root = None 
    try:
        root = tk.Tk()
        app_instance = ScreenRecorderApp(root) 
        # Передаем ранние логи в систему логирования приложения, если она готова
        if app_instance and hasattr(app_instance, 'log_message') and callable(app_instance.log_message):
            for log_msg in initial_logs: 
                app_instance.log_message(f"[EARLY_LOG] {log_msg}")
            initial_logs.clear() # Очищаем, чтобы не дублировать при перезапуске (если возможно)
        
        # Запускаем главный цикл только если root и app_instance созданы успешно
        if root and app_instance:
             if hasattr(root, 'winfo_exists') and root.winfo_exists(): # Доп. проверка перед mainloop
                root.mainloop()
             else:
                early_logger("[Main] Ошибка: root Tk() окно не существует перед mainloop.")
        else:
            early_logger("[Main] Ошибка: Не удалось создать root или app_instance. Приложение не будет запущено.")

    except Exception as e_mainloop: # Ловим любые ошибки на уровне инициализации GUI или mainloop
        # Используем early_logger, так как система логирования app_instance может быть недоступна
        early_logger(f"[Main] КРИТИЧЕСКАЯ ОШИБКА НА УРОВНЕ MAINLOOP ИЛИ ИНИЦИАЛИЗАЦИИ GUI: {e_mainloop}")
        import traceback; early_logger(traceback.format_exc())
        # Попытка показать ошибку пользователю, если Tkinter еще жив
        try:
            root_err_main = tk.Tk(); root_err_main.withdraw()
            messagebox.showerror("Критическая ошибка приложения", f"Произошла критическая ошибка:\n{e_mainloop}\n\nСм. консоль для деталей. Приложение будет закрыто.")
            root_err_main.destroy()
        except: pass # Если и это не удалось, ничего не поделать
    finally:
        # Настройки сохраняются в AppGUI.on_closing() перед уничтожением окна.
        # Повторная попытка сохранения здесь может вызвать ошибки, если GUI уже уничтожено,
        # и не нужна, если on_closing() отработал штатно.
        # Если приложение упало до вызова on_closing, состояние виджетов неопределенно.
        early_logger("[Main] Приложение завершает работу.")