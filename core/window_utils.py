import win32gui
import win32con
import time
import win32ui 
import win32api 
import numpy as np 
import cv2 
import ctypes

BI_RGB = 0
DIB_RGB_COLORS = 0

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', ctypes.c_ulong), ('biWidth', ctypes.c_long),
        ('biHeight', ctypes.c_long), ('biPlanes', ctypes.c_ushort),
        ('biBitCount', ctypes.c_ushort), ('biCompression', ctypes.c_ulong),
        ('biSizeImage', ctypes.c_ulong), ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', ctypes.c_ulong),
        ('biClrImportant', ctypes.c_ulong)
    ]

class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ('rgbBlue', ctypes.c_byte), ('rgbGreen', ctypes.c_byte),
        ('rgbRed', ctypes.c_byte), ('rgbReserved', ctypes.c_byte)
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', RGBQUAD * 1)]


def get_active_windows():
    window_titles = {}
    def enum_windows_proc(hwnd, lParam):
        if not win32gui.IsWindowVisible(hwnd): return True 
        if win32gui.GetWindowTextLength(hwnd) == 0: return True
        title = win32gui.GetWindowText(hwnd)
        if not title or not title.strip(): return True
        try:
            rect = win32gui.GetWindowRect(hwnd)
            if (rect[2] - rect[0]) > 0 and (rect[3] - rect[1]) > 0:
                window_titles[title] = hwnd
        except win32gui.error: pass
        return True
    win32gui.EnumWindows(enum_windows_proc, None)
    return window_titles

def get_window_geometry(hwnd):
    try:
        rect = win32gui.GetClientRect(hwnd) # Используем GetClientRect для размеров клиентской области
        return {"x": rect[0], "y": rect[1], "width": rect[2] - rect[0], "height": rect[3] - rect[1]}
    except win32gui.error:
        return {"x": 0, "y": 0, "width": 0, "height": 0}

