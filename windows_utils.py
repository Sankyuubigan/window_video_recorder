import win32gui
import win32con
import time

def get_active_windows():
    """Возвращает словарь {title: hwnd} для видимых окон с заголовком."""
    window_titles = {}
    def enum_windows_proc(hwnd, lParam):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            title = win32gui.GetWindowText(hwnd)
            # Исключаем пустые заголовки или окна без видимых размеров (например, некоторые фоновые процессы)
            try:
                rect = win32gui.GetWindowRect(hwnd)
                if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0 : # Ширина и высота > 0
                    window_titles[title] = hwnd
            except win32gui.error:
                pass # Окно могло исчезнуть
        return True
    win32gui.EnumWindows(enum_windows_proc, None)
    return window_titles

def get_window_geometry(hwnd):
    """Возвращает геометрию окна (x, y, width, height)."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        x = rect[0]
        y = rect[1]
        width = rect[2] - x
        height = rect[3] - y
        # Убедимся, что размеры четные для crop, если это важно для последующих фильтров
        # Однако, scale фильтр после crop позаботится об этом
        return {"x": x, "y": y, "width": width, "height": height}
    except win32gui.error:
        return None


def prevent_minimize_loop(hwnd_to_protect, stop_event):
    """Поток для предотвращения сворачивания окна."""
    # (Без изменений)
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
            if e.winerror == 1400: break
        except Exception as e:
            print(f"[WindowsUtils] Неожиданная ошибка в потоке защиты: {e}")
            break
        time.sleep(0.2)
    print(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")