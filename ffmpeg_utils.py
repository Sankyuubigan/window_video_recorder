import subprocess
import re
import time
import threading 
import psutil 
from config import FFMPEG_PATH, DEFAULT_FRAMERATE, DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE

def get_dshow_audio_devices():
    # (Без изменений)
    devices = []
    command = [FFMPEG_PATH, '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, 
            startupinfo=startupinfo, encoding='utf-8', errors='ignore'
        )
        stdout_output, stderr_output = "", ""
        try:
            stdout_output, stderr_output = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_output, stderr_output = process.communicate()
            print("[FFmpegUtils] FFmpeg -list_devices true -f dshow -i dummy timed out.")
        
        combined_output = stdout_output + "\n" + stderr_output
        device_name_regex = r'([\'"])(.+?)\1'
        
        for line_num, line in enumerate(combined_output.splitlines()):
            line_stripped = line.strip()
            if "Alternative name" in line: continue
            match = re.search(device_name_regex, line)
            if match:
                device_name = match.group(2).strip()
                if not device_name: continue
                device_type = "unknown" 
                if "(audio)" in line_stripped.lower(): device_type = "audio"
                elif "(video)" in line_stripped.lower(): device_type = "video"
                elif "(none)" in line_stripped.lower(): device_type = "none"
                if device_type == "unknown" and "video" not in line_stripped.lower() and "none" not in line_stripped.lower():
                    if not any(vid_kw in device_name.lower() for vid_kw in ["camera", "virtual cam", "capture", "screen"]):
                        device_type = "audio" 
                if device_type == "audio":
                    if device_name not in devices: devices.append(device_name)
    except FileNotFoundError:
        print(f"[FFmpegUtils] FFmpeg не найден по пути: {FFMPEG_PATH}")
    except Exception as e:
        print(f"[FFmpegUtils] Ошибка при получении списка аудиоустройств: {e}")
    unique_sorted_devices = sorted(list(set(d for d in devices if d)))
    print(f"[FFmpegUtils] Финальный отсортированный список уникальных аудиоустройств: {unique_sorted_devices}")
    return unique_sorted_devices


