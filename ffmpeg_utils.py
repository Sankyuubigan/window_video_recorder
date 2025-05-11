import subprocess
import re
import time
import threading 
import psutil 
from config import FFMPEG_PATH, DEFAULT_FRAMERATE
from config import DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE


def get_dshow_audio_devices(): # (Без изменений)
    devices = []
    command = [FFMPEG_PATH, '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, encoding='utf-8', errors='ignore')
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
            if "Alternative name" in line:
                continue

            match = re.search(device_name_regex, line)
            if match:
                device_name = match.group(2).strip() 
                if not device_name: 
                    continue

                device_type = "unknown" 
                if "(audio)" in line_stripped.lower():
                    device_type = "audio"
                elif "(video)" in line_stripped.lower():
                    device_type = "video"
                elif "(none)" in line_stripped.lower(): 
                    device_type = "none"
                
                if device_type == "unknown" and "video" not in line_stripped.lower() and "none" not in line_stripped.lower():
                    if not any(vid_kw in device_name.lower() for vid_kw in ["camera", "virtual cam", "capture", "screen"]):
                        device_type = "audio" 
                
                if device_type == "audio":
                    if device_name not in devices: 
                        devices.append(device_name)

    except FileNotFoundError:
        print(f"[FFmpegUtils] FFmpeg не найден по пути: {FFMPEG_PATH}")
        return [] 
    except Exception as e:
        print(f"[FFmpegUtils] Ошибка при получении списка аудиоустройств: {e}")
        return []

    unique_sorted_devices = sorted(list(set(d for d in devices if d)))
    print(f"[FFmpegUtils] Финальный отсортированный список уникальных аудиоустройств: {unique_sorted_devices}")
    return unique_sorted_devices


def run_ffmpeg_recording_from_pipe(output_file, 
                                   audio_device_names_list, 
                                   video_width, video_height, video_fps, 
                                   record_audio=True):
                                   
    print(f"[FFmpegUtils] Запуск FFmpeg для приема из pipe: {video_width}x{video_height} @ {video_fps}fps.")
    
    active_audio_devices = [dev for dev in audio_device_names_list if dev] 
    audio_inputs_count = len(active_audio_devices)

    if record_audio and active_audio_devices:
        print(f"[FFmpegUtils] Выбранные аудиоустройства для записи ({audio_inputs_count} шт.): {active_audio_devices}")
    elif record_audio:
        print("[FFmpegUtils] Аудиозапись включена, но нет активных устройств для записи.")
    else:
        print("[FFmpegUtils] Запись аудио отключена.")

    input_pixel_format = 'bgr24' 
    
    dshow_options = [
        '-thread_queue_size', '8192', 
        '-rtbufsize', '256M'      
    ]

    command = [
        FFMPEG_PATH, 
        '-y', 
        '-loglevel', 'verbose',
    ]
        
    command.extend([
        '-f', 'rawvideo',
        '-pix_fmt', input_pixel_format,
        '-s', f'{video_width}x{video_height}',
        '-framerate', str(video_fps), 
        '-i', '-', 
    ])
    
    video_map = "0:v" 
    
    if record_audio and audio_inputs_count > 0 :
        current_ffmpeg_input_index = 1 
        audio_input_streams_for_filter = [] 
        audio_output_labels_from_asetpts = [] 
        
        for i, device_name in enumerate(active_audio_devices):
            print(f"[FFmpegUtils] Добавление аудиовхода {i+1}: '{device_name}'")
            command.extend(dshow_options) 
            command.extend(['-f', 'dshow', '-i', f'audio={device_name}'])
            audio_input_streams_for_filter.append(f"[{current_ffmpeg_input_index}:a]")
            audio_output_labels_from_asetpts.append(f"[aud{i}]")
            current_ffmpeg_input_index += 1
        
        filter_complex_parts = []
        for i in range(audio_inputs_count):
            filter_complex_parts.append(f"{audio_input_streams_for_filter[i]}asetpts=PTS-STARTPTS{audio_output_labels_from_asetpts[i]}")
        
        streams_to_process_further = "".join(audio_output_labels_from_asetpts)
            
        if audio_inputs_count == 1:
            filter_complex_parts.append(f"{audio_output_labels_from_asetpts[0]}acopy[a_out]")
        elif audio_inputs_count > 1:
            weights_str = " ".join(["1"] * audio_inputs_count)
            filter_complex_parts.append(f"{streams_to_process_further}amix=inputs={audio_inputs_count}:duration=first:dropout_transition=2:weights=\"{weights_str}\"[a_out]")
        
        command.extend(['-filter_complex', ";".join(filter_complex_parts)])
        command.extend(['-map', video_map, '-map', '[a_out]']) 
        command.extend([
            '-c:a', DEFAULT_AUDIO_CODEC, 
            '-b:a', DEFAULT_AUDIO_BITRATE,
            '-async', '1', # Возвращаем -async 1 для аудио
            '-ac', '2', 
        ])
    else: 
        print("[FFmpegUtils] Запись будет без звука.")
        command.extend(['-map', video_map, '-an'])

    command.extend([
        '-c:v', 'libx264', 
        '-preset', DEFAULT_VIDEO_PRESET, 
        '-crf', str(DEFAULT_VIDEO_CRF),       
        '-pix_fmt', 'yuv420p', 
        '-r', str(video_fps), 
        '-movflags', 'faststart',
        '-shortest', 
        output_file
    ])

    full_command_str = ' '.join(command)
    print(f"[FFmpegUtils] Команда FFmpeg для записи из pipe: {full_command_str}")
    
    try:
        startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startupinfo.wShowWindow = subprocess.SW_HIDE
        ffmpeg_process = subprocess.Popen(command, startupinfo=startupinfo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
        try:
            p = psutil.Process(ffmpeg_process.pid); p.nice(psutil.HIGH_PRIORITY_CLASS)
            print(f"[FFmpegUtils] Установлен высокий приоритет для процесса FFmpeg (PID: {ffmpeg_process.pid})")
        except Exception as e_priority: print(f"[FFmpegUtils] Не удалось установить приоритет для FFmpeg: {e_priority}")
        return ffmpeg_process
    except FileNotFoundError: print(f"[FFmpegUtils] Ошибка: FFmpeg не найден по пути: {FFMPEG_PATH}."); return None
    except Exception as e: print(f"[FFmpegUtils] Неожиданная ошибка при запуске FFmpeg для pipe: {e}"); return None
