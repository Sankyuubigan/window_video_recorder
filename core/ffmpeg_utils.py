import subprocess
import re
import psutil 
from config import FFMPEG_PATH, DEFAULT_FRAMERATE
from config import DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE

def get_dshow_audio_devices(logger_func=print):
    # ... (код без изменений, оставлен для полноты) ...
    devices = []
    command = [FFMPEG_PATH, '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, encoding='utf-8', errors='ignore')
        stdout_output, stderr_output = "", ""
        try:
            stdout_output, stderr_output = process.communicate(timeout=20) 
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_output, stderr_output = process.communicate()
            logger_func("[FFmpegUtils] FFmpeg -list_devices true -f dshow -i dummy timed out.")
        
        combined_output = stdout_output + "\n" + stderr_output
        device_name_regex = r'([\'"])(.+?)\1' 

        for line in combined_output.splitlines():
            line_stripped = line.strip()
            if "Alternative name" in line: continue
            match = re.search(device_name_regex, line)
            if match:
                device_name = match.group(2).strip() 
                if not device_name: continue
                device_type = "unknown" 
                if "(audio)" in line_stripped.lower(): device_type = "audio"
                elif "(video)" in line_stripped.lower(): device_type = "video"
                
                if device_type == "audio" and device_name not in devices: devices.append(device_name)
    except FileNotFoundError:
        logger_func(f"[FFmpegUtils] FFmpeg не найден по пути: {FFMPEG_PATH}")
        return [] 
    except Exception as e:
        logger_func(f"[FFmpegUtils] Ошибка при получении списка аудиоустройств: {e}")
        return []
    unique_sorted_devices = sorted(list(set(d for d in devices if d)))
    logger_func(f"[FFmpegUtils] Финальный отсортированный список уникальных аудиоустройств: {unique_sorted_devices}")
    return unique_sorted_devices


def run_ffmpeg_direct_window_capture(
    output_file: str, 
    window_title: str,
    audio_device_names_list: list, 
    video_fps: int, 
    record_audio: bool, 
    logger_func=print
):
    logger_func(f"[FFmpegUtils] Запуск FFmpeg для захвата окна '{window_title}' @ {video_fps}fps.")
    
    active_audio_devices = [dev for dev in audio_device_names_list if dev] 
    audio_inputs_count = len(active_audio_devices)

    if record_audio and active_audio_devices:
        logger_func(f"[FFmpegUtils] Выбранные аудиоустройства ({audio_inputs_count} шт.): {active_audio_devices}")
    elif record_audio: logger_func("[FFmpegUtils] Аудиозапись включена, но нет активных устройств.")
    else: logger_func("[FFmpegUtils] Запись аудио отключена.")

    command = [ FFMPEG_PATH, '-y', '-loglevel', 'verbose' ] 
    
    # Опции видеовхода gdigrab
    # Увеличиваем rtbufsize для gdigrab, так как он может требовать большего буфера для стабильной работы.
    video_input_options = [
        '-f', 'gdigrab',
        '-framerate', str(video_fps),
        '-rtbufsize', '512M', # Увеличено с 150M
        '-i', f'title={window_title}',
    ]
    command.extend(video_input_options)
    
    video_filters = f"setpts=PTS-STARTPTS,fps={video_fps},crop=iw:floor(ih/2)*2"

    audio_filter_complex_parts = []
    input_stream_offset = 1 

    if record_audio and audio_inputs_count > 0:
        # Убрали thread_queue_size (пусть FFmpeg использует значение по умолчанию).
        # rtbufsize для dshow оставляем достаточно большим.
        # probesize и analyzeduration немного уменьшены от первоначальных очень больших значений,
        # но все еще достаточно велики для корректного анализа большинства устройств.
        dshow_options = ['-rtbufsize', '256M'] 
        audio_streams_for_final_mix = []

        for i, device_name in enumerate(active_audio_devices):
            current_input_label = f"{input_stream_offset + i}:a"
            command.extend(dshow_options) 
            command.extend(['-probesize', '3M', '-analyzeduration', '3M']) # Изменены с 5M/2.5s и 1M/1M
            command.extend(['-f', 'dshow', '-i', f'audio={device_name}'])
            audio_streams_for_final_mix.append(f"[{current_input_label}]")
        
        processed_audio_labels = []
        for i in range(audio_inputs_count):
            label_after_asetpts = f"[aud_pts{i}]"
            audio_filter_complex_parts.append(f"{audio_streams_for_final_mix[i]}asetpts=PTS-STARTPTS{label_after_asetpts}")
            processed_audio_labels.append(label_after_asetpts)

        streams_to_mix_str = "".join(processed_audio_labels)
        final_audio_label = "[a_out]"

        if audio_inputs_count == 1:
            audio_filter_complex_parts.append(f"{streams_to_mix_str}acopy{final_audio_label}")
        else:
            weights_str = " ".join(["1"] * audio_inputs_count)
            audio_filter_complex_parts.append(f"{streams_to_mix_str}amix=inputs={audio_inputs_count}:duration=first:dropout_transition=3:weights=\"{weights_str}\"{final_audio_label}")
    
    final_filter_complex_str = ""
    if audio_filter_complex_parts: 
        if video_filters:
            final_filter_complex_str = f"[0:v]{video_filters}[v_filt];" + ";".join(audio_filter_complex_parts)
            command.extend(['-map', '[v_filt]', '-map', final_audio_label])
        else: 
            final_filter_complex_str = ";".join(audio_filter_complex_parts)
            command.extend(['-map', '0:v', '-map', final_audio_label]) 
        
        command.extend(['-filter_complex', final_filter_complex_str])
        command.extend(['-c:a', DEFAULT_AUDIO_CODEC, '-b:a', DEFAULT_AUDIO_BITRATE, '-ac', '2'])
        # Убрана опция '-async 1', так как asetpts=PTS-STARTPTS должна корректно обрабатывать синхронизацию аудио.
        # Иногда -async 1 может конфликтовать с другими методами синхронизации.
    elif video_filters: 
        command.extend(['-vf', video_filters])
        command.extend(['-map', '0:v', '-an']) 
    else: 
        command.extend(['-map', '0:v', '-an'])

    command.extend([
        '-c:v', 'libx264', 
        '-preset', DEFAULT_VIDEO_PRESET, 
        '-crf', str(DEFAULT_VIDEO_CRF),       
        '-pix_fmt', 'yuv420p', 
        '-movflags', '+faststart', 
        output_file
    ])

    full_command_str = ' '.join(f'"{c}"' if any(s in c for s in [' ', ':', '=']) and not c.startswith('[') and not c.endswith(']') else c for c in command)
    logger_func(f"[FFmpegUtils] Команда FFmpeg для прямого захвата окна:\n{full_command_str}")
    
    ffmpeg_process = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startupinfo.wShowWindow = subprocess.SW_HIDE
        ffmpeg_process = subprocess.Popen(command, startupinfo=startupinfo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
        if ffmpeg_process and ffmpeg_process.pid:
            try: psutil.Process(ffmpeg_process.pid).nice(psutil.HIGH_PRIORITY_CLASS); logger_func(f"[FFmpegUtils] Установлен высокий приоритет для FFmpeg (PID: {ffmpeg_process.pid})")
            except Exception as e_priority: logger_func(f"[FFmpegUtils] Не удалось установить приоритет: {e_priority}")
        else: logger_func(f"[FFmpegUtils] Не удалось запустить FFmpeg."); return None
    except FileNotFoundError: logger_func(f"[FFmpegUtils] Ошибка: FFmpeg не найден '{FFMPEG_PATH}'."); return None
    except Exception as e_popen: logger_func(f"[FFmpegUtils] Ошибка запуска FFmpeg: {e_popen}"); return None
    return ffmpeg_process