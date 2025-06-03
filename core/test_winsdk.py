# test_winsdk.py
print("Attempting to import winsdk.microsoft.ui...")
try:
    import winsdk.microsoft.ui
    print("Successfully imported winsdk.microsoft.ui")
    
    # Попробуем создать WindowId для текущего процесса, если импорт успешен
    # Это просто для проверки, что базовые вызовы работают
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow() # Получаем HWND консольного окна
        if hwnd != 0:
            print(f"Console HWND: {hwnd}")
            window_id = winsdk.microsoft.ui.WindowId(hwnd)
            print(f"Successfully created WindowId: {window_id.value}")
        else:
            print("Could not get console HWND for WindowId test.")
    except Exception as e_wid:
        print(f"Error creating WindowId: {e_wid}")

except ImportError as e_imp:
    print(f"ImportError: {e_imp}")
    print("Failed to import winsdk.microsoft.ui")
except Exception as e_other:
    print(f"An other error occurred: {e_other}")
    import traceback
    traceback.print_exc()

input("Press Enter to exit...") 