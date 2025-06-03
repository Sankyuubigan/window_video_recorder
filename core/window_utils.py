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

def get_window_geometry(hwnd):
    # ... (без изменений) ...
    try:
        rect = win32gui.GetClientRect(hwnd)
        return {"x": rect[0], "y": rect[1], "width": rect[2] - rect[0], "height": rect[3] - rect[1]}
    except win32gui.error:
        return {"x": 0, "y": 0, "width": 0, "height": 0}

def prevent_minimize_loop(hwnd_to_protect, stop_event, logger_func=print):
    # ... (без изменений) ...
    logger_func(f"[WindowsUtils] Защита от сворачивания запущена для HWND: {hwnd_to_protect}")
    while not stop_event.is_set():
        try:
            if win32gui.IsWindow(hwnd_to_protect): 
                if win32gui.IsIconic(hwnd_to_protect):
                    logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} свернуто. Восстанавливаем...")
                    win32gui.ShowWindow(hwnd_to_protect, win32con.SW_RESTORE)
                    time.sleep(0.1) 
            else:
                logger_func(f"[WindowsUtils] Окно {hwnd_to_protect} больше не существует. Защита остановлена.")
                break 
        except win32gui.error as e: 
            if hasattr(e, 'winerror') and e.winerror == 1400: break 
        except Exception: break 
        time.sleep(0.1)
    logger_func(f"[WindowsUtils] Защита от сворачивания для HWND {hwnd_to_protect} остановлена.")

