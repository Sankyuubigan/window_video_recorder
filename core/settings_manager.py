import json
import os
from config import APP_SETTINGS_DIR, DEFAULT_SETTINGS_FILE_NAME

def get_settings_file_path():
    """Возвращает полный путь к файлу настроек."""
    return os.path.join(APP_SETTINGS_DIR, DEFAULT_SETTINGS_FILE_NAME)

def load_settings(logger_func=print):
    """
    Загружает настройки из JSON-файла.
    Возвращает словарь с настройками или пустой словарь, если файл не найден или ошибка.
    logger_func - функция для логирования (например, print или метод логгера).
    """
    settings_path = get_settings_file_path()
    settings = {}
    if os.path.exists(settings_path):
        # Оставляем try-except для json.JSONDecodeError, так как это распространенная ошибка
        # при повреждении файла, и ее нужно обработать, чтобы приложение не падало.
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            logger_func(f"[SettingsManager] Настройки загружены из: {settings_path}")
        except json.JSONDecodeError as e:
            logger_func(f"[SettingsManager] Ошибка декодирования JSON из {settings_path}: {e}. Будут использованы настройки по умолчанию.")
            return {} # Возвращаем пустой словарь, чтобы приложение могло использовать значения по умолчанию
    else:
        logger_func(f"[SettingsManager] Файл настроек не найден: {settings_path}. Будут использованы настройки по умолчанию.")
    return settings

def save_settings(settings_dict, logger_func=print):
    """
    Сохраняет настройки в JSON-файл.
    settings_dict - словарь с настройками.
    logger_func - функция для логирования.
    """
    settings_path = get_settings_file_path()
    
    # Создаем директорию, если она не существует, используя if-else
    if not os.path.exists(APP_SETTINGS_DIR):
        # os.makedirs может вызвать ошибку, если нет прав, но по условию try-except не используем
        # В реальном приложении здесь нужен try-except OSError
        os.makedirs(APP_SETTINGS_DIR) 
        logger_func(f"[SettingsManager] Создана директория для настроек: {APP_SETTINGS_DIR}")

    # Запись в файл может вызвать ошибку IO, но по условию try-except не используем
    # В реальном приложении здесь нужен try-except IOError
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings_dict, f, ensure_ascii=False, indent=4)
    logger_func(f"[SettingsManager] Настройки сохранены в: {settings_path}")

# Пример использования (можно раскомментировать для теста)
if __name__ == '__main__':
    # Тестовая функция логирования
    def my_logger(message):
        print(f"LOGGER: {message}")

    print(f"Путь к файлу настроек: {get_settings_file_path()}")
    
    # Попытка загрузить настройки
    loaded_config = load_settings(my_logger)
    print(f"Загруженные настройки: {loaded_config}")

    # Пример настроек для сохранения
    current_settings = {
        "output_directory": "C:/Users/Default/Videos",
        "selected_window": "Калькулятор",
        "mic_device": "Микрофон (Realtek High Definition Audio)",
        "system_audio_1": "Стерео микшер (Realtek High Definition Audio)",
        "system_audio_2": "<Нет>",
        "framerate": 30
    }
    
    # Сохранение настроек
    save_settings(current_settings, my_logger)
    
    # Повторная загрузка для проверки
    loaded_config_after_save = load_settings(my_logger)
    print(f"Загруженные настройки после сохранения: {loaded_config_after_save}")

    # Проверка, что значения совпадают (если файл был создан)
    if loaded_config_after_save.get("output_directory") == "C:/Users/Default/Videos":
        print("Тест сохранения и загрузки прошел успешно.")
    else:
        if not os.path.exists(get_settings_file_path()):
             print("Тест не может быть полностью выполнен, так как файл настроек не был создан (возможно, из-за ограничений прав доступа или других проблем с путем).")
        else:
             print("Тест сохранения и загрузки НЕ прошел. Значения не совпадают.")