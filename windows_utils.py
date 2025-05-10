import win32gui
import win32con
import time

def get_active_windows():
    """Возвращает словарь {title: hwnd} для видимых окон с заголовком."""
    # (Без изменений из предыдущего ответа)
    window_titles = {}
    def enum_windows_proc(hwnd, lParam):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            title = win32gui.GetWindowText(hwnd)
            window_titles[title] = hwnd
        return True
    win32gui.EnumWindows(enum_windows_proc, None)
    return window_titles

def prevent_minimize_loop(hwnd_to_protect, stop_event):
    """Поток для предотвращения сворачивания окна."""
    # (Без изменений из предыдущего ответа)
    print(f"[WindowsUtils] Защита от сворачивания запущена для HWND: {hwnd_to_protect}")
    while not stop_event.is_set():
        try:
            if win32gui.IsWindow(hwnd_to_protect):
                if win32gui.IsIconic(hwnd_to_protect):
                    print(f"[WindowsUtils] Окно {hwnd_to_protect} свернуто. Восстанавливаем...")
                    win32gui.ShowWindow(hwnd_to_protect, win32con.SW_RESTORE)
            else:
                print(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита остановлена.")
                break
        except win32gui.error as e:
            print(f"[WindowsUtils] Ошибка в потоке защиты (HWND: {hwnd_to_protect}): {e}")
            if e.winerror == 1400: # ERROR_INVALID_WINDOW_HANDLE
                break
        except Exception as e:
            print(f"[WindowsUtils] Неожиданная ошибка в потоке защиты: {e}")
            break
        time.sleep(0.2)
    print(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")