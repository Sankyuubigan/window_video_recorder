import PyInstaller.__main__
import datetime
import os
import shutil 

APP_NAME = "VideoConfRecorder" 
MAIN_SCRIPT_NAME = "main.py" 
ICON_FILE_NAME = "app_icon.ico" 
FFMPEG_EXE_NAME = "ffmpeg.exe"

BUILD_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_DIR = os.path.dirname(BUILD_SCRIPT_DIR)

ABS_MAIN_SCRIPT_PATH = os.path.join(BUILD_SCRIPT_DIR, MAIN_SCRIPT_NAME) 
ABS_ICON_FILE_PATH = os.path.join(PROJECT_ROOT_DIR, ICON_FILE_NAME) 
ABS_FFMPEG_SOURCE_PATH = os.path.join(PROJECT_ROOT_DIR, FFMPEG_EXE_NAME) 

def get_date_version_string(): 
    now = datetime.datetime.now()
    return now.strftime("%y%m%d") # Формат ГГММДД

def build():
    version_str = get_date_version_string()
    # Имя .exe файла будет включать дату как часть версии
    output_exe_name = f"{APP_NAME}_v{version_str}" 

    dist_path_abs = os.path.join(PROJECT_ROOT_DIR, "dist") 
    build_temp_path_abs = os.path.join(PROJECT_ROOT_DIR, "build_temp_pyinstaller")
    
    # Не удаляем старую папку dist
    # if os.path.exists(dist_path_abs):
    #     print(f"Удаление старой папки dist: {dist_path_abs}")
    #     shutil.rmtree(dist_path_abs)

    # Удаляем старую временную папку сборки, если она есть, перед началом новой
    if os.path.exists(build_temp_path_abs):
        print(f"Удаление старой папки build_temp: {build_temp_path_abs}")
        try:
            shutil.rmtree(build_temp_path_abs)
        except Exception as e_rm_old_build:
            print(f"Не удалось удалить старую папку {build_temp_path_abs}: {e_rm_old_build}")


    os.makedirs(dist_path_abs, exist_ok=True)
    # PyInstaller сам создаст workpath (build_temp_path_abs), если его нет

    add_binary_ffmpeg_arg = f"{ABS_FFMPEG_SOURCE_PATH}{os.pathsep}."
    add_data_icon_arg = f"{ABS_ICON_FILE_PATH}{os.pathsep}." 
    
    pyinstaller_args = [
        MAIN_SCRIPT_NAME, 
        '--name', output_exe_name, # Имя .exe файла теперь включает дату
        '--onefile',         
        '--windowed', # Используем --windowed, чтобы не было консоли
        '--icon', ABS_ICON_FILE_PATH, 
        '--distpath', dist_path_abs,    
        '--workpath', build_temp_path_abs,    
        '--specpath', build_temp_path_abs, 
        # Опция --clean для PyInstaller удаляет его кэш, не workpath/distpath.
        # Мы сами управляем workpath (build_temp_path_abs).
    ]
    
    pyinstaller_args.extend(['--add-binary', add_binary_ffmpeg_arg])
    pyinstaller_args.extend(['--add-data', add_data_icon_arg])
    
    hidden_imports = ['win32timezone', 'win32com.gen_py', 'psutil'] 
    for imp in hidden_imports:
        pyinstaller_args.extend(['--hidden-import', imp])

    print(f"Запуск PyInstaller для сборки {output_exe_name}.exe...")
    log_args_display = []
    for arg in pyinstaller_args:
        if " " in arg and not (arg.startswith("'") or arg.startswith('"')):
            log_args_display.append(f'"{arg}"')
        else:
            log_args_display.append(arg)
    print(f"Аргументы: {' '.join(log_args_display)}")
    print(f"Рабочая директория для PyInstaller будет: {BUILD_SCRIPT_DIR}")

    current_dir_before_pyinstaller = os.getcwd()
    os.chdir(BUILD_SCRIPT_DIR) 
    
    build_successful = False
    try:
        PyInstaller.__main__.run(pyinstaller_args)
        final_exe_path = os.path.join(dist_path_abs, f"{output_exe_name}.exe")
        if os.path.exists(final_exe_path):
            print(f"Сборка завершена успешно! Исполняемый файл: {final_exe_path}")
            build_successful = True
        else:
            print(f"Сборка завершилась, но исполняемый файл не найден: {final_exe_path}")
            
    except SystemExit as e:
        print(f"PyInstaller завершился с ошибкой (SystemExit: {e}). Проверьте лог выше.")
    except Exception as e:
        print(f"Ошибка во время сборки PyInstaller: {e}")
        import traceback
        traceback.print_exc()
    finally:
        os.chdir(current_dir_before_pyinstaller) 
        # Удаляем временную папку сборки build_temp_path_abs после сборки
        if os.path.exists(build_temp_path_abs):
            print(f"Удаление временной папки сборки: {build_temp_path_abs}")
            try:
                shutil.rmtree(build_temp_path_abs)
                print(f"Папка {build_temp_path_abs} успешно удалена.")
            except Exception as e_rm:
                print(f"Не удалось удалить папку {build_temp_path_abs}: {e_rm}")
        else:
            # Если папки нет (например, из-за ошибки PyInstaller на раннем этапе или если --clean ее удалил)
            print(f"Временная папка сборки {build_temp_path_abs} не найдена для удаления или уже удалена.")


if __name__ == '__main__':
    if not os.path.exists(ABS_ICON_FILE_PATH):
        print(f"Ошибка: Файл иконки '{ABS_ICON_FILE_PATH}' не найден."); exit(1)
    if not os.path.exists(ABS_MAIN_SCRIPT_PATH): 
        print(f"Ошибка: Основной скрипт '{ABS_MAIN_SCRIPT_PATH}' не найден."); exit(1)
    if not os.path.exists(ABS_FFMPEG_SOURCE_PATH): 
        print(f"Ошибка: Файл FFmpeg '{ABS_FFMPEG_SOURCE_PATH}' не найден (ожидается в корне проекта)."); exit(1)
    
    build()