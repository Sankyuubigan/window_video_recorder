import win32gui
import win32con
import time

def get_active_windows():
    """
    Возвращает словарь {title: hwnd} для видимых окон с непустым заголовком.
    Использует более простую фильтрацию, чтобы вернуть больше окон.
    """
    window_titles = {}
    def enum_windows_proc(hwnd, lParam):
        # 1. Окно должно быть видимо
        if not win32gui.IsWindowVisible(hwnd):
            return True # Продолжаем перечисление

        # 2. У окна должен быть текст (заголовок)
        window_text_length = win32gui.GetWindowTextLength(hwnd)
        if window_text_length == 0:
            return True # Продолжаем перечисление
        
        title = win32gui.GetWindowText(hwnd)
        
        # 3. Заголовок не должен быть пустым или состоять только из пробелов
        if not title or not title.strip():
            return True # Продолжаем перечисление

        # 4. Исключаем окна без родителя, которые не являются основным окном рабочего стола
        # Это помогает отфильтровать некоторые фоновые "невидимые" окна, которые могут иметь заголовок
        # h_parent = win32gui.GetParent(hwnd)
        # shell_window = win32gui.GetShellWindow()
        # if h_parent == 0 and hwnd != shell_window: # Окно верхнего уровня, не рабочий стол
             # Можно добавить дополнительные проверки здесь, если нужно
             # Например, на стиль WS_EX_TOOLWINDOW, чтобы исключить панели инструментов
             # ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
             # if ex_style & win32con.WS_EX_TOOLWINDOW:
             # return True
        #    pass # Пропускаем это условие, чтобы быть менее строгим

        # 5. Проверка на минимальные размеры (чтобы отсеять совсем уж невидимые компоненты)
        # Но делаем ее очень мягкой, чтобы не отфильтровать ваше окно, если оно специфичное.
        try:
            rect = win32gui.GetWindowRect(hwnd)
            # Условие (rect[2] - rect[0]) > 1 and (rect[3] - rect[1]) > 1 было слишком мягким.
            # Попробуем чуть строже, но не сильно. GDI захват все равно не сработает для нулевых размеров.
            # Захват окна с размером 1x1 пиксель обычно не имеет смысла.
            # Для WGC размеры получаются из GraphicsCaptureItem.
            # Если ваше окно имеет специфичные размеры или стиль, этот фильтр может его убирать.
            # Пока оставим проверку на > 0, чтобы быть максимально нестрогим.
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width > 0 and height > 0: # Окно должно иметь хоть какие-то размеры
                # Добавляем в список, если заголовок уникален. Если нет - можно добавить (HWND) к заголовку.
                # Пока просто перезаписываем, если заголовок совпадает (последнее найденное окно с таким заголовком).
                # Для уникальности лучше использовать список кортежей (title, hwnd), а не словарь.
                # Но для Combobox словарь {title: hwnd} и затем sorted(titles) подходит.
                window_titles[title] = hwnd
        except win32gui.error:
            # Окно могло исчезнуть между IsWindowVisible и GetWindowRect
            pass
        return True

    win32gui.EnumWindows(enum_windows_proc, None)
    return window_titles

def get_window_geometry(hwnd):
    """Возвращает геометрию окна (x, y, width, height)."""
    # Без try-except, ошибка будет проброшена, если hwnd невалиден
    rect = win32gui.GetWindowRect(hwnd)
    x = rect[0]
    y = rect[1]
    width = rect[2] - x
    height = rect[3] - y
    return {"x": x, "y": y, "width": width, "height": height}


def prevent_minimize_loop(hwnd_to_protect, stop_event, logger_func=print):
    logger_func(f"[WindowsUtils] Защита от сворачивания запущена для HWND: {hwnd_to_protect}")
    while not stop_event.is_set():
        try:
            if win32gui.IsWindow(hwnd_to_protect): 
                if win32gui.IsIconic(hwnd_to_protect):
                    logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} свернуто. Восстанавливаем...")
                    win32gui.ShowWindow(hwnd_to_protect, win32con.SW_RESTORE)
            else:
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита остановлена.")
                break 
        except win32gui.error as e: # Ловим только win32gui.error
            logger_func(f"[WindowsUtils] Ошибка win32gui в потоке защиты (HWND: {hwnd_to_protect}): {e}")
            # Ошибка 1400: "Неверный дескриптор окна." - окно закрыто.
            if hasattr(e, 'winerror') and e.winerror == 1400: 
                logger_func(f"[WindowsUtils] Ошибка 1400 (неверный дескриптор), окно, вероятно, закрыто.")
                break
            # Другие ошибки win32gui могут быть временными, продолжаем цикл
        except Exception as e_generic: # Ловим другие неожиданные ошибки
            logger_func(f"[WindowsUtils] Неожиданная ошибка в потоке защиты: {e_generic}")
            break # При неожиданной ошибке лучше остановить поток
        time.sleep(0.1)
    logger_func(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")
