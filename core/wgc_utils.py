# -*- coding: utf-8 -*-
import ctypes
from ctypes import wintypes, windll
from ctypes.wintypes import HWND, RECT, POINT, ULONG, USHORT, BYTE, LPCWSTR, UINT, HANDLE, LONG 
import uuid
import threading
import sys

WINSDK_BASE_AVAILABLE = True
HSTRING_TYPE = wintypes.HANDLE # Запасной тип по умолчанию

try:
    import winsdk
    # Пытаемся получить тип HSTRING из известных мест в winsdk
    # winsdk.system.HSTRING - один из возможных стандартных путей
    if hasattr(winsdk, 'system') and hasattr(winsdk.system, 'HSTRING'):
        HSTRING_TYPE = winsdk.system.HSTRING
        print("[wgc_utils] HSTRING_TYPE определен из winsdk.system.HSTRING.")
    # Можно добавить другие проверки, если HSTRING может быть в других местах в разных версиях winsdk
    # elif hasattr(winsdk.windows.foundation, ' ... '): HSTRING_TYPE = ...
    else:
        # Если стандартные пути не найдены, возможно, winsdk не полностью инициализирован
        # или структура изменилась. Оставляем HANDLE и понижаем флаг.
        print("[wgc_utils] winsdk импортирован, но стандартный HSTRING_TYPE не найден. Используется запасной HANDLE. WINSDK_BASE_AVAILABLE может быть неточным.")
        # WINSDK_BASE_AVAILABLE = False # Можно рассмотреть этот вариант, если это критично
except ImportError:
    WINSDK_BASE_AVAILABLE = False
    print("[wgc_utils] Не удалось импортировать базовый модуль winsdk. HSTRING_TYPE будет wintypes.HANDLE.")
except Exception as e_hstring_check: # Ловим другие ошибки при проверке HSTRING
    WINSDK_BASE_AVAILABLE = False
    print(f"[wgc_utils] Ошибка при определении HSTRING_TYPE из winsdk: {e_hstring_check}. Используется запасной HANDLE.")


HRESULT = wintypes.LONG
UINT64 = ctypes.c_uint64
if not hasattr(wintypes, 'UINT'): 
    UINT = ctypes.c_uint

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ULONG), ("Data2", USHORT), ("Data3", USHORT), ("Data4", BYTE * 8)
    ]
    def __init__(self, guid_string=None):
        if guid_string: 
            u = uuid.UUID(guid_string)
            self.Data1 = u.time_low; self.Data2 = u.time_mid; self.Data3 = u.time_hi_version
            guid_bytes = u.bytes
            for i in range(8): self.Data4[i] = guid_bytes[8+i] # Стандартное присвоение элементам массива ctypes
    def __repr__(self): return f"GUID('{self.to_uuid()}')"
    def to_uuid(self) -> uuid.UUID:
        return uuid.UUID(bytes_le=(self.Data1.to_bytes(4,'little') + self.Data2.to_bytes(2,'little') + self.Data3.to_bytes(2,'little') + bytes(self.Data4)))
    @classmethod
    def from_string(cls, guid_string: str): return cls(guid_string=guid_string)

class IUnknownVtbl(ctypes.Structure):
    _fields_=[
        ("QueryInterface", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))),
        ("AddRef", ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)),
        ("Release", ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)),
    ]
class IUnknown(ctypes.Structure):
    _fields_=[("lpVtbl",ctypes.POINTER(IUnknownVtbl))]
    def QueryInterface(self, riid_ptr, ppvObject_ptr): return self.lpVtbl.contents.QueryInterface(ctypes.byref(self), riid_ptr, ppvObject_ptr)
    def AddRef(self): return self.lpVtbl.contents.AddRef(ctypes.byref(self))
    def Release(self): return self.lpVtbl.contents.Release(ctypes.byref(self))

class ID3D11DeviceContext(IUnknown): pass 

_id3d11device_vtbl_fields_list = IUnknownVtbl._fields_ + [
    ("CreateBuffer", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
    ("CreateTexture1D", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)),
    ("CreateTexture2D", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)), 
]
_id3d11device_vtbl_fields_list.extend([(f"Placeholder_dev_create{i}", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)) for i in range(37)])
_id3d11device_vtbl_fields_list.append(("GetImmediateContext", ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ID3D11DeviceContext)))))
class ID3D11DeviceVtbl(ctypes.Structure): _fields_ = _id3d11device_vtbl_fields_list
class ID3D11Device(IUnknown): _fields_=[("lpVtbl",ctypes.POINTER(ID3D11DeviceVtbl))]

class IDXGIDeviceVtbl(ctypes.Structure):
    _fields_ = IUnknownVtbl._fields_ + [
        ("SetPrivateData", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), UINT, ctypes.c_void_p)),
        ("SetPrivateDataInterface", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(IUnknown))),
        ("GetPrivateData", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(UINT), ctypes.c_void_p)),
        ("GetParent", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))),
        ("GetAdapter", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p)),
        ("CreateSurface", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, UINT, UINT, ctypes.c_void_p, ctypes.c_void_p)),
        ("QueryResourceResidency", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(IUnknown)), ctypes.c_void_p, UINT)),
        ("SetGPUThreadPriority", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_int)),
        ("GetGPUThreadPriority", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))),
    ]
