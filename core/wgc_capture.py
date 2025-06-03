import ctypes
from ctypes import wintypes
import time
import numpy as np 
import sys 

WGC_SUPPORT_AVAILABLE = False
wf = None
wgc = None
wgdx = None
d3d11_winrt = None
ms_ui = None 

if sys.platform == "win32":
    try:
        import winsdk.windows.foundation as wf_import
        import winsdk.windows.graphics.capture as wgc_import
        import winsdk.windows.graphics.directx as wgdx_import
        import winsdk.windows.graphics.directx.direct3d11 as d3d11_winrt_import
        import winsdk.microsoft.ui as ms_ui_import 

        wf = wf_import
        wgc = wgc_import
        wgdx = wgdx_import
        d3d11_winrt = d3d11_winrt_import
        ms_ui = ms_ui_import
        WGC_SUPPORT_AVAILABLE = True
        print("[wgc_capture] Модули winsdk для WGC успешно импортированы.")
    except ImportError as e:
        print(f"[wgc_capture] Ошибка импорта модулей winsdk: {e}. Функциональность WGC будет недоступна.")
        WGC_SUPPORT_AVAILABLE = False
    except Exception as e_winsdk_general:
        print(f"[wgc_capture] Неожиданная ошибка при импорте winsdk: {e_winsdk_general}. Функциональность WGC будет недоступна.")
        WGC_SUPPORT_AVAILABLE = False
else:
    print("[wgc_capture] Платформа не Windows. Функциональность WGC будет недоступна.")
    WGC_SUPPORT_AVAILABLE = False

if WGC_SUPPORT_AVAILABLE and sys.platform == "win32":
    from wgc_utils import (
        SUCCEEDED, FAILED, HResultException,
        IID_ID3D11Device, IID_IDXGIDevice,
        ID3D11Device, ID3D11DeviceContext, IDXGIDevice, 
        D3D11_SDK_VERSION, D3D_DRIVER_TYPE_HARDWARE, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        UINT, WINSDK_BASE_AVAILABLE as WGC_UTILS_WINSDK_BASE_AVAILABLE # Используем новое имя
    )
    # Если wgc_utils говорит, что база winsdk не доступна, то и WGC не может быть полностью доступен
    if not WGC_UTILS_WINSDK_BASE_AVAILABLE: 
        print("[wgc_capture] wgc_utils сообщили о недоступности базы winsdk. Отключаем WGC.")
        WGC_SUPPORT_AVAILABLE = False 
    
    # d3d11_dll должен быть определен только если WGC_SUPPORT_AVAILABLE все еще True
    if WGC_SUPPORT_AVAILABLE:
        d3d11_dll = ctypes.windll.d3d11
    else:
        d3d11_dll = None # Явно None, если WGC отключен на этом этапе
else: 
    class HResultException(OSError): pass 
    SUCCEEDED = lambda hr: False
    FAILED = lambda hr: True
    ID3D11Device = ctypes.c_void_p 
    ID3D11DeviceContext = ctypes.c_void_p
    IDXGIDevice = ctypes.c_void_p
    IID_ID3D11Device = None
    IID_IDXGIDevice = None
    D3D11_SDK_VERSION = 0
    D3D_DRIVER_TYPE_HARDWARE = 0
    D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0
    UINT = ctypes.c_uint
    d3d11_dll = None


