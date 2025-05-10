import PyInstaller.__main__
import datetime
import os
import shutil

APP_NAME = "VideoConfRecorder"
MAIN_SCRIPT = "main.py"
ICON_FILE = "app_icon.ico" 

def get_version_string():
    """Генерирует строку версии на основе текущей даты."""
    now = datetime.datetime.now()
    return now.strftime("%y%m%d_%H%M")

def build():
    version_str = get_version_string()
    dist_path = "dist"
    build_path = "build"
    
    output_exe_name = f"{APP_NAME}_v{version_str}"

    pyinstaller_args = [
        MAIN_SCRIPT,
        '--name', output_exe_name,
        '--onefile',         
        '--windowed',        
        '--icon', ICON_FILE,
        '--distpath', dist_path,
        '--workpath', build_path,
        '--clean',           
        # Добавляем все .py файлы из текущей директории, кроме build.py
        # Это необходимо, чтобы PyInstaller нашел модули config, app_gui, etc.
        # os.pathsep - это ';' для Windows, ':' для Linux
        # '.' означает текущую директорию, где лежат модули
        '--paths', '.', 
        # '--add-data', f'{ICON_FILE}{os.pathsep}.', # Иконка должна быть найдена через --icon
    ]
    
    # Скрытые импорты для pywin32 (могут понадобиться)
    hidden_imports = [
        'win32timezone', 
        'win32com.gen_py'
    ]
    for imp in hidden_imports:
        pyinstaller_args.extend(['--hidden-import', imp])


    print(f"Запуск PyInstaller для сборки {output_exe_name}.exe...")
    print(f"Аргументы: {' '.join(pyinstaller_args)}")

    try:
        PyInstaller.__main__.run(pyinstaller_args)
        print(f"Сборка завершена успешно! Исполняемый файл в папке: {os.path.abspath(dist_path)}")
    except SystemExit as e:
        # PyInstaller использует SystemExit для указания на ошибки
        print(f"PyInstaller завершился с ошибкой (SystemExit: {e}). Проверьте лог выше.")
    except Exception as e:
        print(f"Ошибка во время сборки PyInstaller: {e}")

    # Удаляем .spec файл
    spec_file = f"{output_exe_name}.spec"
    if os.path.exists(spec_file):
        try:
            os.remove(spec_file)
            print(f"Удален файл {spec_file}")
        except Exception as e:
            print(f"Не удалось удалить файл {spec_file}: {e}")
    
    # Опционально: удалить папку build
    # if os.path.exists(build_path) and False: # Пока оставим для отладки
    #     print(f"Удаление временной папки сборки: {build_path}")
    #     try:
    #         shutil.rmtree(build_path)
    #     except Exception as e:
    #         print(f"Не удалось удалить папку {build_path}: {e}")

if __name__ == '__main__':
    if not os.path.exists(ICON_FILE):
        print(f"Ошибка: Файл иконки '{ICON_FILE}' не найден в корне проекта.")
        exit(1)
        
    if not os.path.exists(MAIN_SCRIPT):
        print(f"Ошибка: Основной скрипт '{MAIN_SCRIPT}' не найден.")
        exit(1)

    build()