class WindowFrameGrabberGDI:
    def __init__(self, hwnd, logger_func=print):
        self.hwnd = hwnd
        self.logger = logger_func
        self.width = 0      # Будет хранить округленную ширину
        self.height = 0     # Будет хранить округленную высоту
        
        self.saveDC_mem = None   
        self.hBitmap_dib = None  
        self.pBitmapBits = None  
        self.is_initialized = False
        self._initialize_resources()

    def _initialize_resources(self):
        self.release_resources() 

        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            self.logger(f"[FrameGrabberGDI] Окно {self.hwnd} не существует.")
            return

        try:
            client_rect = win32gui.GetClientRect(self.hwnd)
            # Получаем оригинальные размеры
            original_width = client_rect[2] - client_rect[0]
            original_height = client_rect[3] - client_rect[1]

            # Округляем до ближайшего четного числа ВНИЗ для ffmpeg (особенно для yuv420p)
            self.width = (original_width // 2) * 2
            self.height = (original_height // 2) * 2

            if self.width <= 0 or self.height <= 0:
                self.logger(f"[FrameGrabberGDI] Неверные размеры после округления для {self.hwnd}: {self.width}x{self.height} (исходные: {original_width}x{original_height})")
                return
            
            hScreenDC_raw = win32gui.GetDC(0) 
            if not hScreenDC_raw:
                 self.logger(f"[FrameGrabberGDI] GetDC(0) FAILED. Error: {win32api.GetLastError()}")
                 return

            self.saveDC_mem = win32gui.CreateCompatibleDC(hScreenDC_raw)
            if not self.saveDC_mem:
                self.logger(f"[FrameGrabberGDI] CreateCompatibleDC(hScreenDC_raw) FAILED. Error: {win32api.GetLastError()}")
                win32gui.ReleaseDC(0, hScreenDC_raw)
                return
            
            win32gui.ReleaseDC(0, hScreenDC_raw)

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self.width # Используем округленные размеры
            bmi.bmiHeader.biHeight = -self.height  # Отрицательная высота для top-down DIB (используем округленные)
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32 
            bmi.bmiHeader.biCompression = BI_RGB
            
            self.pBitmapBits = ctypes.c_void_p() 
            win32api.SetLastError(0)
            self.hBitmap_dib = ctypes.windll.gdi32.CreateDIBSection(
                self.saveDC_mem, ctypes.byref(bmi), DIB_RGB_COLORS, 
                ctypes.byref(self.pBitmapBits), None, 0
            )
            err_dib = win32api.GetLastError()

            if not self.hBitmap_dib:
                self.logger(f"[FrameGrabberGDI] CreateDIBSection ({self.width}x{self.height}, 32bpp) FAILED. Error: {err_dib}")
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None
                return
            
            hOldBitmap = win32gui.SelectObject(self.saveDC_mem, self.hBitmap_dib)
            if hOldBitmap == 0: 
                self.logger(f"[FrameGrabberGDI] SelectObject(hBitmap_dib) FAILED. Error: {win32api.GetLastError()}")
                ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib); self.hBitmap_dib = None
                win32gui.DeleteDC(self.saveDC_mem); self.saveDC_mem = None
                return
            
            self.is_initialized = True
            self.logger(f"[FrameGrabberGDI] Ресурсы DIBSection инициализированы для {self.hwnd} ({self.width}x{self.height}, исходные: {original_width}x{original_height}).")

        except Exception as e:
            self.logger(f"[FrameGrabberGDI] Исключение при инициализации DIBSection: {e}")
            import traceback; self.logger(traceback.format_exc())
            self.release_resources()

    def grab_frame(self):
        if not self.is_initialized or not self.hwnd or not win32gui.IsWindow(self.hwnd):
            # self.logger("[FrameGrabberGDI] Захват невозможен: не инициализирован или окно/HWND невалидны. Попытка переинициализации...")
            # Не будем пытаться переинициализировать здесь, чтобы избежать рекурсии или частых пересозданий.
            # Переинициализация должна происходить на более высоком уровне или при явном изменении размера.
            return None

        # Проверка изменения размера клиентской области
        try:
            current_client_rect = win32gui.GetClientRect(self.hwnd)
            original_w = current_client_rect[2] - current_client_rect[0]
            original_h = current_client_rect[3] - current_client_rect[1]
            # Сравниваем округленные текущие размеры с сохраненными округленными
            current_w_rounded = (original_w // 2) * 2
            current_h_rounded = (original_h // 2) * 2

            if current_w_rounded != self.width or current_h_rounded != self.height:
                if current_w_rounded > 0 and current_h_rounded > 0:
                    self.logger(f"[FrameGrabberGDI] Изменение размера ({self.width}x{self.height} -> {current_w_rounded}x{current_h_rounded}). Переинициализация...")
                    self._initialize_resources() # Это создаст новый битмап нужного (округленного) размера
                    if not self.is_initialized: return None # Если переинициализация не удалась
                    # После переинициализации self.width и self.height будут обновлены
                else: # Новый размер невалиден
                    self.logger(f"[FrameGrabberGDI] Новый размер окна невалиден после округления: {current_w_rounded}x{current_h_rounded}")
                    self.is_initialized = False; return None # Сбрасываем флаг
        except win32gui.error: # Окно могло исчезнуть
             self.logger("[FrameGrabberGDI] Ошибка GetClientRect при проверке размера.")
             self.is_initialized = False; return None


        flags = 1 # PW_CLIENTONLY
        user32 = ctypes.windll.user32
        win32api.SetLastError(0)
        
        hDC_to_draw_on = self.saveDC_mem
        if not hDC_to_draw_on: return None # Уже должно быть проверено при инициализации

        result = user32.PrintWindow(self.hwnd, hDC_to_draw_on, flags)
        err = win32api.GetLastError()

        if result == 0: 
            self.logger(f"[FrameGrabberGDI] PrintWindow FAILED для HWND {self.hwnd}. Result: {result}, LastError: {err}")
            return None

        try:
            if not self.pBitmapBits or self.pBitmapBits.value is None:
                self.logger("[FrameGrabberGDI] pBitmapBits NULL.")
                return None

            buffer_size = self.width * self.height * 4 # Используем сохраненные округленные размеры
            image_bytes = ctypes.string_at(self.pBitmapBits.value, buffer_size)
            img_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((self.height, self.width, 4))
            
            return cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            
        except Exception as e: 
            self.logger(f"[FrameGrabberGDI] Ошибка при доступе к данным DIBSection: {e}")
            return None

    def release_resources(self):
        # ... (без изменений) ...
        if self.hBitmap_dib:
            try: ctypes.windll.gdi32.DeleteObject(self.hBitmap_dib)
            except: pass 
            self.hBitmap_dib = None; self.pBitmapBits = None 
        if self.saveDC_mem:
            try: win32gui.DeleteDC(self.saveDC_mem)
            except: pass
            self.saveDC_mem = None
        self.is_initialized = False

    def close(self): self.release_resources(); self.hwnd = None
    def __del__(self): self.release_resources()
