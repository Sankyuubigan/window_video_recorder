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
    # ... (без изменений) ...
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

def get_window_client_rect(hwnd):
    # ... (без изменений) ...
    try:
        rect = win32gui.GetClientRect(hwnd) 
        return {"x": rect[0], "y": rect[1], "width": rect[2] - rect[0], "height": rect[3] - rect[1]}
    except win32gui.error:
        return {"x": 0, "y": 0, "width": 0, "height": 0}

def get_window_rect(hwnd):
    # ... (без изменений) ...
    try:
        return win32gui.GetWindowRect(hwnd)
    except win32gui.error:
        return (0, 0, 0, 0)


def prevent_minimize_loop(hwnd_to_protect, stop_event, logger_func=print):
    # ... (без изменений) ...
    logger_func(f"[WindowsUtils] Защита от сворачивания запущена для HWND: {hwnd_to_protect}")
    while not stop_event.is_set():
        try:
            if not win32gui.IsWindow(hwnd_to_protect):
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита от сворачивания остановлена.")
                break 
            if win32gui.IsIconic(hwnd_to_protect):
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} свернуто. Восстанавливаем...")
                win32gui.ShowWindow(hwnd_to_protect, win32con.SW_RESTORE)
                time.sleep(0.05) 
        except win32gui.error as e: 
            if hasattr(e, 'winerror') and e.winerror == 1400: 
                logger_func(f"[WindowsUtils] Ошибка 1400 (неверный дескриптор), окно {hwnd_to_protect} закрыто. Защита от сворачивания остановлена.")
                break 
            else: 
                 logger_func(f"[WindowsUtils] Ошибка win32gui в потоке защиты от сворачивания (HWND: {hwnd_to_protect}): {e}")
        except Exception as e_generic: 
            logger_func(f"[WindowsUtils] Неожиданная ошибка в потоке защиты от сворачивания: {e_generic}")
            break 
        time.sleep(0.05) 
    logger_func(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")


def prevent_resize_loop(hwnd_to_protect, initial_window_rect, stop_event, logger_func=print):
    # ... (без изменений) ...
    logger_func(f"[WindowsUtils] Защита от изменения размера запущена для HWND: {hwnd_to_protect}, целевой RECT: {initial_window_rect}")
    target_w = initial_window_rect[2] - initial_window_rect[0]
    target_h = initial_window_rect[3] - initial_window_rect[1]
    if target_w <= 0 or target_h <= 0 :
        logger_func(f"[WindowsUtils] ВНИМАНИЕ: Целевые размеры для защиты от изменения размера невалидны ({target_w}x{target_h}). Поток не будет запущен.")
        return

    while not stop_event.is_set():
        try:
            if not win32gui.IsWindow(hwnd_to_protect):
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита от изменения размера остановлена.")
                break
            
            current_rect = win32gui.GetWindowRect(hwnd_to_protect)
            current_w = current_rect[2] - current_rect[0]
            current_h = current_rect[3] - current_rect[1]

            if current_w != target_w or current_h != target_h or \
               current_rect[0] != initial_window_rect[0] or current_rect[1] != initial_window_rect[1]:
                if not win32gui.IsIconic(hwnd_to_protect): # Не трогаем свернутые окна здесь
                    logger_func(f"[WindowsUtils] Обнаружено изменение геометрии окна {hwnd_to_protect}: "
                                f"Pos:({current_rect[0]},{current_rect[1]})->({initial_window_rect[0]},{initial_window_rect[1]}), "
                                f"Size:({current_w}x{current_h})->({target_w}x{target_h}). Восстановление...")
                    win32gui.MoveWindow(hwnd_to_protect, 
                                        initial_window_rect[0], initial_window_rect[1], 
                                        target_w, target_h, True)                    
                    time.sleep(0.05) 
        except win32gui.error as e:
            if hasattr(e, 'winerror') and e.winerror == 1400:
                logger_func(f"[WindowsUtils] Ошибка 1400 (неверный дескриптор) в защите от изменения размера, окно {hwnd_to_protect} закрыто.")
                break
            else:
                logger_func(f"[WindowsUtils] Ошибка win32gui в потоке защиты от изменения размера (HWND: {hwnd_to_protect}): {e}")
        except Exception as e_generic:
            logger_func(f"[WindowsUtils] Неожиданная ошибка в потоке защиты от изменения размера: {e_generic}")
            break
        time.sleep(0.1) 
    logger_func(f"[WindowsUtils] Защита от изменения размера для HWND {hwnd_to_protect} остановлена.")


class WindowFrameGrabberGDI:
    def __init__(self, hwnd, logger_func=print):
        self.hwnd = hwnd
        self.logger = logger_func
        # Эти размеры (target_*) будут установлены при первой успешной инициализации
        # и будут использоваться для всех последующих операций DIBSection и захвата.
        self.target_dib_width = 0      
        self.target_dib_height = 0     
        # Эти размеры хранят исходные клиентские размеры, с которыми граббер был успешно инициализирован.
        # Они используются для проверки, не изменился ли размер окна настолько, что требуется вмешательство.
        self.expected_client_width = 0 
        self.expected_client_height = 0
        
        self.saveDC_mem = None   
        self.hBitmap_dib = None  
        self.pBitmapBits = ctypes.c_void_p() 
        self.is_initialized = False
        self._initialize_resources() # Первоначальная инициализация

    def _get_current_client_rect_robust(self, max_retries=3, delay=0.05):
        # ... (логика получения клиентских размеров, как была, но возможно уменьшить delay)
        for attempt in range(max_retries):
            if not self.hwnd or not win32gui.IsWindow(self.hwnd):
                self.logger(f"[FrameGrabberGDI] Окно {self.hwnd} не существует (в _get_current_client_rect_robust).")
                return None
            try:
                if win32gui.IsIconic(self.hwnd):
                    self.logger(f"[FrameGrabberGDI] Попытка {attempt + 1}/{max_retries}: Окно свернуто.")
                    # Не ждем здесь, пусть prevent_minimize_loop разбирается. Если оно свернуто, размеры будут 0.
                
                rect = win32gui.GetClientRect(self.hwnd)
                current_w = rect[2] - rect[0]
                current_h = rect[3] - rect[1]

                if current_w > 0 and current_h > 0:
                    return rect # Возвращаем (left, top, right, bottom) клиентской области
                # self.logger(f"[FrameGrabberGDI] Попытка {attempt + 1}/{max_retries}: GetClientRect вернул {current_w}x{current_h}.")
            except win32gui.error as e:
                self.logger(f"[FrameGrabberGDI] Попытка {attempt + 1}/{max_retries}: Ошибка GetClientRect: {e}.")
            
            if attempt < max_retries - 1: 
                time.sleep(delay)
        self.logger(f"[FrameGrabberGDI] Не удалось получить валидные клиентские размеры окна HWND {self.hwnd} после {max_retries} попыток.")
        return None

    def _initialize_resources(self):
        self.release_resources() # Очищаем старые ресурсы перед новой инициализацией

        client_rect = self._get_current_client_rect_robust()
        if client_rect is None:
            self.logger(f"[FrameGrabberGDI] Инициализация не удалась: не получены валидные размеры клиентской области для HWND {self.hwnd}.")
            self.is_initialized = False; return

        # Запоминаем ожидаемые клиентские размеры, с которыми мы инициализируемся
        self.expected_client_width = client_rect[2] - client_rect[0]
        self.expected_client_height = client_rect[3] - client_rect[1]

        # Размеры для DIBSection (округленные)
        self.target_dib_width = (self.expected_client_width // 2) * 2
        self.target_dib_height = (self.expected_client_height // 2) * 2

        if self.target_dib_width <= 0 or self.target_dib_height <= 0:
            self.logger(f"[FrameGrabberGDI] Неверные размеры для DIBSection ({self.target_dib_width}x{self.target_dib_height}) "
                        f"для HWND {self.hwnd} (исходные клиентские: {self.expected_client_width}x{self.expected_client_height})")
            self.is_initialized = False; return
        
        try:
            hScreenDC_raw = win32gui.GetDC(0) 
            if not hScreenDC_raw:
                 self.logger(f"[FrameGrabberGDI] GetDC(0) FAILED. Error: {win32api.GetLastError()}"); return

            self.saveDC_mem = win32gui.CreateCompatibleDC(hScreenDC_raw)
            win32gui.ReleaseDC(0, hScreenDC_raw) 
            if not self.saveDC_mem:
                self.logger(f"[FrameGrabberGDI] CreateCompatibleDC FAILED. Error: {win32api.GetLastError()}"); return
            
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self.target_dib_width 
            bmi.bmiHeader.biHeight = -self.target_dib_height  
            bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32; bmi.bmiHeader.biCompression = BI_RGB
            
            win32api.SetLastError(0)
            self.hBitmap_dib = ctypes.windll.gdi32.CreateDIBSection(
                self.saveDC_mem, ctypes.byref(bmi), DIB_RGB_COLORS, 
                ctypes.byref(self.pBitmapBits), None, 0)
            err_dib = win32api.GetLastError()

            if not self.hBitmap_dib:
                self.logger(f"[FrameGrabberGDI] CreateDIBSection FAILED (Error: {err_dib}) для {self.target_dib_width}x{self.target_dib_height}.")
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None; return
            
            hOldBitmap = win32gui.SelectObject(self.saveDC_mem, self.hBitmap_dib)
            if hOldBitmap == 0 or hOldBitmap is None : 
                self.logger(f"[FrameGrabberGDI] SelectObject(hBitmap_dib) FAILED. Error: {win32api.GetLastError()}")
                ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib); self.hBitmap_dib = None
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None; return
            
            self.is_initialized = True
            self.logger(f"[FrameGrabberGDI] Ресурсы DIBSection инициализированы для HWND {self.hwnd} "
                        f"(DIB: {self.target_dib_width}x{self.target_dib_height}, "
                        f"ожидаемые клиентские: {self.expected_client_width}x{self.expected_client_height}).")

        except Exception as e:
            self.logger(f"[FrameGrabberGDI] Исключение при инициализации DIBSection: {e}")
            import traceback; self.logger(traceback.format_exc())
            self.release_resources() 

    def grab_frame(self):
        if not self.is_initialized:
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] grab_frame вызван, но граббер не инициализирован. Попытка инициализации...")
            self._initialize_resources() # Попытка однократной инициализации, если не был инициализирован
            if not self.is_initialized:
                self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Инициализация в grab_frame не удалась.")
                return None # Не удалось инициализироваться

        # Проверяем, существует ли еще окно
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] Окно больше не существует. Деинициализация.")
            self.release_resources(); return None

        # Проверяем, не изменились ли КЛИЕНТСКИЕ размеры окна значительно
        # (т.е. не то, что мы ожидаем для DIB, а реальные размеры окна)
        current_client_rect = self._get_current_client_rect_robust(max_retries=1, delay=0.01)
        if current_client_rect is None:
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] grab_frame: не удалось получить текущие клиентские размеры. Пропуск кадра.")
            # Не сбрасываем is_initialized здесь, даем шанс prevent_resize восстановить
            return None 
            
        current_client_w = current_client_rect[2] - current_client_rect[0]
        current_client_h = current_client_rect[3] - current_client_rect[1]

        if current_client_w != self.expected_client_width or current_client_h != self.expected_client_height:
            self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] ВНИМАНИЕ: Клиентские размеры окна ({current_client_w}x{current_client_h}) "
                        f"отличаются от ожидаемых ({self.expected_client_width}x{self.expected_client_height}). "
                        f"Ожидается, что prevent_resize_loop восстановит их. Захват с целевыми DIB размерами ({self.target_dib_width}x{self.target_dib_height}).")
            # Не переинициализируем ресурсы здесь. Продолжаем использовать self.target_dib_width/height.
            # PrintWindow будет рисовать клиентскую область окна на наш DIBSection фиксированного размера.
            # Если окно стало меньше, часть DIB будет пустой. Если больше - часть окна не влезет.
            # prevent_resize_loop должен исправить это.

        # Валидация состояния перед PrintWindow
        if not self.saveDC_mem or not self.hBitmap_dib or not self.pBitmapBits:
             self.logger(f"[FrameGrabberGDI HWND:{self.hwnd}] grab_frame: Состояние граббера невалидно перед PrintWindow (DC/Bitmap/Bits is None).")
             self.release_resources(); return None # Критическая ошибка, нужна полная переинициализация

        flags = 1 
        user32 = ctypes.windll.user32
        win32api.SetLastError(0)
        
        result = user32.PrintWindow(self.hwnd, self.saveDC_mem, flags)
        err_printwindow = win32api.GetLastError()

        if result == 0: 
            self.logger(f"[FrameGrabberGDI] PrintWindow FAILED для HWND {self.hwnd}. Result: {result}, LastError: {err_printwindow}.")
            # Если PrintWindow не удался, возможно, окно в плохом состоянии.
            # Не сбрасываем is_initialized сразу, даем шанс восстановиться.
            return None

        try:
            if self.pBitmapBits.value is None: # Проверяем, что указатель на данные валиден
                self.logger("[FrameGrabberGDI] pBitmapBits.value is NULL после PrintWindow.")
                return None

            buffer_size = self.target_dib_width * self.target_dib_height * 4 
            image_bytes = ctypes.string_at(self.pBitmapBits.value, buffer_size)
            img_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((self.target_dib_height, self.target_dib_width, 4))
            
            # Обрезаем до фактических ожидаемых клиентских размеров, если они меньше DIB
            # Это на случай, если округление target_dib_width/height было в большую сторону.
            final_frame = img_bgra[:self.expected_client_height, :self.expected_client_width, :]
            
            return cv2.cvtColor(final_frame, cv2.COLOR_BGRA2BGR)
            
        except Exception as e: 
            self.logger(f"[FrameGrabberGDI] Ошибка при доступе/конвертации данных DIBSection: {e}")
            return None

    def release_resources(self):
        if self.hBitmap_dib:
            try: ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib)
            except: pass 
            self.hBitmap_dib = None
        if hasattr(self, 'pBitmapBits') and self.pBitmapBits: self.pBitmapBits.value = None 
        if self.saveDC_mem:
            try: win32gui.DeleteDC(self.saveDC_mem)
            except: pass
            self.saveDC_mem = None
        self.is_initialized = False
        self.target_dib_width = 0; self.target_dib_height = 0
        self.expected_client_width = 0; self.expected_client_height = 0

    def close(self): self.release_resources(); self.hwnd = None
    def __del__(self): self.release_resources()