class WGCCapture:
    def __init__(self, hwnd: wintypes.HWND, logger_func=print):
        self.hwnd = hwnd
        self.logger = logger_func
        self.is_initialized = False      
        
        self.item_rt = None 
        self.d3d_device_winrt = None 
        self.frame_pool_rt = None 
        self.session_rt = None 
        
        self._d3d_device_com = None 
        self._d3d_context_com = None 
        self._dxgi_device_com = None 

        self.item_width = 0
        self.item_height = 0
        
        if not WGC_SUPPORT_AVAILABLE:
            self.logger("[WGCCapture] WGC API недоступен (проблемы с winsdk или не Windows). Инициализация отменена.")
            return 

        try:
            self._initialize_wgc_safe()
        except Exception as e_init:
            self.logger(f"[WGCCapture HWND:{self.hwnd}] КРИТИЧЕСКАЯ ОШИБКА в конструкторе WGC: {e_init}")
            self.is_initialized = False
            self.close() # Попытка очистки


    def _initialize_wgc_safe(self):
        # ... (остальная часть класса WGCCapture без изменений) ...
        # Убедимся, что d3d11_dll используется только если он не None
        self.logger(f"[WGCCapture HWND:{self.hwnd}] Безопасная инициализация WGC...")
        if not self._initialize_capture_item_sdk():
            self.logger("[WGCCapture] _initialize_capture_item_sdk FAILED."); self.is_initialized = False; return
        if not self._initialize_d3d_device_sdk_interop():
            self.logger("[WGCCapture] _initialize_d3d_device_sdk_interop FAILED."); self.is_initialized = False; self.close(); return
        if not self._create_frame_pool_and_session_sdk():
            self.logger("[WGCCapture] _create_frame_pool_and_session_sdk FAILED."); self.is_initialized = False; self.close(); return
        
        if self.session_rt:
            try:
                self.session_rt.start_capture()
                self.is_initialized = True 
                self.logger(f"[WGCCapture HWND:{self.hwnd}] WGC инициализирован и сессия успешно стартовала.")
            except Exception as e_start_capture:
                self.logger(f"[WGCCapture HWND:{self.hwnd}] Ошибка при start_capture: {e_start_capture}. WGC для этого окна недоступен.")
                self.is_initialized = False
                self.close() 
                return 
        else: 
            self.logger(f"[WGCCapture HWND:{self.hwnd}] Сессия захвата не была создана.")
            self.is_initialized = False
            self.close()
            return
        
        self.logger(f"[WGCCapture HWND:{self.hwnd}] WGC полностью инициализирован.")


    def _initialize_capture_item_sdk(self) -> bool:
        self.logger("[WGCCapture] Инициализация GraphicsCaptureItem...")
        if not ms_ui or not wgc or not wgc.GraphicsCaptureSession.is_supported():
            self.logger("[WGCCapture] ms_ui или wgc не импортированы, или GraphicsCaptureSession не поддерживается.")
            return False
            
        try:
            hwnd_value = self.hwnd 
            if isinstance(self.hwnd, ctypes.c_void_p): hwnd_value = self.hwnd.value
            if hwnd_value is None or hwnd_value == 0: 
                self.logger("[WGCCapture] HWND is None or 0."); return False
            if not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd_value)):
                self.logger(f"[WGCCapture] HWND {hwnd_value} не является валидным окном."); return False

            window_id = ms_ui.WindowId(hwnd_value)
            item = wgc.GraphicsCaptureItem.try_create_from_window_id(window_id)

            if item is None:
                self.logger(f"[WGCCapture] try_create_from_window_id вернул None для HWND {self.hwnd}."); return False
            self.item_rt = item
            size = self.item_rt.size
            self.item_width = size.width; self.item_height = size.height
            if self.item_width <= 0 or self.item_height <= 0:
                self.logger(f"[WGCCapture] Некорректные размеры элемента: {self.item_width}x{self.item_height}"); self.item_rt = None; return False
            self.logger(f"[WGCCapture] GraphicsCaptureItem создан: {self.item_width}x{self.item_height}"); return True
        except AttributeError as ae:
             self.logger(f"[WGCCapture] AttributeError при создании GCI (проверьте winsdk): {ae}"); self.item_rt = None; return False
        except Exception as e:
            self.logger(f"[WGCCapture] Исключение при создании GCI: {e} (HRESULT: {getattr(e, 'hresult', 'N/A'):#0x})"); self.item_rt = None; return False

    def _initialize_d3d_device_sdk_interop(self) -> bool:
        self.logger("[WGCCapture] Инициализация D3D11 устройства (COM) и WinRT IDirect3DDevice...")
        if not d3d11_winrt or not d3d11_dll or IID_IDXGIDevice is None: 
            self.logger("[WGCCapture] d3d11_winrt, d3d11_dll или IID не доступны."); return False

        d3d_device_com_ptr = ctypes.POINTER(ID3D11Device)()
        d3d_context_com_ptr = ctypes.POINTER(ID3D11DeviceContext)()
        feature_level = UINT()
        creation_flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT
        
        hr = d3d11_dll.D3D11CreateDevice(None, D3D_DRIVER_TYPE_HARDWARE, None, creation_flags, None, 0, D3D11_SDK_VERSION, ctypes.byref(d3d_device_com_ptr), ctypes.byref(feature_level), ctypes.byref(d3d_context_com_ptr))
        if FAILED(hr) or not d3d_device_com_ptr or not d3d_device_com_ptr.contents:
            self.logger(f"[WGCCapture] D3D11CreateDevice не удалось. HR: {hr:#0x}"); return False
        self._d3d_device_com = d3d_device_com_ptr
        self._d3d_context_com = d3d_context_com_ptr
        self.logger(f"[WGCCapture] D3D11Device/Context созданы. Уровень: {feature_level.value:#0x}")
        
        dxgi_device_com_ptr = ctypes.POINTER(IDXGIDevice)()
        hr_qi_dxgi = self._d3d_device_com.contents.QueryInterface(ctypes.byref(IID_IDXGIDevice), ctypes.byref(ctypes.cast(ctypes.byref(dxgi_device_com_ptr), ctypes.POINTER(ctypes.c_void_p))))
        if FAILED(hr_qi_dxgi) or not dxgi_device_com_ptr or not dxgi_device_com_ptr.contents:
            self.logger(f"[WGCCapture] QueryInterface для IDXGIDevice не удался. HR: {hr_qi_dxgi:#0x}")
            self._release_com_object(self._d3d_device_com, "d3d_device_com"); self._d3d_device_com = None
            self._release_com_object(self._d3d_context_com, "d3d_context_com"); self._d3d_context_com = None
            return False
        self._dxgi_device_com = dxgi_device_com_ptr
        self.logger("[WGCCapture] IDXGIDevice (COM) получен.")
        
        try:
            self.d3d_device_winrt = d3d11_winrt.CreateDirect3DDevice(self._dxgi_device_com) 
            if self.d3d_device_winrt is None:
                self.logger("[WGCCapture] CreateDirect3DDevice вернул None.")
                self._release_com_object(self._dxgi_device_com, "dxgi_device_com"); self._dxgi_device_com = None
                self._release_com_object(self._d3d_device_com, "d3d_device_com"); self._d3d_device_com = None
                self._release_com_object(self._d3d_context_com, "d3d_context_com"); self._d3d_context_com = None
                return False
            self.logger("[WGCCapture] WinRT IDirect3DDevice создан."); return True
        except Exception as e_interop: 
            self.logger(f"[WGCCapture] Исключение при создании WinRT IDirect3DDevice: {e_interop} (HRESULT: {getattr(e_interop, 'hresult', 'N/A'):#0x})");
            self._release_com_object(self._dxgi_device_com, "dxgi_device_com"); self._dxgi_device_com = None
            self._release_com_object(self._d3d_device_com, "d3d_device_com"); self._d3d_device_com = None
            self._release_com_object(self._d3d_context_com, "d3d_context_com"); self._d3d_context_com = None
            self.d3d_device_winrt = None; return False

    def _create_frame_pool_and_session_sdk(self) -> bool:
        self.logger("[WGCCapture] Создание FramePool и Session...")
        if self.d3d_device_winrt is None or self.item_rt is None or not wgc or not wgdx:
            self.logger("[WGCCapture] D3DDevice, CaptureItem, wgc или wgdx None."); return False
        try:
            self.frame_pool_rt = wgc.Direct3D11CaptureFramePool.create_free_threaded(self.d3d_device_winrt, wgdx.DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED, 2, self.item_rt.size)
            if self.frame_pool_rt is None: self.logger("[WGCCapture] FramePool.create_free_threaded вернул None."); return False
            self.logger(f"[WGCCapture] FramePool создан. Размер: {self.item_rt.size.width}x{self.item_rt.size.height}")
            
            self.session_rt = self.frame_pool_rt.create_capture_session(self.item_rt)
            if self.session_rt is None: 
                self.logger("[WGCCapture] create_capture_session вернул None.")
                if self.frame_pool_rt: self._release_winrt_object(self.frame_pool_rt, "frame_pool_rt"); self.frame_pool_rt = None
                return False
            self.logger("[WGCCapture] GraphicsCaptureSession создан."); return True
        except Exception as e_fp_sess: 
            self.logger(f"[WGCCapture] Исключение при создании FramePool/Session: {e_fp_sess} (HRESULT: {getattr(e_fp_sess, 'hresult', 'N/A'):#0x})");
            if self.frame_pool_rt: self._release_winrt_object(self.frame_pool_rt, "frame_pool_rt"); self.frame_pool_rt = None
            if self.session_rt: self._release_winrt_object(self.session_rt, "session_rt"); self.session_rt = None
            return False

    def grab_frame(self) -> np.ndarray | None:
        # ... (без изменений, все еще возвращает None) ...
        if not self.is_initialized or self.frame_pool_rt is None or self.session_rt is None: return None
        frame_np = None
        try:
            frame_rt = self.frame_pool_rt.try_get_next_frame()
            if frame_rt: frame_rt.close() 
        except Exception as e_grab:
            self.logger(f"[WGCCapture grab_frame] Ошибка: {e_grab} (HRESULT: {getattr(e_grab, 'hresult', 'N/A'):#0x})");
            self.is_initialized = False; self.close()
        return frame_np

    def _release_winrt_object(self, obj, name):
        # ... (без изменений) ...
        if obj:
            try: obj.close(); self.logger(f"[WGCCapture] WinRT '{name}' закрыт.")
            except Exception as e: self.logger(f"[WGCCapture] Ошибка закрытия WinRT '{name}': {e}")
        return None

    def _release_com_object(self, com_ptr_ptr, name): 
        # ... (без изменений) ...
        if com_ptr_ptr and com_ptr_ptr.contents: 
            try:
                ref_count = com_ptr_ptr.contents.Release()
                self.logger(f"[WGCCapture] COM '{name}' освобожден. Ссылки: {ref_count}")
            except Exception as e: self.logger(f"[WGCCapture] Ошибка освобождения COM '{name}': {e}")
        return None

    def close(self):
        # ... (без изменений) ...
        self.logger(f"[WGCCapture HWND:{self.hwnd}] Закрытие WGC ресурсов...")
        self.session_rt = self._release_winrt_object(self.session_rt, "SessionRT")
        self.frame_pool_rt = self._release_winrt_object(self.frame_pool_rt, "FramePoolRT")
        self.item_rt = self._release_winrt_object(self.item_rt, "CaptureItemRT")
        self.d3d_device_winrt = self._release_winrt_object(self.d3d_device_winrt, "WinRT IDirect3DDevice")
        self._dxgi_device_com = self._release_com_object(self._dxgi_device_com, "_dxgi_device_com")
        self._d3d_context_com = self._release_com_object(self._d3d_context_com, "_d3d_context_com")
        self._d3d_device_com = self._release_com_object(self._d3d_device_com, "_d3d_device_com")
        self.is_initialized = False 
        self.logger(f"[WGCCapture HWND:{self.hwnd}] Ресурсы WGC освобождены/закрыты.")

    def __del__(self):
        # ... (без изменений) ...
        has_active_resources = bool(self.item_rt or self.session_rt or self.frame_pool_rt or self.d3d_device_winrt or self._d3d_device_com)
        if has_active_resources:
            self.logger(f"[WGCCapture HWND:{self.hwnd if self.hwnd else 'N/A'}] __del__ с активными ресурсами. Принудительное close().")
            self.close()