class IDXGIDevice(IUnknown): _fields_=[("lpVtbl",ctypes.POINTER(IDXGIDeviceVtbl))]

IID_IUnknown = GUID.from_string('00000000-0000-0000-C000-000000000046')
IID_ID3D11Device = GUID.from_string('db6f6ddb-ac77-4e88-8253-819df9bbf140')
IID_IDXGIDevice = GUID.from_string('54ec77fa-1377-44e6-8c32-88fd5f44c84c')

combase = None
d3d11 = None
if sys.platform == "win32":
    combase = windll.combase
    combase.RoInitialize.argtypes=[ctypes.c_int]; combase.RoInitialize.restype=HRESULT
    combase.RoUninitialize.argtypes=[]; combase.RoUninitialize.restype=None
    # Проверяем наличие функций WindowsCreateString и т.д. перед определением argtypes
    if WINSDK_BASE_AVAILABLE and hasattr(combase, 'WindowsCreateString') and \
       hasattr(combase, 'WindowsDeleteString') and hasattr(combase, 'WindowsGetStringRawBuffer') and \
       hasattr(combase, 'RoGetActivationFactory'):
        combase.RoGetActivationFactory.argtypes=[HSTRING_TYPE,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];combase.RoGetActivationFactory.restype=HRESULT
        combase.WindowsCreateString.argtypes=[LPCWSTR,UINT,ctypes.POINTER(HSTRING_TYPE)];combase.WindowsCreateString.restype=HRESULT
        combase.WindowsDeleteString.argtypes=[HSTRING_TYPE];combase.WindowsDeleteString.restype=HRESULT
        combase.WindowsGetStringRawBuffer.argtypes=[HSTRING_TYPE,ctypes.POINTER(UINT)];combase.WindowsGetStringRawBuffer.restype=LPCWSTR
    else:
        # Если функции для HSTRING недоступны, то WINSDK_BASE_AVAILABLE должен быть False
        WINSDK_BASE_AVAILABLE = False
        print("[wgc_utils] Функции Windows*String или RoGetActivationFactory не найдены в combase. WINSDK_BASE_AVAILABLE установлен в False.")

    d3d11=windll.d3d11
    d3d11.D3D11CreateDevice.argtypes=[ctypes.c_void_p, UINT, HANDLE, UINT, ctypes.POINTER(UINT), UINT, UINT, ctypes.POINTER(ctypes.POINTER(ID3D11Device)), ctypes.POINTER(UINT), ctypes.POINTER(ctypes.POINTER(ID3D11DeviceContext))]
    d3d11.D3D11CreateDevice.restype=HRESULT
else: 
    WINSDK_BASE_AVAILABLE = False

D3D11_SDK_VERSION=7
D3D_DRIVER_TYPE_HARDWARE=0
D3D11_CREATE_DEVICE_BGRA_SUPPORT=0x20
RO_INIT_MULTITHREADED = 0x1

def SUCCEEDED(hr_val: HRESULT) -> bool: return hr_val >= 0
def FAILED(hr_val: HRESULT) -> bool: return hr_val < 0

class HResultException(OSError):
    def __init__(self,hr_code,message=""): super().__init__(f"{message} HRESULT: {hr_code:#010x} ({hr_code})"); self.hr=hr_code

_com_initialized_thread_local = threading.local()
def init_com() -> HRESULT:
    if not sys.platform == "win32" or not combase: return -1 
    hr=combase.RoInitialize(RO_INIT_MULTITHREADED)
    if not (SUCCEEDED(hr) or hr == 0x80010106): 
        print(f"[wgc_utils] RoInitialize failed HRESULT: {hr:#0x}.")
    return hr

def uninit_com():
    if not sys.platform == "win32" or not combase: return
    combase.RoUninitialize()

def py_string_to_hstring(s:str) -> HSTRING_TYPE | None: 
    if not WINSDK_BASE_AVAILABLE or not combase or not hasattr(combase, 'WindowsCreateString'): return None
    hs=HSTRING_TYPE()
    hr=combase.WindowsCreateString(LPCWSTR(s),len(s),ctypes.byref(hs))
    if FAILED(hr): print(f"[wgc_utils] WindowsCreateString failed for '{s}'. HR: {hr:#0x}"); return None
    return hs

def hstring_to_py_string(hs:HSTRING_TYPE | None) -> str: 
    if not WINSDK_BASE_AVAILABLE or not hs or \
       (hasattr(hs, 'value') and not hs.value and hs.value != 0) or \
       not combase or not hasattr(combase, 'WindowsGetStringRawBuffer'): 
        return ""
    l=UINT()
    # Проверяем, что hs не None перед передачей в WindowsGetStringRawBuffer
    if hs is None: return ""
    b_ptr = combase.WindowsGetStringRawBuffer(hs,ctypes.byref(l))
    if not b_ptr: return ""
    return ctypes.wstring_at(b_ptr,l.value)
