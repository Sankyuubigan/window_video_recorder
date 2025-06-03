import win32gui
import win32ui
import win32con
import win32api 
import numpy as np
import cv2 
import time 
import ctypes # Для PrintWindow

SRCCOPY = 0x00CC0020 
# Флаги для PrintWindow
PW_CLIENTONLY = 1 # Захватывать только клиентскую область

class WindowCapture:
    def __init__(self, hwnd, logger_func=print): 
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise ValueError(f"Invalid window handle (HWND): {hwnd}.")
        
        self.hwnd = hwnd
        self.logger = logger_func
        self.width = 0
        self.height = 0
        self.hwnd_dc = None
        self.mfc_dc = None
        self.save_dc = None
        self.bitmap = None 
        self.is_initialized_properly = False 
        self.capture_method_used = "None" 
        self.use_print_window = False # Флаг для переключения на PrintWindow

        self.logger(f"[WindowCapture HWND:{self.hwnd}] Initializing...")
        self._update_geometry_and_resources() 
        if self.is_initialized_properly:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] Initialized for {self.capture_method_used}. Client size: {self.width}x{self.height}")
        else:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] Initialization FAILED. GDI resources problem. Size (attempted): {self.width}x{self.height}")


    def _release_resources_unsafe(self):
        if self.bitmap is not None:
            if hasattr(self.bitmap, 'GetSafeHandle') and self.bitmap.GetSafeHandle():
                win32gui.DeleteObject(self.bitmap.GetSafeHandle())
            self.bitmap = None
        if self.save_dc is not None:
            if hasattr(self.save_dc, 'GetSafeHdc') and self.save_dc.GetSafeHdc():
                 self.save_dc.DeleteDC()
            self.save_dc = None
        if self.mfc_dc is not None:
            if hasattr(self.mfc_dc, 'GetSafeHdc') and self.mfc_dc.GetSafeHdc():
                 self.mfc_dc.DeleteDC()
            self.mfc_dc = None
        if self.hwnd_dc is not None:
            if self.hwnd and win32gui.IsWindow(self.hwnd): 
                 win32gui.ReleaseDC(self.hwnd, self.hwnd_dc)
            self.hwnd_dc = None
        self.is_initialized_properly = False


    def _update_geometry_and_resources(self):
        self.is_initialized_properly = False 
        self._release_resources_unsafe() 

        # Получаем размеры клиентской области
        try:
            client_rect = win32gui.GetClientRect(self.hwnd)
        except win32ui.error as e:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] GetClientRect failed: {e}. Cannot initialize.")
            self.width = 0; self.height = 0
            return

        temp_width = client_rect[2] - client_rect[0]
        temp_height = client_rect[3] - client_rect[1]
        
        if temp_width <= 0 or temp_height <= 0:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] GetClientRect: {temp_width}x{temp_height} (invalid).")
            # Для PrintWindow тоже нужны валидные размеры, так что если тут 0, то проблема.
            # Можно попробовать GetWindowRect, но PrintWindow обычно нацелен на видимое содержимое.
            self.width = 0; self.height = 0
            return
        
        self.width = temp_width
        self.height = temp_height
        self.logger(f"[WindowCapture HWND:{self.hwnd}] Target dimensions for GDI: {self.width}x{self.height}")

        # --- Попытка инициализации для BitBlt ---
        self.logger(f"[WindowCapture HWND:{self.hwnd}] Attempting GDI init for BitBlt...")
        try:
            self.hwnd_dc = win32gui.GetDC(self.hwnd) 
            if not self.hwnd_dc: raise RuntimeError(f"GetDC failed. Error: {win32api.GetLastError()}")

            self.mfc_dc = win32ui.CreateDCFromHandle(self.hwnd_dc) 
            if not self.mfc_dc: raise RuntimeError(f"CreateDCFromHandle failed. Error: {win32api.GetLastError()}")

            self.save_dc = self.mfc_dc.CreateCompatibleDC() 
            if not self.save_dc: raise RuntimeError(f"CreateCompatibleDC (save_dc) failed. Error: {win32api.GetLastError()}")
            
            current_bitmap_bitblt = win32ui.CreateBitmap() 
            win32api.SetLastError(0)
            # Логируем состояние DC перед вызовом CreateCompatibleBitmap
            self.logger(f"[WindowCapture HWND:{self.hwnd}] BitBlt path: hwnd_dc valid: {self.hwnd_dc != 0}, mfc_dc valid: {self.mfc_dc.GetSafeHdc() != 0}")
            
            bitmap_creation_successful = current_bitmap_bitblt.CreateCompatibleBitmap(self.mfc_dc, self.width, self.height)
            err_createbmp = win32api.GetLastError()

            if not bitmap_creation_successful: 
                raise RuntimeError(f"CreateCompatibleBitmap (BitBlt) FAILED for {self.width}x{self.height}. Python success: {bitmap_creation_successful}, System Error: {err_createbmp}")
            
            if not current_bitmap_bitblt.GetSafeHandle():
                raise RuntimeError(f"CreateCompatibleBitmap (BitBlt) Python success, but GetSafeHandle is NULL. System Error: {err_createbmp}")

            self.bitmap = current_bitmap_bitblt
            if self.save_dc.SelectObject(self.bitmap) == 0:
                raise RuntimeError(f"SelectObject(bitmap for BitBlt) FAILED. Error: {win32api.GetLastError()}")

            self.is_initialized_properly = True
            self.use_print_window = False
            self.capture_method_used = "BitBlt"
            self.logger(f"[WindowCapture HWND:{self.hwnd}] GDI resources for BitBlt created successfully.")
            return # Успешная инициализация для BitBlt

        except RuntimeError as e_bitblt_init:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] BitBlt GDI init failed: {e_bitblt_init}")
            self._release_resources_unsafe() # Очищаем то, что могло быть создано для BitBlt

            # --- Попытка инициализации для PrintWindow, если BitBlt не удался ---
            self.logger(f"[WindowCapture HWND:{self.hwnd}] Attempting GDI init for PrintWindow...")
            try:
                # PrintWindow требует DC окна, которое оно будет рисовать, и DC битмапа, куда рисовать
                # Нам все еще нужен битмап для PrintWindow
                self.hwnd_dc = win32gui.GetDC(self.hwnd) # DC самого окна (источник)
                if not self.hwnd_dc: raise RuntimeError(f"GetDC (for PrintWindow source) failed. Error: {win32api.GetLastError()}")
                
                # Создаем DC для битмапа (цель)
                # Можно использовать mfc_dc, если он уже создан, или создать новый
                # Для чистоты создадим временный mfc_dc, если предыдущий не удался
                temp_mfc_dc_for_bitmap = win32ui.CreateDCFromHandle(self.hwnd_dc) # Используем DC окна как основу
                if not temp_mfc_dc_for_bitmap: raise RuntimeError(f"CreateDCFromHandle (for PrintWindow bitmap DC) failed. Error: {win32api.GetLastError()}")

                self.save_dc = temp_mfc_dc_for_bitmap.CreateCompatibleDC() # Совместимый DC для битмапа
                if not self.save_dc: 
                    temp_mfc_dc_for_bitmap.DeleteDC()
                    raise RuntimeError(f"CreateCompatibleDC (for PrintWindow save_dc) failed. Error: {win32api.GetLastError()}")

                current_bitmap_pw = win32ui.CreateBitmap()
                win32api.SetLastError(0)
                self.logger(f"[WindowCapture HWND:{self.hwnd}] PrintWindow path: hwnd_dc valid: {self.hwnd_dc != 0}, save_dc valid for bitmap: {self.save_dc.GetSafeHdc() != 0}")

                # PrintWindow может работать с DDB (device-dependent bitmap), который создает CreateCompatibleBitmap
                # или DIB (device-independent bitmap). Попробуем с DDB.
                bitmap_creation_pw_successful = current_bitmap_pw.CreateCompatibleBitmap(temp_mfc_dc_for_bitmap, self.width, self.height)
                err_createbmp_pw = win32api.GetLastError()

                if not bitmap_creation_pw_successful:
                    raise RuntimeError(f"CreateCompatibleBitmap (PrintWindow) FAILED for {self.width}x{self.height}. Python success: {bitmap_creation_pw_successful}, System Error: {err_createbmp_pw}")
                
                if not current_bitmap_pw.GetSafeHandle():
                     raise RuntimeError(f"CreateCompatibleBitmap (PrintWindow) Python success, but GetSafeHandle is NULL. System Error: {err_createbmp_pw}")

                self.bitmap = current_bitmap_pw
                if self.save_dc.SelectObject(self.bitmap) == 0:
                    raise RuntimeError(f"SelectObject(bitmap for PrintWindow) FAILED. Error: {win32api.GetLastError()}")
                
                # mfc_dc нам не нужен напрямую для PrintWindow, если мы не делаем BitBlt из него
                # hwnd_dc используется как источник для PrintWindow, save_dc как цель с битмапом
                # Освобождаем временный temp_mfc_dc_for_bitmap, так как он был только для создания битмапа
                temp_mfc_dc_for_bitmap.DeleteDC()

                self.is_initialized_properly = True
                self.use_print_window = True
                self.capture_method_used = "PrintWindow"
                self.logger(f"[WindowCapture HWND:{self.hwnd}] GDI resources for PrintWindow created successfully.")
                # self.mfc_dc остается None, так как он не используется PrintWindow напрямую
                return

            except RuntimeError as e_pw_init:
                self.logger(f"[WindowCapture HWND:{self.hwnd}] PrintWindow GDI init also failed: {e_pw_init}")
                self._release_resources_unsafe() # Очищаем все, если и PrintWindow не удался
                self.width = 0; self.height = 0 # Сбрасываем размеры, чтобы indicate failure
                return # Инициализация полностью провалена


    def grab_frame(self):
        if not self.hwnd or not win32gui.IsWindow(self.hwnd) or not self.is_initialized_properly: 
            # Если не инициализирован, пытаемся обновить ресурсы.
            # Это может быть вызвано, если окно изменило размер и старые ресурсы невалидны,
            # или если первая инициализация не удалась.
            if self.hwnd and win32gui.IsWindow(self.hwnd): # Пробуем обновить только если окно еще есть
                self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: Not initialized or window state changed. Re-initializing...")
                self._update_geometry_and_resources() # Попытка переинициализации
                if not self.is_initialized_properly: # Если и после этого не удалось
                    # self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: Re-initialization failed.")
                    return None
            else: # Окно уже не существует
                return None
        
        if self.width <= 0 or self.height <= 0: # Дополнительная проверка размеров
            # self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: Invalid dimensions {self.width}x{self.height}.")
            return None

        # Проверка изменения размера клиентской области (если BitBlt)
        if not self.use_print_window: # Для BitBlt важно, чтобы размеры совпадали
            try:
                client_rect_current = win32gui.GetClientRect(self.hwnd)
                new_w, new_h = client_rect_current[2]-client_rect_current[0], client_rect_current[3]-client_rect_current[1]
                if new_w != self.width or new_h != self.height:
                    if new_w > 0 and new_h > 0:
                        self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame (BitBlt): Resize detected. Re-initializing.")
                        self._update_geometry_and_resources()
                        if not self.is_initialized_properly: return None
                    else: return None 
            except win32ui.error: return None
        
        # --- Захват ---
        if self.use_print_window:
            # Для PrintWindow нам нужен HDC битмапа (self.save_dc.GetSafeHdc())
            # и флаги (PW_CLIENTONLY).
            # PrintWindow возвращает BOOL (1 для успеха, 0 для неудачи).
            hdc_bitmap = self.save_dc.GetSafeHdc()
            if not hdc_bitmap: 
                self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame (PrintWindow): save_dc HDC is NULL.")
                return None
            
            # ctypes.windll.user32.PrintWindow(hwnd, hdcBitmap, nFlags)
            # nFlags: 0 для всего окна, PW_CLIENTONLY для клиентской области
            print_window_flags = PW_CLIENTONLY 
            # print_window_flags = 0 # Для теста захвата всего окна
            
            win32api.SetLastError(0)
            result = ctypes.windll.user32.PrintWindow(self.hwnd, hdc_bitmap, print_window_flags)
            err_print_window = win32api.GetLastError()

            if result == 0: # PrintWindow не удался
                self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: PrintWindow FAILED (result: {result}). System Error: {err_print_window}")
                # Можно попробовать переинициализировать ресурсы GDI, если PrintWindow перестал работать
                self.is_initialized_properly = False 
                self._release_resources_unsafe()
                return None
            self.capture_method_used = "PrintWindow"
        else: # Используем BitBlt
            if not self.save_dc or not self.mfc_dc: # Проверка на случай, если что-то пошло не так
                 self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame (BitBlt): save_dc or mfc_dc is None.")
                 return None
            try:
                self.save_dc.BitBlt((0, 0), (self.width, self.height), self.mfc_dc, (0, 0), SRCCOPY)
                self.capture_method_used = "BitBlt"
            except win32ui.error as e_bitblt:
                self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: BitBlt error: {e_bitblt}.")
                self.is_initialized_properly = False 
                self._release_resources_unsafe()
                return None 
        
        # --- Получение данных из битмапа ---
        if not self.bitmap or not self.bitmap.GetSafeHandle():
            self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: Bitmap is invalid before GetBitmapBits.")
            return None
        try:
            bmp_str = self.bitmap.GetBitmapBits(True) # True для BGRA
        except win32ui.error as e_bmp_data:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: GetBitmapBits error: {e_bmp_data}")
            return None

        expected_buffer_size = self.width * self.height * 4
        if len(bmp_str) != expected_buffer_size:
            self.logger(f"[WindowCapture HWND:{self.hwnd}] grab_frame: Buffer size mismatch. Expected: {expected_buffer_size}, Got: {len(bmp_str)}. Frame: {self.width}x{self.height}.")
            return None

        img = np.frombuffer(bmp_str, dtype=np.uint8)
        img.shape = (self.height, self.width, 4) # BGRA
        img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img_bgr

    def close(self): 
        self.logger(f"[WindowCapture HWND:{self.hwnd if self.hwnd else 'N/A'}] Close called for instance {id(self)}.")
        self._release_resources_unsafe() 
        self.hwnd = None 
        self.logger(f"[WindowCapture] Instance {id(self)} resources released.")

    def __del__(self):
        if self.hwnd is not None: 
             self.logger(f"[WindowCapture HWND:{self.hwnd}] __del__ for instance {id(self)}. Forcing close.")
             self.close()

