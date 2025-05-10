import win32gui
import win32ui
import win32con
import win32api
import numpy as np
import cv2 
import ctypes
import time # Для тестирования в __main__

SRCCOPY = 0x00CC0020 
PW_CLIENTONLY = 0x00000001

class WindowCapture:
    def __init__(self, hwnd):
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise ValueError(f"Invalid window handle (HWND): {hwnd}.")
        
        self.hwnd = hwnd
        self.width = 0
        self.height = 0
        self.hwnd_dc = None
        self.mfc_dc = None
        self.save_dc = None
        self.bitmap = None
        self.capture_method_used = "None" 
        
        # print(f"[WindowCapture HWND:{self.hwnd}] Initializing...") # Убрал для краткости логов
        try:
            self._update_geometry_and_resources()
            # print(f"[WindowCapture HWND:{self.hwnd}] Initialized with size: {self.width}x{self.height}")
        except Exception as e:
            print(f"[WindowCapture HWND:{self.hwnd}] Critical error during __init__: {e}")
            self._release_resources()
            raise 

    def _update_geometry_and_resources(self):
        self._release_resources()
        try:
            rect = win32gui.GetClientRect(self.hwnd)
        except win32ui.error as e:
            raise RuntimeError(f"GetClientRect failed for HWND {self.hwnd}: {e}")

        self.width = rect[2] - rect[0]
        self.height = rect[3] - rect[1]

        if self.width <= 0 or self.height <= 0:
            try:
                rect_win = win32gui.GetWindowRect(self.hwnd)
                self.width = rect_win[2] - rect_win[0]
                self.height = rect_win[3] - rect_win[1]
                # print(f"[WindowCapture HWND:{self.hwnd}] Using GetWindowRect dimensions: {self.width}x{self.height}")
            except win32ui.error as e:
                 raise RuntimeError(f"GetWindowRect failed for HWND {self.hwnd}: {e}")
            
            if self.width <= 0 or self.height <= 0:
                raise ValueError(f"Window HWND {self.hwnd} has zero/negative dimensions: {self.width}x{self.height}")
        
        try:
            # self.hwnd_dc = win32gui.GetWindowDC(self.hwnd) # DC всего окна
            self.hwnd_dc = win32gui.GetDC(self.hwnd) # DC клиентской области - это должно быть правильнее для BitBlt
        except win32ui.error as e:
            raise RuntimeError(f"GetDC failed for HWND {self.hwnd}: {e}")
        
        if not self.hwnd_dc:
             raise RuntimeError(f"GetDC returned null for HWND {self.hwnd}.")

        try:
            self.mfc_dc = win32ui.CreateDCFromHandle(self.hwnd_dc)
        except win32ui.error as e:
            win32gui.ReleaseDC(self.hwnd, self.hwnd_dc); self.hwnd_dc = None
            raise RuntimeError(f"CreateDCFromHandle failed for HWND {self.hwnd}: {e}")

        try:
            self.save_dc = self.mfc_dc.CreateCompatibleDC()
        except win32ui.error as e:
            self.mfc_dc.DeleteDC(); self.mfc_dc = None
            win32gui.ReleaseDC(self.hwnd, self.hwnd_dc); self.hwnd_dc = None
            raise RuntimeError(f"CreateCompatibleDC failed for HWND {self.hwnd}: {e}")

        try:
            self.bitmap = win32ui.CreateBitmap()
            self.bitmap.CreateCompatibleBitmap(self.mfc_dc, self.width, self.height)
        except win32ui.error as e:
            self.save_dc.DeleteDC(); self.save_dc = None
            self.mfc_dc.DeleteDC(); self.mfc_dc = None
            win32gui.ReleaseDC(self.hwnd, self.hwnd_dc); self.hwnd_dc = None
            raise RuntimeError(f"CreateCompatibleBitmap failed for HWND {self.hwnd} ({self.width}x{self.height}): {e}")
        
        self.save_dc.SelectObject(self.bitmap)

    def grab_frame(self):
        if not self.hwnd or not win32gui.IsWindow(self.hwnd): return None
        if self.width <= 0 or self.height <= 0:
            try:
                self._update_geometry_and_resources()
                if self.width <= 0 or self.height <= 0: return None
            except Exception: return None
        
        try:
            current_rect = win32gui.GetClientRect(self.hwnd)
            new_width, new_height = current_rect[2] - current_rect[0], current_rect[3] - current_rect[1]
            if new_width != self.width or new_height != self.height:
                if new_width > 0 and new_height > 0: self._update_geometry_and_resources()
                else: return None
            
            # Используем BitBlt из клиентского DC (self.mfc_dc) в наш save_dc
            self.save_dc.BitBlt((0, 0), (self.width, self.height), self.mfc_dc, (0, 0), win32con.SRCCOPY)
            self.capture_method_used = "BitBlt_ClientDC"
            
            bmp_info = self.bitmap.GetInfo()
            bmp_str = self.bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmp_str, dtype=np.uint8)
            img.shape = (bmp_info['bmHeight'], bmp_info['bmWidth'], 4)
            img_cropped = img[0:self.height, 0:self.width]
            img_bgr = cv2.cvtColor(img_cropped, cv2.COLOR_BGRA2BGR)
            return img_bgr
        except win32ui.error: return None
        except Exception: return None

    def _release_resources(self):
        if self.bitmap is not None:
            try: win32gui.DeleteObject(self.bitmap.GetHandle())
            except (win32ui.error, AttributeError): pass 
            self.bitmap = None
        if self.save_dc is not None:
            try: self.save_dc.DeleteDC()
            except (win32ui.error, AttributeError): pass
            self.save_dc = None
        if self.mfc_dc is not None:
            try: self.mfc_dc.DeleteDC()
            except (win32ui.error, AttributeError): pass
            self.mfc_dc = None
        if self.hwnd_dc is not None: # hwnd_dc получен из GetDC, его нужно освобождать через ReleaseDC
            try: win32gui.ReleaseDC(self.hwnd, self.hwnd_dc)
            except (win32ui.error, AttributeError, NameError): pass # NameError если self.hwnd уже None
            self.hwnd_dc = None

    def close(self): 
        # print(f"[WindowCapture HWND:{self.hwnd}] Close called.")
        self._release_resources()
        self.hwnd = None # Помечаем, что объект больше не валиден

    def __del__(self):
        self.close() # Используем метод close для очистки