def run_ffmpeg_recording(window_title, output_file, mic_device, system_audio_device, stop_event_ref):
    print(f"[FFmpegUtils] Начало записи FFmpeg: Окно='{window_title}', Файл='{output_file}'")
    print(f"[FFmpegUtils] Микрофон: '{mic_device}', Системный звук: '{system_audio_device}'")

    video_filter = "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"

    command = [
        FFMPEG_PATH, '-y', '-loglevel', 'verbose', 
        
        # Опции для gdigrab (видеовход)
        '-thread_queue_size', '1024', # Увеличиваем очередь для входного потока gdigrab
        '-rtbufsize', '500M',         # Увеличиваем буфер реального времени
        '-f', 'gdigrab', 
        '-framerate', str(DEFAULT_FRAMERATE), 
        # '-vsync', 'cfr', # Попробуем сначала без этого, потом с этим, если thread_queue_size не поможет
        '-i', f'title={window_title}',
        
        # Аудиовход 1 (микрофон)
        '-thread_queue_size', '512', # Очередь для аудиовхода
        '-f', 'dshow', 
        '-i', f'audio={mic_device}',
        
        # Аудиовход 2 (системные звуки)
        '-thread_queue_size', '512', # Очередь для аудиовхода
        '-f', 'dshow', 
        '-i', f'audio={system_audio_device}',
        
        # Фильтры
        '-filter_complex', f"[0:v]{video_filter}[v_scaled];[1:a][2:a]amerge=inputs=2[a_out]",
        
        # Маппинг
        '-map', '[v_scaled]', 
        '-map', '[a_out]',
        
        # Кодеки и параметры
        '-c:v', 'libx264', '-preset', DEFAULT_VIDEO_PRESET, '-crf', DEFAULT_VIDEO_CRF, '-pix_fmt', 'yuv420p',
        '-c:a', DEFAULT_AUDIO_CODEC, '-b:a', DEFAULT_AUDIO_BITRATE,
        # '-max_interleave_delta', '0', # Иногда помогает с синхронизацией, но может вызвать другие проблемы
        output_file
    ]
    full_command_str = ' '.join(command)
    print(f"[FFmpegUtils] Команда FFmpeg для записи: {full_command_str}")
    
    live_stdout_lines = []
    live_stderr_lines = []
    
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        ffmpeg_process = subprocess.Popen(command, startupinfo=startupinfo,
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                             text=True, encoding='utf-8', errors='ignore', bufsize=1)
        
        try:
            p = psutil.Process(ffmpeg_process.pid)
            p.nice(psutil.HIGH_PRIORITY_CLASS)
            print(f"[FFmpegUtils] Установлен высокий приоритет для процесса FFmpeg (PID: {ffmpeg_process.pid})")
        except Exception as e_priority:
            print(f"[FFmpegUtils] Не удалось установить приоритет для FFmpeg: {e_priority}")

        def log_stream(stream, stream_name, line_buffer):
            try:
                for line in iter(stream.readline, ''):
                    if not line: break
                    line = line.strip(); print(f"[FFmpegLive-{stream_name}] {line}"); line_buffer.append(line)
                stream.close()
            except Exception as e: print(f"[FFmpegUtils] Ошибка при чтении потока {stream_name}: {e}")

        stdout_thread = threading.Thread(target=log_stream, args=(ffmpeg_process.stdout, "STDOUT", live_stdout_lines), daemon=True)
        stderr_thread = threading.Thread(target=log_stream, args=(ffmpeg_process.stderr, "STDERR", live_stderr_lines), daemon=True)
        stdout_thread.start(); stderr_thread.start()
        
        while ffmpeg_process.poll() is None and not stop_event_ref[0].is_set():
            time.sleep(0.1)

        final_stdout, final_stderr, return_code = "", "", -1 

        if stop_event_ref[0].is_set(): 
            print("[FFmpegUtils] Получен сигнал остановки. Отправка 'q' в FFmpeg...")
            if ffmpeg_process.poll() is None: 
                try:
                    ffmpeg_process.stdin.write('q\n'); ffmpeg_process.stdin.flush(); ffmpeg_process.stdin.close()
                    print("[FFmpegUtils] Ожидание завершения FFmpeg после 'q'...")
                    ffmpeg_process.wait(timeout=10) 
                except (OSError, ValueError, BrokenPipeError) as e: 
                    print(f"[FFmpegUtils] Ошибка при отправке 'q' или закрытии stdin: {e}")
                    if ffmpeg_process.poll() is None: print("[FFmpegUtils] FFmpeg не ответил на 'q', принудительно убиваем."); ffmpeg_process.kill()
                except subprocess.TimeoutExpired:
                    print("[FFmpegUtils] FFmpeg не завершился вовремя после 'q', принудительно убиваем.")
                    if ffmpeg_process.poll() is None: ffmpeg_process.kill()
            print("[FFmpegUtils] FFmpeg остановлен (или был остановлен).")
            if ffmpeg_process.poll() is not None: return_code = ffmpeg_process.returncode
            else: return_code = -9 
        
        elif ffmpeg_process.poll() is not None: 
             return_code = ffmpeg_process.returncode
        
        stdout_thread.join(timeout=1); stderr_thread.join(timeout=1)
        final_stdout = "\n".join(live_stdout_lines)
        final_stderr = "\n".join(live_stderr_lines)

        if hasattr(ffmpeg_process, 'stdout') and ffmpeg_process.stdout and not ffmpeg_process.stdout.closed:
            try: final_stdout += "\n[COMMUNICATE STDOUT]\n" + ffmpeg_process.stdout.read()
            except: pass
        if hasattr(ffmpeg_process, 'stderr') and ffmpeg_process.stderr and not ffmpeg_process.stderr.closed:
            try: final_stderr += "\n[COMMUNICATE STDERR]\n" + ffmpeg_process.stderr.read()
            except: pass

        print(f"[FFmpegUtils] FFmpeg окончательно завершился. Код: {return_code}")
        return {"return_code": return_code, "stdout": final_stdout, "stderr": final_stderr}

    except FileNotFoundError:
        return {"return_code": -99, "stderr": f"FFmpeg не найден по пути: {FFMPEG_PATH}."}
    except Exception as e:
        print(f"[FFmpegUtils] Неожиданная ошибка при запуске/работе FFmpeg: {e}")
        return {"return_code": -100, "stderr": f"Неожиданная ошибка при запуске FFmpeg: {e}"}