if __name__ == '__main__':
    def test_logger_main(message): print(f"TEST_LOG: {message}")
    test_logger_main("Ожидание 5 секунд...")
    time.sleep(5)
    hwnd_main_test = win32gui.GetForegroundWindow() 
    if not hwnd_main_test: test_logger_main("Не удалось найти окно."); exit()
    
    window_text_main_test = win32gui.GetWindowText(hwnd_main_test)
    test_logger_main(f"Захват окна: {window_text_main_test} (HWND: {hwnd_main_test})")
    capturer_main_test = None
    
    try:
        capturer_main_test = WindowCapture(hwnd_main_test, logger_func=test_logger_main)
    except Exception as e:
        test_logger_main(f"КРИТИЧЕСКАЯ ОШИБКА ИНИЦИАЛИЗАЦИИ WindowCapture: {e}")
        import traceback; traceback.print_exc(); exit(1)

    if not capturer_main_test.is_initialized_properly:
         test_logger_main(f"WindowCapture не смог корректно инициализировать GDI ресурсы для окна '{window_text_main_test}'. Метод: {capturer_main_test.capture_method_used}")
         test_logger_main("Захват кадров будет невозможен или нестабилен. Проверьте логи на ошибки.")
    elif capturer_main_test.width <= 0 or capturer_main_test.height <= 0:
        test_logger_main(f"Ошибка: Размеры окна ({capturer_main_test.width}x{capturer_main_test.height}) невалидны после инициализации.")
        exit(1)
    else:
        test_logger_main(f"Начальные размеры захвата: {capturer_main_test.width}x{capturer_main_test.height}, метод: {capturer_main_test.capture_method_used}")
        
    frame_count_main_test = 0; start_time_main_test = time.time(); loop_active_main_test = True
    while loop_active_main_test:
        if not win32gui.IsWindow(hwnd_main_test): 
            test_logger_main("Окно было закрыто."); loop_active_main_test = False; break
        
        frame_main_test = None
        try: frame_main_test = capturer_main_test.grab_frame() 
        except Exception as e_grab: 
            test_logger_main(f"НЕПРЕДВИДЕННАЯ ОШИБКА в grab_frame: {e_grab}"); import traceback; traceback.print_exc(); loop_active_main_test = False; break

        if frame_main_test is not None:
            frame_count_main_test +=1
            if frame_main_test.size > 0: cv2.imshow(f"Window Capture (method: {capturer_main_test.capture_method_used}) - Press 'q' to quit", frame_main_test)
        else:
            if not capturer_main_test.is_initialized_properly: # Если постоянно не инициализировано, даем паузу
                test_logger_main(f"grab_frame: GDI не инициализирован ({capturer_main_test.capture_method_used}), кадр не получен. Ожидание...")
                time.sleep(0.5) 

        key_main_test = cv2.waitKey(1) 
        if key_main_test == ord('q'): loop_active_main_test = False; break
        if key_main_test == ord('r'): 
            test_logger_main("Переинициализация захвата (нажата 'r')...")
            try: 
                capturer_main_test._update_geometry_and_resources()
                if capturer_main_test.is_initialized_properly: test_logger_main(f"Новые размеры: {capturer_main_test.width}x{capturer_main_test.height}, метод: {capturer_main_test.capture_method_used}")
                else: test_logger_main(f"Переинициализация по 'r' НЕ УДАЛАСЬ. Метод: {capturer_main_test.capture_method_used}")
            except Exception as e_reinit_main_test: test_logger_main(f"Ошибка переинициализации по 'r': {e_reinit_main_test}")

    end_time_main_test = time.time(); duration_main_test = end_time_main_test - start_time_main_test
    if duration_main_test > 0 and frame_count_main_test > 0 : 
        test_logger_main(f"Захвачено {frame_count_main_test} кадров за {duration_main_test:.2f} сек, FPS: {frame_count_main_test/duration_main_test:.2f}")
    elif frame_count_main_test == 0: 
        test_logger_main("Не было захвачено ни одного кадра.")
        if not capturer_main_test.is_initialized_properly: test_logger_main(f"Причина: WindowCapture не смог инициализировать GDI для '{window_text_main_test}' методом {capturer_main_test.capture_method_used}.")

    cv2.destroyAllWindows()
    if capturer_main_test: 
        try: capturer_main_test.close()
        except Exception as e_close: test_logger_main(f"Ошибка при capturer_main_test.close(): {e_close}")
    test_logger_main("Тест завершен.")
