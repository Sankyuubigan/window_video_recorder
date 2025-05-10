import subprocess
import re
import time
import threading 
import psutil 
from config import FFMPEG_PATH, DEFAULT_FRAMERATE
from config import DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE


def get_dshow_audio_devices(): # (без изменений)
    devices = []
    command = [FFMPEG_PATH, '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    try:
        startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startupinfo.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, encoding='utf-8', errors='ignore')
        stdout_output, stderr_output = "", ""
        try: stdout_output, stderr_output = process.communicate(timeout=15)
        except subprocess.TimeoutExpired: process.kill(); stdout_output, stderr_output = process.communicate(); print("[FFmpegUtils] FFmpeg -list_devices true -f dshow -i dummy timed out.")
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
                    if not any(vid_kw in device_name.lower() for vid_kw in ["camera", "virtual cam", "capture", "screen"]): device_type = "audio" 
                if device_type == "audio":
                    if device_name not in devices: devices.append(device_name)
    except FileNotFoundError: print(f"[FFmpegUtils] FFmpeg не найден по пути: {FFMPEG_PATH}")
    except Exception as e: print(f"[FFmpegUtils] Ошибка при получении списка аудиоустройств: {e}")
    unique_sorted_devices = sorted(list(set(d for d in devices if d)))
    print(f"[FFmpegUtils] Финальный отсортированный список уникальных аудиоустройств: {unique_sorted_devices}")
    return unique_sorted_devices


def run_ffmpeg_recording_from_pipe(output_file, mic_device, system_audio_device, 
                                   video_width, video_height, video_fps, record_audio=True):
    print(f"[FFmpegUtils] Запуск FFmpeg для приема из pipe: {video_width}x{video_height} @ {video_fps}fps. Запись аудио: {record_audio}")
    if record_audio:
        print(f"[FFmpegUtils] Микрофон: '{mic_device}', Системный звук: '{system_audio_device}'")

    input_pixel_format = 'bgr24' 

    command = [
        FFMPEG_PATH, '-y', '-loglevel', 'verbose',
        
        '-f', 'rawvideo',
        '-pix_fmt', input_pixel_format,
        '-s', f'{video_width}x{video_height}',
        '-r', str(video_fps),
        '-i', '-',  # Видео из stdin
    ]
    
    # Карта по умолчанию для видео
    video_map = "0:v"
    
    if record_audio and mic_device and system_audio_device:
        command.extend([
            '-thread_queue_size', '1024', 
            '-f', 'dshow', '-i', f'audio={mic_device}',       # Вход 1 (аудио)
            '-thread_queue_size', '1024',
            '-f', 'dshow', '-i', f'audio={system_audio_device}', # Вход 2 (аудио)
            '-filter_complex', "[1:a][2:a]amerge=inputs=2[a_out]",
            '-map', video_map,      # Видео из входа 0
            '-map', '[a_out]',  # Аудио из фильтра
        ])
        command.extend([
            '-c:a', DEFAULT_AUDIO_CODEC, 
            '-b:a', DEFAULT_AUDIO_BITRATE,
        ])
        # Добавляем -shortest, если есть аудиоисточники, которые могут быть "бесконечными"
        command.append('-shortest') 
    else: 
        command.extend(['-map', video_map])
        if not record_audio:
            command.append('-an') 

    command.extend([
        '-c:v', 'libx264', 
        '-preset', DEFAULT_VIDEO_PRESET, 
        '-crf', str(DEFAULT_VIDEO_CRF),       
        '-pix_fmt', 'yuv420p', # Важный параметр для совместимости MP4
        '-r', str(video_fps), # Убедимся, что выходная частота кадров тоже указана
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
