import tkinter as tk
from tkinter import messagebox
import subprocess

from app_gui import ScreenRecorderApp
from config import FFMPEG_PATH 

def check_ffmpeg():
    """Проверяет доступность FFmpeg."""
    # (Без изменений из предыдущего ответа)
    print("[Main] Проверка FFmpeg...")
    try:
        p_info = subprocess.STARTUPINFO()
        p_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        p_info.wShowWindow = subprocess.SW_HIDE
        p = subprocess.Popen([FFMPEG_PATH, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                             startupinfo=p_info, text=True, encoding='utf-8', errors='ignore')
        stdout, stderr = p.communicate(timeout=10)
        if p.returncode != 0: 
            print(f"[Main] FFmpeg version check failed. Код: {p.returncode}\nStdout: {stdout}\nStderr: {stderr}")
            return False, f"FFmpeg вернул код ошибки {p.returncode} при проверке версии. Проверьте консоль."
        print(f"[Main] FFmpeg version: {stdout.splitlines()[0] if stdout else 'Не удалось получить версию'}")
        return True, "FFmpeg найден."
    except FileNotFoundError:
        print(f"[Main] FFmpeg не найден по пути '{FFMPEG_PATH}'.")
        return False, f"FFmpeg не найден по пути '{FFMPEG_PATH}'. Убедитесь, что он установлен и путь указан верно (в PATH или в config.py)."
    except subprocess.TimeoutExpired:
        print("[Main] Проверка версии FFmpeg заняла слишком много времени (timeout).")
        return False, "Проверка версии FFmpeg заняла слишком много времени (timeout)."
    except Exception as e:
        print(f"[Main] Ошибка при проверке FFmpeg: {e}")
        return False, f"Ошибка при проверке FFmpeg: {e}"

if __name__ == "__main__":
    ffmpeg_ok, ffmpeg_message = check_ffmpeg()
    
    if not ffmpeg_ok:
        root_check = tk.Tk()
        root_check.withdraw() 
        messagebox.showerror("Ошибка FFmpeg", ffmpeg_message + "\n\nПрограмма не может работать без FFmpeg.")
        root_check.destroy()
        exit()
    
    print(f"[Main] {ffmpeg_message}")

    root = tk.Tk()
    app = ScreenRecorderApp(root)
    root.mainloop()