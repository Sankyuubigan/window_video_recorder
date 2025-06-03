from window_capture import WindowCapture
# Импортируем WGCCapture и флаг доступности из него
from wgc_capture import WGCCapture, is_wgc_fully_available as wgc_module_available
from config import CAPTURE_METHOD_GDI, CAPTURE_METHOD_WGC
import sys

def initialize_capturer(hwnd, requested_capture_method, logger_func):
    """
    Инициализирует подходящий захватчик экрана (WGCCapture или WindowCapture).
    Возвращает кортеж (capturer_instance, actual_method_used, error_message).
    Если error_message не None, инициализация не удалась.
    `wgc_available_os_com` теперь не передается, определяется из wgc_capture.py
    """
    capturer_instance = None
    actual_method_used = requested_capture_method
    error_message = "Неизвестная ошибка инициализации захвата."
    init_success = False

    # Проверяем доступность WGC на уровне модуля (импорты winsdk)
    wgc_is_generally_available = wgc_module_available()
    logger_func(f"[CaptureInit] Проверка доступности WGC модуля: {wgc_is_generally_available}")


    if actual_method_used == CAPTURE_METHOD_WGC and wgc_is_generally_available and sys.platform == "win32":
        logger_func(f"[CaptureInit] Попытка инициализации WGCCapture для HWND: {hwnd}")
        try:
            capturer_instance = WGCCapture(hwnd, logger_func=logger_func)
            if capturer_instance.is_initialized:
                init_success = True
                logger_func(f"[CaptureInit] WGCCapture (is_init: True): {capturer_instance.item_width}x{capturer_instance.item_height}")
                error_message = None 
            else:
                # WGCCapture сам должен был залогировать причину, если is_initialized=False
                error_message = "WGCCapture не удалось инициализировать (см. лог WGCCapture). Попытка GDI."
                logger_func(f"[CaptureInit] {error_message}")
                actual_method_used = CAPTURE_METHOD_GDI 
                capturer_instance = None # Сбрасываем, чтобы не использовать частично инициализированный
        except Exception as e_wgc: # Ловим ошибки конструктора WGCCapture, если они не были обработаны внутри
            error_message = f"Критическая ошибка конструктора WGCCapture: {e_wgc}. Попытка GDI."
            logger_func(f"[CaptureInit] {error_message}")
            actual_method_used = CAPTURE_METHOD_GDI
            capturer_instance = None
    elif actual_method_used == CAPTURE_METHOD_WGC and (not wgc_is_generally_available or not sys.platform == "win32"):
        logger_func(f"[CaptureInit] WGC запрошен, но недоступен (модуль: {wgc_is_generally_available}, платформа: {sys.platform}). Переключение на GDI.")
        actual_method_used = CAPTURE_METHOD_GDI
    
    # Если выбран GDI (изначально или как фоллбэк)
    if actual_method_used == CAPTURE_METHOD_GDI and not init_success: # Проверяем init_success, чтобы не перезаписывать успешный WGC
        logger_func(f"[CaptureInit] Попытка инициализации WindowCapture (GDI) для HWND: {hwnd}")
        try:
            capturer_instance = WindowCapture(hwnd, logger_func=logger_func)
            if capturer_instance.is_initialized_properly:
                init_success = True
                logger_func(f"[CaptureInit] WindowCapture (GDI) (is_init: True): {capturer_instance.width}x{capturer_instance.height}")
                error_message = None 
            else:
                # WindowCapture должен был залогировать причину
                error_message = "WindowCapture (GDI) не удалось инициализировать (см. лог WindowCapture)."
                logger_func(f"[CaptureInit] {error_message}")
                capturer_instance = None # Явно сбрасываем
        except ValueError as e_gdi_val: # Ошибка, которую WindowCapture может бросить при невалидном HWND
            error_message = f"Ошибка WindowCapture (GDI - ValueError): {e_gdi_val}"
            logger_func(f"[CaptureInit] {error_message}")
            capturer_instance = None
        except Exception as e_gdi_generic: # Другие ошибки конструктора GDI
            error_message = f"Критическая ошибка конструктора WindowCapture (GDI): {e_gdi_generic}"
            logger_func(f"[CaptureInit] {error_message}")
            capturer_instance = None
            
    if not init_success:
        # error_message уже должен быть установлен выше, если была попытка инициализации
        if not error_message or error_message == "Неизвестная ошибка инициализации захвата.":
            # Если ни одна ветка не была выполнена или error_message не обновился
            if actual_method_used == CAPTURE_METHOD_WGC:
                error_message = "WGC не доступен или не удалось инициализировать."
            else: # GDI
                error_message = "GDI не удалось инициализировать."
        logger_func(f"[CaptureInit] Инициализация захвата НЕ удалась. Метод: {actual_method_used}. Ошибка: {error_message}")
        return None, actual_method_used, error_message

    logger_func(f"[CaptureInit] Захватчик успешно инициализирован методом: {actual_method_used}")
    return capturer_instance, actual_method_used, None