if __name__ == '__main__':
    print("Ожидание 5 секунд, чтобы вы могли выбрать окно...")
    time.sleep(5)
    hwnd = win32gui.GetForegroundWindow() 
    if not hwnd: print("Не удалось найти окно."); exit()
    
    window_text = win32gui.GetWindowText(hwnd)
    print(f"Захват окна: {window_text} (HWND: {hwnd})")
    capturer = None
    try:
        capturer = WindowCapture(hwnd)
        print(f"Начальные размеры захвата: {capturer.width}x{capturer.height}")
        if capturer.width == 0 or capturer.height == 0: print("Ошибка: Начальные размеры нулевые."); exit()
        
        frame_count = 0
        start_time = time.time()
        
        while True:
            if not win32gui.IsWindow(hwnd): print("Окно было закрыто."); break
            frame = capturer.grab_frame()
            if frame is not None:
                frame_count +=1
                cv2.imshow(f"Window Capture (method: {capturer.capture_method_used}) - Press 'q' to quit", frame)
            # else:
                # print("Не удалось захватить кадр (grab_frame вернул None).")
            
            key = cv2.waitKey(1) # Задержка в 1 мс, чтобы окно успевало обновляться
            if key == ord('q'): break 
            if key == ord('r'): # Попытка переинициализации по 'r'
                print("Переинициализация захвата...")
                try:
                    capturer._update_geometry_and_resources()
                    print(f"Новые размеры: {capturer.width}x{capturer.height}")
                except Exception as e_reinit:
                    print(f"Ошибка переинициализации: {e_reinit}")


        end_time = time.time()
        duration = end_time - start_time
        if duration > 0 and frame_count > 0 : 
            print(f"Захвачено {frame_count} кадров за {duration:.2f} сек, FPS: {frame_count/duration:.2f}")
        elif frame_count == 0:
            print("Не было захвачено ни одного кадра.")

        cv2.destroyAllWindows()
    except Exception as e: 
        print(f"Произошла ошибка в __main__: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if capturer: capturer.close()