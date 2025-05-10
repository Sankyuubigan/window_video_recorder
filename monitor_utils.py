import win32api
import win32con

def get_all_monitors_info():
    """
    Возвращает список словарей с информацией о каждом мониторе.
    Каждый словарь содержит: 'x', 'y', 'width', 'height', 'device_name', 'is_primary', 'handle'.
    Координаты и размеры указаны для виртуального экрана.
    """
    monitors_details = []
    try:
        monitors = win32api.EnumDisplayMonitors()
        for i, monitor_handle in enumerate(monitors):
            info = win32api.GetMonitorInfo(monitor_handle[0]) # monitor_handle[0] это HMONITOR
            
            # {'Device': '\\\\.\\DISPLAY1', 'Work': (0, 0, 1920, 1040), 'Flags': 1, 'Monitor': (0, 0, 1920, 1080)}
            # Monitor - это координаты на виртуальном рабочем столе
            rect = info['Monitor']
            device_name = info.get('Device', f'UnknownDevice{i}')
            
            is_primary = (info['Flags'] & win32con.MONITORINFOF_PRIMARY) == win32con.MONITORINFOF_PRIMARY
            
            details = {
                'x': rect[0],
                'y': rect[1],
                'width': rect[2] - rect[0],
                'height': rect[3] - rect[1],
                'device_name': device_name,
                'is_primary': is_primary,
                'handle': monitor_handle[0]
            }
            monitors_details.append(details)
    except Exception as e:
        print(f"[MonitorUtils] Ошибка при получении информации о мониторах: {e}")
    return monitors_details

def get_primary_monitor_info():
    """
    Возвращает словарь с информацией об основном (primary) мониторе.
    Или None, если не удалось определить.
    """
    all_monitors = get_all_monitors_info()
    for monitor in all_monitors:
        if monitor['is_primary']:
            return monitor
    
    # Если флаг primary не сработал (маловероятно, но возможно),
    # часто основной монитор имеет координаты (0,0)
    if all_monitors:
        for monitor in all_monitors:
            if monitor['x'] == 0 and monitor['y'] == 0:
                print("[MonitorUtils] Предупреждение: Основной монитор определен по координатам (0,0), а не по флагу PRIMARY.")
                return monitor
        # Если и это не помогло, возвращаем первый в списке как крайний случай
        print("[MonitorUtils] Предупреждение: Не удалось точно определить основной монитор. Возвращаем первый из списка.")
        return all_monitors[0]
        
    return None

if __name__ == '__main__':
    print("Информация обо всех мониторах:")
    monitors = get_all_monitors_info()
    if monitors:
        for idx, mon in enumerate(monitors):
            print(f"  Монитор {idx + 1}:")
            for key, value in mon.items():
                print(f"    {key}: {value}")
    else:
        print("  Не удалось получить информацию о мониторах.")

    print("\nИнформация об основном мониторе:")
    primary = get_primary_monitor_info()
    if primary:
        for key, value in primary.items():
            print(f"  {key}: {value}")
    else:
        print("  Не удалось получить информацию об основном мониторе.")