def prevent_minimize_loop(hwnd_to_protect, stop_event, logger_func=print):
    logger_func(f"[WindowsUtils] Защита от сворачивания запущена для HWND: {hwnd_to_protect}")
    while not stop_event.is_set():
        try:
            if win32gui.IsWindow(hwnd_to_protect): 
                if win32gui.IsIconic(hwnd_to_protect):
                    logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} свернуто. Восстанавливаем...")
                    win32gui.ShowWindow(hwnd_to_protect, win32con.SW_RESTORE)
                    time.sleep(0.05) # Уменьшим задержку, чтобы быстрее реагировать
            else:
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита остановлена.")
                break 
        except win32gui.error as e: 
            if hasattr(e, 'winerror') and e.winerror == 1400: # Неверный дескриптор окна
                logger_func(f"[WindowsUtils] Ошибка 1400 (неверный дескриптор), окно {hwnd_to_protect} закрыто. Защита остановлена.")
                break 
            else: # Другие ошибки win32, продолжаем, но логируем
                 logger_func(f"[WindowsUtils] Ошибка win32gui в потоке защиты (HWND: {hwnd_to_protect}): {e}")
        except Exception as e_generic: 
            logger_func(f"[WindowsUtils] Неожиданная ошибка в потоке защиты: {e_generic}")
            break 
        time.sleep(0.05) # Проверяем чаще
    logger_func(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")

class WindowFrameGrabberGDI:
    def __init__(self, hwnd, logger_func=print):
        self.hwnd = hwnd
        self.logger = logger_func
        self.width = 0      
        self.height = 0     
        self.original_width_recorded = 0 # Для сравнения при проверке размера
        self.original_height_recorded = 0
        
        self.saveDC_mem = None   
        self.hBitmap_dib = None  
        self.pBitmapBits = ctypes.c_void_p() # Инициализируем здесь, чтобы был всегда доступен
        self.is_initialized = False
        self._initialize_resources_with_retry()

    def _get_current_client_rect_robust(self, max_retries=3, delay=0.1):
        for attempt in range(max_retries):
            if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                self.logger(f"[FrameGrabberGDI] Окно {self.hwnd} не существует (в _get_current_client_rect_robust).")
                return None
            try:
                # Перед GetClientRect убедимся, что окно не свернуто (на всякий случай, хотя prevent_minimize должен это делать)
                if win32gui.IsIconic(self.hwnd):
                    win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                    time.sleep(delay / 2) # Короткая пауза для восстановления

                rect = win32gui.GetClientRect(self.hwnd)
                # Проверяем, что размеры не нулевые
                if (rect[2] - rect[0]) > 0 and (rect[3] - rect[1]) > 0:
                    return rect
                self.logger(f"[FrameGrabberGDI] Попытка {attempt + 1}/{max_retries}: GetClientRect вернул {rect[2]-rect[0]}x{rect[3]-rect[1]}. Ожидание...")
            except win32gui.error as e:
                self.logger(f"[FrameGrabberGDI] Попытка {attempt + 1}/{max_retries}: Ошибка GetClientRect: {e}. Ожидание...")
            
            if attempt < max_retries - 1: # Не спим после последней попытки
                time.sleep(delay)
        self.logger(f"[FrameGrabberGDI] Не удалось получить валидные размеры окна после {max_retries} попыток.")
        return None


    def _initialize_resources_with_retry(self):
        self.release_resources() 

        client_rect = self._get_current_client_rect_robust()
        if client_rect is None:
            self.logger(f"[FrameGrabberGDI] Не удалось получить валидные размеры окна для инициализации HWND {self.hwnd}.")
            self.is_initialized = False; return

        original_width = client_rect[2] - client_rect[0]
        original_height = client_rect[3] - client_rect[1]

        self.width = (original_width // 2) * 2
        self.height = (original_height // 2) * 2
        self.original_width_recorded = original_width
        self.original_height_recorded = original_height


        if self.width <= 0 or self.height <= 0:
            self.logger(f"[FrameGrabberGDI] Неверные размеры после округления для {self.hwnd}: {self.width}x{self.height} (исходные: {original_width}x{original_height})")
            self.is_initialized = False; return
        
        try:
            hScreenDC_raw = win32gui.GetDC(0) 
            if not hScreenDC_raw:
                 self.logger(f"[FrameGrabberGDI] GetDC(0) FAILED. Error: {win32api.GetLastError()}"); return

            self.saveDC_mem = win32gui.CreateCompatibleDC(hScreenDC_raw)
            win32gui.ReleaseDC(0, hScreenDC_raw) # Освобождаем DC экрана сразу
            if not self.saveDC_mem:
                self.logger(f"[FrameGrabberGDI] CreateCompatibleDC FAILED. Error: {win32api.GetLastError()}"); return
            
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self.width 
            bmi.bmiHeader.biHeight = -self.height  
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32 
            bmi.bmiHeader.biCompression = BI_RGB
            
            # self.pBitmapBits уже инициализирован в __init__
            win32api.SetLastError(0)
            self.hBitmap_dib = ctypes.windll.gdi32.CreateDIBSection(
                self.saveDC_mem, ctypes.byref(bmi), DIB_RGB_COLORS, 
                ctypes.byref(self.pBitmapBits), None, 0
            )
            err_dib = win32api.GetLastError()

            if not self.hBitmap_dib:
                self.logger(f"[FrameGrabberGDI] CreateDIBSection ({self.width}x{self.height}, 32bpp) FAILED. Error: {err_dib}")
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None; return
            
            hOldBitmap = win32gui.SelectObject(self.saveDC_mem, self.hBitmap_dib)
            if hOldBitmap == 0 or hOldBitmap is None : # Проверка на None тоже
                self.logger(f"[FrameGrabberGDI] SelectObject(hBitmap_dib) FAILED. Error: {win32api.GetLastError()}")
                ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib); self.hBitmap_dib = None
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None; return
            
            self.is_initialized = True
            self.logger(f"[FrameGrabberGDI] Ресурсы DIBSection инициализированы для {self.hwnd} ({self.width}x{self.height}, исходные: {original_width}x{original_height}).")

        except Exception as e:
            self.logger(f"[FrameGrabberGDI] Исключение при инициализации DIBSection: {e}")
            import traceback; self.logger(traceback.format_exc())
            self.release_resources() # Убедимся, что все очищено при ошибке

    def grab_frame(self):
        if not self.is_initialized or not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Захват невозможен: не инициализирован или окно/HWND невалидны. Попытка переинициализации...")
            self._initialize_resources_with_retry()
            if not self.is_initialized:
                self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Переинициализация не удалась.")
                return None
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Успешно переинициализирован.")

        # Проверка изменения размера клиентской области
        current_client_rect_check = self._get_current_client_rect_robust(max_retries=1, delay=0.01) # Быстрая проверка
        if current_client_rect_check is None:
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] grab_frame: Не удалось получить текущие размеры окна. Граббер деинициализирован.")
            self.is_initialized = False; return None

        original_w_current = current_client_rect_check[2] - current_client_rect_check[0]
        original_h_current = current_client_rect_check[3] - current_client_rect_check[1]

        # Сравниваем оригинальные размеры, а не округленные, чтобы точно отловить изменение
        if original_w_current != self.original_width_recorded or original_h_current != self.original_height_recorded:
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Изменение размера окна ({self.original_width_recorded}x{self.original_height_recorded} -> {original_w_current}x{original_h_current}). Переинициализация...")
            self._initialize_resources_with_retry()
            if not self.is_initialized: 
                self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Переинициализация из-за размера не удалась.")
                return None 
        
        # Дополнительная проверка на случай, если инициализация не удалась, а мы все еще здесь
        if not self.is_initialized or self.width <= 0 or self.height <= 0 or not self.saveDC_mem or not self.hBitmap_dib:
             self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] grab_frame: Состояние граббера невалидно перед PrintWindow.")
             self.is_initialized = False; return None


        flags = 1 # PW_CLIENTONLY
        user32 = ctypes.windll.user32
        win32api.SetLastError(0)
        
        result = user32.PrintWindow(self.hwnd, self.saveDC_mem, flags)
        err_printwindow = win32api.GetLastError()

        if result == 0: 
            self.logger(f"[FrameGrabberGDI] PrintWindow FAILED для HWND {self.hwnd}. Result: {result}, LastError: {err_printwindow}. Граббер деинициализирован.")
            self.is_initialized = False # Считаем это ошибкой, требующей переинициализации
            return None

        try:
            if not self.pBitmapBits or self.pBitmapBits.value is None:
                self.logger("[FrameGrabberGDI] pBitmapBits NULL после PrintWindow (неожиданно).")
                self.is_initialized = False; return None

            buffer_size = self.width * self.height * 4 
            image_bytes = ctypes.string_at(self.pBitmapBits.value, buffer_size)
            img_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((self.height, self.width, 4))
            return cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            
        except Exception as e: 
            self.logger(f"[FrameGrabberGDI] Ошибка при доступе к данным DIBSection: {e}")
            self.is_initialized = False; return None

    def release_resources(self):
        if self.hBitmap_dib:
            try: ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib)
            except: pass 
            self.hBitmap_dib = None
        
        # pBitmapBits сам не освобождается, он указывает на память, управляемую hBitmap_dib
        # Когда hBitmap_dib удален, эта память становится невалидной.
        # Просто сбрасываем указатель.
        if hasattr(self, 'pBitmapBits'): self.pBitmapBits.value = None 

        if self.saveDC_mem:
            try: win32gui.DeleteDC(self.saveDC_mem)
            except: pass
            self.saveDC_mem = None
        
        self.is_initialized = False
        self.width = 0; self.height = 0
        self.original_width_recorded = 0; self.original_height_recorded = 0


    def close(self): self.release_resources(); self.hwnd = None
    def __del__(self): self.release_resources()
