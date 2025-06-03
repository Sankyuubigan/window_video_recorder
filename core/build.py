import PyInstaller.__main__
import datetime
import os
import shutil

APP_NAME = "VideoConfRecorder"
MAIN_SCRIPT = "main.py" # Относительно build.py (который в /core)
ICON_FILE_NAME = "app_icon.ico" 
# Путь к иконке относительно build.py. Если build.py в /core, а иконка в корне проекта:
ICON_FILE_PATH_RELATIVE_TO_BUILD = os.path.join("..", ICON_FILE_NAME) 

FFMPEG_SOURCE_DIR_RELATIVE_TO_BUILD = os.path.join("..", "ffmpeg_bin") # Папка ffmpeg_bin в корне проекта
FFMPEG_EXE_NAME = "ffmpeg.exe"
FFMPEG_SOURCE_PATH_RELATIVE_TO_BUILD = os.path.join(FFMPEG_SOURCE_DIR_RELATIVE_TO_BUILD, FFMPEG_EXE_NAME)


def get_version_string():
    """Генерирует строку версии на основе текущей даты."""
    now = datetime.datetime.now()
    return now.strftime("%y%m%d_%H%M")

def build():
    version_str = get_version_string()
    # Папки для сборки будут созданы относительно build.py (т.е. в /core/build_output)
    # Если хотите в корне проекта, нужно будет ../build_output
    base_build_dir = os.path.dirname(os.path.abspath(__file__)) # Папка, где лежит build.py (/core)
    
    # Выходные папки относительно корня проекта
    project_root = os.path.dirname(base_build_dir) # /
    dist_path_abs = os.path.join(project_root, "build_output", "dist") 
    build_path_abs = os.path.join(project_root, "build_output", "build_temp")
    
    os.makedirs(dist_path_abs, exist_ok=True)
    os.makedirs(build_path_abs, exist_ok=True)

    output_exe_name = f"{APP_NAME}_v{version_str}"

    # Аргументы для PyInstaller
    # Пути к скрипту, иконке, ffmpeg должны быть корректными относительно CWD PyInstaller.
    # PyInstaller обычно запускается из папки, где лежит .spec файл (или где MAIN_SCRIPT).
    # Мы будем запускать PyInstaller, находясь в папке /core.
    # MAIN_SCRIPT - это 'main.py' (т.е. core/main.py)
    # ICON_FILE_PATH_RELATIVE_TO_BUILD - это '../app_icon.ico'
    # FFMPEG_SOURCE_PATH_RELATIVE_TO_BUILD - это '../ffmpeg_bin/ffmpeg.exe'

    # --add-binary: <src_path_on_disk_host_sep>:<dest_path_in_bundle_bundle_sep>
    # bundle_sep всегда '/', host_sep - os.pathsep (неправильно, это разделитель PATH)
    # host_sep для путей это os.sep. Для --add-binary src - это путь на диске, dest - в бандле.
    # ':' или ';' - разделитель между src и dest.
    # Мы хотим, чтобы ffmpeg.exe и app_icon.ico оказались в корне бандла (рядом с основным .exe)
    
    add_binary_ffmpeg_arg = f"{os.path.abspath(FFMPEG_SOURCE_PATH_RELATIVE_TO_BUILD)}{os.pathsep}."
    add_binary_icon_arg = f"{os.path.abspath(ICON_FILE_PATH_RELATIVE_TO_BUILD)}{os.pathsep}."
    # Если иконка используется через --icon, ее не всегда нужно добавлять через --add-binary,
    # PyInstaller должен сам ее встроить. Но для --onefile, если мы хотим ее как отдельный файл в _MEIPASS,
    # то --add-binary нужен. Пока оставим ее для --icon.

    pyinstaller_args = [
        MAIN_SCRIPT, # core/main.py
        '--name', output_exe_name,
        '--onefile',         
        '--windowed',        
        '--icon', os.path.abspath(ICON_FILE_PATH_RELATIVE_TO_BUILD), # Используем абсолютный путь для надежности
        '--distpath', dist_path_abs,    
        '--workpath', build_path_abs,   
        '--specpath', build_path_abs, # .spec файл будет в build_temp в корне проекта
        '--clean',           
        # '--paths', '.', # Путь к main.py уже указан, текущая папка (core) будет в sys.path
        '--add-binary', add_binary_ffmpeg_arg, 
        # Если иконка не подхватывается для отображения в GUI из ресурсов exe,
        # можно попробовать добавить ее и так, чтобы она была в _MEIPASS:
        '--add-data', f"{os.path.abspath(ICON_FILE_PATH_RELATIVE_TO_BUILD)}{os.pathsep}.",
    ]
    
    hidden_imports = ['win32timezone', 'win32com.gen_py', 'psutil'] 
    for imp in hidden_imports:
        pyinstaller_args.extend(['--hidden-import', imp])

    print(f"Запуск PyInstaller для сборки {output_exe_name}.exe...")
    print(f"Аргументы: {' '.join(pyinstaller_args)}")
    print(f"Рабочая директория для PyInstaller будет: {base_build_dir}") # /core

    current_dir_before_pyinstaller = os.getcwd()
    os.chdir(base_build_dir) # Переходим в /core, чтобы пути к MAIN_SCRIPT и т.д. были проще

    try:
        PyInstaller.__main__.run(pyinstaller_args)
        # Итоговый .exe будет в dist_path_abs
        final_exe_path = os.path.join(dist_path_abs, f"{output_exe_name}.exe")
        print(f"Сборка завершена успешно! Исполняемый файл: {final_exe_path}")
    except SystemExit as e:
        print(f"PyInstaller завершился с ошибкой (SystemExit: {e}). Проверьте лог выше.")
    except Exception as e:
        print(f"Ошибка во время сборки PyInstaller: {e}")
    finally:
        os.chdir(current_dir_before_pyinstaller) # Возвращаемся в исходную директорию

    # .spec файл создается в build_path_abs (т.е. в /build_output/build_temp в корне)
    spec_file_in_build_path = os.path.join(build_path_abs, f"{output_exe_name}.spec")
    if os.path.exists(spec_file_in_build_path):
        try:
            # os.remove(spec_file_in_build_path) # Не будем удалять, он может быть полезен
            print(f"Файл .spec сохранен: {spec_file_in_build_path}")
        except Exception as e:
            print(f"Не удалось удалить файл {spec_file_in_build_path}: {e}")
    
    # Очистка временной папки build_temp (workpath) - PyInstaller должен делать это сам с --clean
    # if os.path.exists(build_path_abs):
    # print(f"Удаление временной папки сборки: {build_path_abs}")
    # shutil.rmtree(build_path_abs)


if __name__ == '__main__':
    # Проверяем пути относительно build.py (который в /core)
    abs_icon_path = os.path.abspath(ICON_FILE_PATH_RELATIVE_TO_BUILD)
    abs_main_script_path = os.path.abspath(MAIN_SCRIPT)
    abs_ffmpeg_path = os.path.abspath(FFMPEG_SOURCE_PATH_RELATIVE_TO_BUILD)

    if not os.path.exists(abs_icon_path):
        print(f"Ошибка: Файл иконки '{abs_icon_path}' не найден."); exit(1)
    if not os.path.exists(abs_main_script_path):
        print(f"Ошибка: Основной скрипт '{abs_main_script_path}' не найден."); exit(1)
    if not os.path.exists(abs_ffmpeg_path):
        print(f"Ошибка: Файл '{abs_ffmpeg_path}' не найден. Поместите ffmpeg.exe в {os.path.abspath(FFMPEG_SOURCE_DIR_RELATIVE_TO_BUILD)}.")
        exit(1)
    
    build()