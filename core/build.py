import PyInstaller.__main__
import datetime
import os
import shutil

APP_NAME = "VideoConfRecorder"
MAIN_SCRIPT = "main.py"
ICON_FILE = "app_icon.ico" 
FFMPEG_SOURCE_PATH = "ffmpeg_bin/ffmpeg.exe" # Путь к вашему ffmpeg.exe относительно build.py

def get_version_string():
    """Генерирует строку версии на основе текущей даты."""
    now = datetime.datetime.now()
    return now.strftime("%y%m%d_%H%M")

def build():
    version_str = get_version_string()
    dist_path = os.path.join("build_output", "dist") # Выходная папка для .exe
    build_path = os.path.join("build_output", "build_temp") # Временная папка сборки
    
    # Создаем выходные директории, если их нет
    os.makedirs(dist_path, exist_ok=True)
    os.makedirs(build_path, exist_ok=True)

    output_exe_name = f"{APP_NAME}_v{version_str}"

    # Определяем, как добавлять ffmpeg.exe
    # Для --onefile: PyInstaller сам распакует его во временную папку.
    # Для --onedir: он будет скопирован в указанное место.
    # Мы указываем, что ffmpeg.exe должен оказаться в подпапке ffmpeg_bin относительно основного .exe
    # или просто рядом, если собираем в одну папку.
    # os.pathsep это ';' для Windows, ':' для Linux/Mac
    
    # Для --onefile, чтобы config.py нашел ffmpeg.exe после распаковки,
    # он должен лежать в корне временной папки MEIPASS или в известной подпапке.
    # Если FFMPEG_SOURCE_PATH = "ffmpeg_bin/ffmpeg.exe",
    # то --add-binary "ffmpeg_bin/ffmpeg.exe:ffmpeg_bin"
    # И в config.py путь будет os.path.join(application_path, "ffmpeg_bin", "ffmpeg.exe")

    # Если мы хотим, чтобы ffmpeg.exe лежал просто рядом с основным .exe (в корне сборки)
    # то --add-binary "ffmpeg_bin/ffmpeg.exe:."
    # И в config.py путь будет os.path.join(application_path, "ffmpeg.exe")

    # Выберем вариант, когда ffmpeg.exe копируется в корень сборки (рядом с основным .exe)
    # Это проще для определения пути в config.py при --onefile (sys._MEIPASS)
    add_binary_ffmpeg_arg = f"{FFMPEG_SOURCE_PATH}{os.pathsep}."


    pyinstaller_args = [
        MAIN_SCRIPT,
        '--name', output_exe_name,
        '--onefile',         
        '--windowed',        
        '--icon', ICON_FILE,
        '--distpath', dist_path,    # Папка для最终 .exe
        '--workpath', build_path,   # Временная папка сборки
        '--specpath', build_path,   # Куда помещать .spec файл
        '--clean',           
        '--paths', '.', 
        '--add-binary', add_binary_ffmpeg_arg, # Добавляем ffmpeg.exe
        # '--add-binary', f"{ICON_FILE}{os.pathsep}.", # Если иконка нужна как отдельный файл данных
    ]
    
    hidden_imports = ['win32timezone', 'win32com.gen_py', 'psutil'] # Добавили psutil
    for imp in hidden_imports:
        pyinstaller_args.extend(['--hidden-import', imp])

    print(f"Запуск PyInstaller для сборки {output_exe_name}.exe...")
    print(f"Аргументы: {' '.join(pyinstaller_args)}")

    try:
        PyInstaller.__main__.run(pyinstaller_args)
        final_exe_path = os.path.join(dist_path, output_exe_name, f"{output_exe_name}.exe") if not '--onefile' in pyinstaller_args else os.path.join(dist_path, f"{output_exe_name}.exe")
        print(f"Сборка завершена успешно! Исполняемый файл: {os.path.abspath(final_exe_path)}")
    except SystemExit as e:
        print(f"PyInstaller завершился с ошибкой (SystemExit: {e}). Проверьте лог выше.")
    except Exception as e:
        print(f"Ошибка во время сборки PyInstaller: {e}")

    # Удаляем .spec файл, который создается в build_path
    spec_file_in_build_path = os.path.join(build_path, f"{output_exe_name}.spec")
    if os.path.exists(spec_file_in_build_path):
        try:
            os.remove(spec_file_in_build_path)
            print(f"Удален файл {spec_file_in_build_path}")
        except Exception as e:
            print(f"Не удалось удалить файл {spec_file_in_build_path}: {e}")
    
    # Очистка временной папки build, если нужно (после успешной сборки)
    # if os.path.exists(build_path):
    #     print(f"Удаление временной папки сборки: {build_path}")
    #     shutil.rmtree(build_path)


if __name__ == '__main__':
    if not os.path.exists(ICON_FILE):
        print(f"Ошибка: Файл иконки '{ICON_FILE}' не найден."); exit(1)
    if not os.path.exists(MAIN_SCRIPT):
        print(f"Ошибка: Основной скрипт '{MAIN_SCRIPT}' не найден."); exit(1)
    if not os.path.exists(FFMPEG_SOURCE_PATH):
        print(f"Ошибка: Файл '{FFMPEG_SOURCE_PATH}' не найден. Поместите ffmpeg.exe в папку ffmpeg_bin.")
        exit(1)
    build()