def is_wgc_fully_available():
    # ... (без изменений) ...
    return WGC_SUPPORT_AVAILABLE

if __name__ == '__main__':
    # ... (блок __main__ без изменений, он должен теперь корректно использовать is_wgc_fully_available) ...
    def test_logger(message): print(f"WGC_TEST: {message}")
    test_logger("WGC Capture Test Script")
    if not is_wgc_fully_available():
        test_logger("WGC не доступен согласно is_wgc_fully_available(). Тест не может быть выполнен.")
        exit()
    com_init_hr = -1; TEST_SUCCEEDED_FUNC_LOCAL = lambda hr_val: hr_val >= 0 # Локальная заглушка
    try:
        from wgc_utils import init_com as test_init_com, uninit_com as test_uninit_com, SUCCEEDED as TEST_SUCCEEDED_FROM_UTILS
        TEST_SUCCEEDED_FUNC_LOCAL = TEST_SUCCEEDED_FROM_UTILS # Используем из utils, если доступно
        com_init_hr = test_init_com()
        if TEST_SUCCEEDED_FUNC_LOCAL(com_init_hr) or com_init_hr == 0x80010106: test_logger(f"COM инициализирован. HR: {com_init_hr:#0x}")
        else: test_logger(f"Ошибка COM init. HR: {com_init_hr:#0x}."); exit(1)
    except Exception as e_com_test: test_logger(f"Исключение COM init: {e_com_test}"); exit(1)
    test_logger("Ожидание 3s..."); time.sleep(3)
    target_hwnd_val = ctypes.windll.user32.GetForegroundWindow()
    if not target_hwnd_val: test_logger("Нет окна."); exit()
    window_text_buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(target_hwnd_val, window_text_buf, 255)
    test_logger(f"Окно: '{window_text_buf.value}' (HWND: {target_hwnd_val})")
    wgc_capturer = None
    try:
        wgc_capturer = WGCCapture(wintypes.HWND(target_hwnd_val), logger_func=test_logger)
        if wgc_capturer.is_initialized: 
            test_logger(f"WGCCapture init OK. Размеры: {wgc_capturer.item_width}x{wgc_capturer.item_height}")
            for i in range(5): 
                time.sleep(0.1); frame = wgc_capturer.grab_frame()
                if not wgc_capturer.is_initialized: test_logger(f"WGC стал uninitialized на кадре {i+1}."); break
            test_logger("Тест grab_frame завершен (пока None).")
        else: test_logger("WGCCapture НЕ инициализирован.")
    except Exception as e_test_main: test_logger(f"Ошибка теста WGC: {e_test_main}"); import traceback; traceback.print_exc()
    finally:
        if wgc_capturer: test_logger("Закрытие WGCCapture..."); wgc_capturer.close()
        if TEST_SUCCEEDED_FUNC_LOCAL(com_init_hr) or com_init_hr == 0x80010106:
            test_logger("Деинициализация COM..."); 
            if 'test_uninit_com' in locals() or ('wgc_utils' in sys.modules and hasattr(sys.modules['wgc_utils'], 'uninit_com')): 
                from wgc_utils import uninit_com as actual_uninit_com
                actual_uninit_com()
        test_logger("Тест WGC завершен.")
