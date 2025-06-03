import numpy as np
import cv2 
import threading
import time
import os
import win32gui
import win32con
import subprocess 
import signal
import tempfile 

from config import DEFAULT_FRAMERATE, FFMPEG_PATH, NO_AUDIO_DEVICE_SELECTED
from config import DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE
from window_utils import WindowFrameGrabberGDI 

# Флаг для отладки - не удалять временные файлы
DEBUG_KEEP_TEMP_FILES = True # Установите в True для отладки звука

class FFmpegRecorder:
    def __init__(self, hwnd, output_file, audio_device_names_list, framerate, logger_func, on_critical_error_callback=None):
        self.hwnd = hwnd
        self.final_output_file = output_file 
        self.audio_device_names_list = audio_device_names_list if audio_device_names_list else []
        self.framerate = framerate if framerate > 0 else DEFAULT_FRAMERATE
        self.logger = logger_func
        self.on_critical_error_callback = on_critical_error_callback
        
        self.frame_grabber = None 
        self.ffmpeg_video_process = None 
        self.ffmpeg_audio_processes_list = [] 
        self.temp_audio_files_list = []       

        self._stop_event = threading.Event()
        self._video_recording_thread = None 
        
        self.temp_video_file = ""
        
        self.is_recording = False
        self.accumulated_error_messages = [] 
        self.frames_written_count = 0 

    def get_frames_written(self):
        return self.frames_written_count

    def _add_error_message(self, message, is_critical=False):
        if message:
            self.accumulated_error_messages.append(message)
            log_prefix = "[FFmpegRecorder CRITICAL ERROR]" if is_critical else "[FFmpegRecorder ERROR]"
            self.logger(f"{log_prefix} {message}")
            if is_critical and self.on_critical_error_callback:
                self.logger(f"[FFmpegRecorder] Вызов on_critical_error_callback из-за: {message}")
                try: self.on_critical_error_callback(message)
                except Exception as e_cb: self.logger(f"[FFmpegRecorder] Ошибка при вызове on_critical_error_callback: {e_cb}")

    def _initialize_grabber(self):
        # ... (без изменений) ...
        if not (self.hwnd and win32gui.IsWindow(self.hwnd)):
            self.accumulated_error_messages.append("HWND окна недействителен или окно закрыто."); return False
        if win32gui.IsIconic(self.hwnd): 
            self.logger(f"[FFmpegRecorder] Окно {self.hwnd} свернуто, попытка восстановления...")
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE); time.sleep(0.5) 
            if not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd):
                self.accumulated_error_messages.append("Не удалось восстановить свернутое окно."); return False
            self.logger(f"[FFmpegRecorder] Окно {self.hwnd} восстановлено.")
        try:
            self.frame_grabber = WindowFrameGrabberGDI(self.hwnd, self.logger)
            if not self.frame_grabber.is_initialized or self.frame_grabber.width <= 0 or self.frame_grabber.height <= 0:
                w_val = self.frame_grabber.width if self.frame_grabber else "N/A"
                h_val = self.frame_grabber.height if self.frame_grabber else "N/A"
                self.accumulated_error_messages.append(f"GDI граббер: ошибка инициализации/размеров (w={w_val}, h={h_val}).")
                if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
                return False
            self.logger(f"[FFmpegRecorder] GDI граббер инициализирован: {self.frame_grabber.width}x{self.frame_grabber.height}")
            return True
        except Exception as e:
            self.accumulated_error_messages.append(f"Ошибка WindowFrameGrabberGDI: {e}"); import traceback; self.logger(traceback.format_exc())
            if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
            return False

    def _build_ffmpeg_video_command(self, width, height, temp_video_path):
        # ... (без изменений) ...
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-nostdin', '-threads', '1', '-hide_banner', '-loglevel', 'error'])
        command.extend(['-fflags', '+genpts', '-f', 'rawvideo', '-pix_fmt', 'bgr24', 
                        '-s', f'{width}x{height}', '-r', str(self.framerate), '-i', 'pipe:0'])
        command.extend(['-c:v', 'libx264', '-preset', DEFAULT_VIDEO_PRESET, '-crf', str(DEFAULT_VIDEO_CRF)])
        command.extend(['-pix_fmt', 'yuv420p', '-an']) 
        command.extend([temp_video_path, '-y'])
        return command

    def _build_ffmpeg_audio_command(self, audio_device_name, temp_audio_path):
        if not audio_device_name or audio_device_name == NO_AUDIO_DEVICE_SELECTED:
            return None 
        
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        # Изменяем loglevel на info для аудио, чтобы видеть больше вывода от FFmpeg
        command.extend(['-nostdin', '-threads', '1', '-nostats', '-hide_banner', '-loglevel', 'info']) 
        command.extend(['-f', 'dshow', '-guess_layout_max', '0', '-i', f'audio={audio_device_name}'])
        command.extend(['-af', 'asetpts=PTS-STARTPTS']) 
        command.extend(['-c:a', DEFAULT_AUDIO_CODEC, '-b:a', DEFAULT_AUDIO_BITRATE, '-ar', '44100', '-ac', '2'])
        command.extend([temp_audio_path, '-y'])
        return command

    def _build_ffmpeg_mux_command(self, temp_video_path, temp_audio_files_list, final_output_path):
        # ... (без изменений) ...
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-hide_banner', '-loglevel', 'error']) 
        command.extend(['-i', temp_video_path]) 
        valid_temp_audio_files = [f for f in temp_audio_files_list if f and os.path.exists(f) and os.path.getsize(f) > 0]
        for audio_file_path in valid_temp_audio_files: command.extend(['-i', audio_file_path]) 
        map_video_option = "-map 0:v"; audio_codec_option = ['-c:a', DEFAULT_AUDIO_CODEC] 
        if not valid_temp_audio_files:
            command.extend(['-c:v', 'copy', '-an']); command.extend([map_video_option])
        else:
            command.extend(['-c:v', 'copy']) 
            if len(valid_temp_audio_files) == 1:
                command.extend(['-c:a', 'copy']); command.extend([map_video_option, "-map 1:a"]) 
            else: 
                filter_complex_str = ""
                for i in range(len(valid_temp_audio_files)): filter_complex_str += f"[{i+1}:a]" 
                weights_str = " ".join(["1"] * len(valid_temp_audio_files))
                filter_complex_str += f"amix=inputs={len(valid_temp_audio_files)}:duration=longest:dropout_transition=2:weights='{weights_str}'[a_out]"
                command.extend(['-filter_complex', filter_complex_str])
                command.extend([map_video_option, "-map [a_out]"]); command.extend(audio_codec_option) 
        command.extend(['-shortest']); command.extend(['-movflags', '+faststart']); command.extend([final_output_path, '-y'])
        return command

    def start(self):
        # ... (без изменений)
        self.logger("[FFmpegRecorder] Попытка запуска раздельной записи видео и аудио...")
        if self.is_recording: self.logger("[FFmpegRecorder] Запись уже идет."); return True, None
        self.frames_written_count = 0; self.accumulated_error_messages = [] 
        self.ffmpeg_audio_processes_list = []; self.temp_audio_files_list = []
        if not self._initialize_grabber(): 
            final_err_msg = "; ".join(self.accumulated_error_messages) if self.accumulated_error_messages else "Ошибка инициализации граббера"
            self.logger(f"[FFmpegRecorder] Отмена запуска: {final_err_msg}"); return False, final_err_msg
        self._stop_event.clear()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', prefix='_rec_vid_') as f_vid: self.temp_video_file = f_vid.name
            if os.path.exists(self.temp_video_file): os.remove(self.temp_video_file)
        except Exception as e_temp_vid:
            self._add_error_message(f"Ошибка создания временного видеофайла: {e_temp_vid}", is_critical=True)
            return False, "; ".join(self.accumulated_error_messages)
        for i, _ in enumerate(self.audio_device_names_list):
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.aac', prefix=f'_rec_aud_{i}_') as f_aud: temp_path = f_aud.name
                if os.path.exists(temp_path): os.remove(temp_path)
                self.temp_audio_files_list.append(temp_path)
            except Exception as e_temp_aud:
                self._add_error_message(f"Ошибка создания временного аудиофайла {i}: {e_temp_aud}", is_critical=True)
                self._cleanup_temp_files(); return False, "; ".join(self.accumulated_error_messages)
        try: 
            video_cmd_list = self._build_ffmpeg_video_command(self.frame_grabber.width, self.frame_grabber.height, self.temp_video_file)
            self.logger(f"[FFmpegRecorder] Видео команда: {' '.join(video_cmd_list)}")
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            self.ffmpeg_video_process = subprocess.Popen(video_cmd_list, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags, bufsize=0)
            self.logger(f"[FFmpegRecorder] FFmpeg ВИДЕО процесс запущен (PID: {self.ffmpeg_video_process.pid}).")
        except Exception as e_start_vid:
            self._add_error_message(f"Ошибка при запуске видеопроцесса ffmpeg: {e_start_vid}", is_critical=True)
            self._cleanup_temp_files(); return False, "; ".join(self.accumulated_error_messages)
        if self.audio_device_names_list:
            for i, device_name in enumerate(self.audio_device_names_list):
                temp_audio_file_for_device = self.temp_audio_files_list[i]
                audio_cmd_list = self._build_ffmpeg_audio_command(device_name, temp_audio_file_for_device)
                if audio_cmd_list:
                    self.logger(f"[FFmpegRecorder] Аудио команда [{i}] для '{device_name}': {' '.join(audio_cmd_list)}")
                    try:
                        # Для аудиопроцесса будем читать и stdout, и stderr
                        audio_proc = subprocess.Popen(audio_cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                        self.ffmpeg_audio_processes_list.append(audio_proc)
                        self.logger(f"[FFmpegRecorder] FFmpeg АУДИО процесс [{i}] запущен (PID: {audio_proc.pid}) для '{device_name}'.")
                    except Exception as e_start_aud:
                        self._add_error_message(f"Ошибка запуска аудиопроцесса [{i}] для '{device_name}': {e_start_aud}", is_critical=True)
                        self._cleanup_ffmpeg_processes(force_kill=True); self._cleanup_temp_files()
                        if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
                        return False, "; ".join(self.accumulated_error_messages)
        self.is_recording = True
        self._video_recording_thread = threading.Thread(target=self._video_feed_loop, daemon=True)
        self._video_recording_thread.start()
        self.logger("[FFmpegRecorder] Поток передачи видеокадров запущен.")
        return True, None 
    
    def _read_ffmpeg_pipe(self, pipe, pipe_name_prefix, stop_event_local=None):
        # ... (без изменений)
        try:
            while True:
                if stop_event_local and stop_event_local.is_set() and pipe.closed: break 
                line_bytes = pipe.readline() 
                if not line_bytes: break 
                line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                if line_str: self.logger(f"[{pipe_name_prefix}] {line_str}")
        except Exception: pass 
        finally:
            if hasattr(pipe, 'close') and not pipe.closed: 
                try: pipe.close()
                except: pass

    def _video_feed_loop(self):
        # ... (без изменений)
        self.logger("[FFmpegRecorder] Начало цикла передачи видеокадров...")
        frames_written_in_loop_local = 0; start_time_loop_overall = time.time() 
        loop_internal_error_msg_obj = {"msg": None}; vid_stderr_thread = None
        if self.ffmpeg_video_process and self.ffmpeg_video_process.stderr:
            vid_stderr_thread = threading.Thread(target=self._read_ffmpeg_pipe, args=(self.ffmpeg_video_process.stderr, "FFmpegVideo-stderr", self._stop_event), daemon=True)
            vid_stderr_thread.start()
        time_per_frame = 1.0 / self.framerate
        try:
            if not self.frame_grabber or not self.frame_grabber.is_initialized:
                loop_internal_error_msg_obj["msg"] = "GDI граббер не инициализирован перед видео циклом."
                raise RuntimeError(loop_internal_error_msg_obj["msg"])
            expected_w = self.frame_grabber.width; expected_h = self.frame_grabber.height
            last_frame_target_time = time.time() 
            while True: 
                if self._stop_event.is_set(): self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (начало цикла), выход."); break
                current_iteration_start_time = time.time()
                if not (self.hwnd and win32gui.IsWindow(self.hwnd)): 
                    loop_internal_error_msg_obj["msg"] = "Окно захвата закрыто (видеоцикл)."; break 
                if self.ffmpeg_video_process.poll() is not None: 
                    poll_code = self.ffmpeg_video_process.poll()
                    loop_internal_error_msg_obj["msg"] = f"FFmpeg видео завершился (код: {poll_code})."
                    if poll_code == 0 and self.ffmpeg_video_process.stdin and not self.ffmpeg_video_process.stdin.closed:
                         loop_internal_error_msg_obj["msg"] += " (stdin еще был открыт)"
                    break 
                if not self.ffmpeg_video_process.stdin or self.ffmpeg_video_process.stdin.closed: 
                    loop_internal_error_msg_obj["msg"] = "FFmpeg видео stdin закрыт (неожиданно)."; break 
                frame_bgr = self.frame_grabber.grab_frame()
                if self._stop_event.is_set(): self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (после grab_frame), выход."); break 
                if frame_bgr is None:
                    if not self.frame_grabber.is_initialized: 
                        loop_internal_error_msg_obj["msg"] = "GDI граббер неинициализирован (видеоцикл)."; break 
                    time_to_next_tick = last_frame_target_time + time_per_frame - time.time()
                    if time_to_next_tick > 0.001: time.sleep(min(time_to_next_tick, 0.01))
                    if self._stop_event.is_set(): break
                    continue 
                fh, fw, _ = frame_bgr.shape
                if fw != expected_w or fh != expected_h: 
                    loop_internal_error_msg_obj["msg"] = f"Размер кадра ({fw}x{fh}) != ({expected_w}x{expected_h})."; break 
                try:
                    self.ffmpeg_video_process.stdin.write(frame_bgr.tobytes())
                    frames_written_in_loop_local += 1
                    self.frames_written_count = frames_written_in_loop_local 
                except (IOError, BrokenPipeError) as e_pipe: 
                    loop_internal_error_msg_obj["msg"] = f"Видео Pipe error: {e_pipe}"; break 
                except Exception as e_write: 
                    loop_internal_error_msg_obj["msg"] = f"Видео Stdin write error: {e_write}"; break 
                last_frame_target_time += time_per_frame
                current_time_after_send = time.time()
                sleep_duration = last_frame_target_time - current_time_after_send
                if sleep_duration > 0:
                    sleep_chunk = 0.005; end_sleep_time = current_time_after_send + sleep_duration
                    while time.time() < end_sleep_time:
                        if self._stop_event.is_set(): break
                        actual_sleep_this_chunk = min(sleep_chunk, end_sleep_time - time.time())
                        if actual_sleep_this_chunk <=0: break
                        time.sleep(actual_sleep_this_chunk)
                if self._stop_event.is_set(): self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (после сна), выход."); break
                if time.time() > last_frame_target_time + time_per_frame : last_frame_target_time = time.time()
        except RuntimeError : pass 
        except Exception as e_generic_loop: 
             if not loop_internal_error_msg_obj["msg"]: loop_internal_error_msg_obj["msg"] = f"Неожиданная ошибка в видеоцикле: {e_generic_loop}"
             import traceback; self.logger(traceback.format_exc())
        finally:
            self.logger("[FFmpegRecorder] Цикл передачи видеокадров завершается.")
            self.frames_written_count = frames_written_in_loop_local 
            if loop_internal_error_msg_obj["msg"]: self._add_error_message(loop_internal_error_msg_obj["msg"], is_critical=True) 
            if self.ffmpeg_video_process and self.ffmpeg_video_process.stdin and not self.ffmpeg_video_process.stdin.closed:
                self.logger("[FFmpegRecorder] Закрытие stdin видеопроцесса FFmpeg (из finally)...")
                try: 
                    self.ffmpeg_video_process.stdin.flush(); self.ffmpeg_video_process.stdin.close()
                    self.logger("[FFmpegRecorder] stdin видеопроцесса FFmpeg успешно закрыт (из finally).")
                except Exception as e_close_stdin_finally: self.logger(f"[FFmpegRecorder] Ошибка при закрытии stdin (finally): {e_close_stdin_finally}")
            if vid_stderr_thread and vid_stderr_thread.is_alive(): 
                vid_stderr_thread.join(timeout=2.0) 
                if vid_stderr_thread.is_alive(): self.logger("[FFmpegRecorder] Поток чтения stderr видео не завершился.")
        actual_duration_of_loop = time.time() - start_time_loop_overall
        if self.frames_written_count > 0 : 
            avg_fps_sent_actual = self.frames_written_count / actual_duration_of_loop if actual_duration_of_loop > 0.01 else self.framerate
            self.logger(f"[FFmpegRecorder] Видеоцикл: {self.frames_written_count} кадров за {actual_duration_of_loop:.2f}с. (Отправлено ~{avg_fps_sent_actual:.1f} FPS).")
        elif actual_duration_of_loop > 0.1 : self.logger(f"[FFmpegRecorder] Видеоцикл: 0 кадров за {actual_duration_of_loop:.2f}с.")

    def _stop_ffmpeg_process(self, process, process_name, timeout_graceful=3, timeout_signal=7, timeout_terminate=3, is_audio=False, audio_file_path_for_check=None):
        # ... (без изменений)
        if not process: return
        return_code = process.poll(); process_final_stderr_content = ""
        stderr_reader_thread_stop = None; pipe_to_read_stop = process.stderr
        # Передаем self._stop_event в _read_ffmpeg_pipe для аудио процессов тоже,
        # чтобы они могли быстрее завершиться, если основной stop вызван.
        # stderr_stop_event_for_reader = self._stop_event if is_audio else stop_stderr_event_local_stop (ошибка, нужна одна переменная)
        # Будем использовать stop_stderr_event_local_stop для всех потоков чтения здесь
        stderr_buffer_local_stop = []; stop_stderr_event_local_stop = threading.Event()
        
        if pipe_to_read_stop and not pipe_to_read_stop.closed:
            # Запускаем отдельный поток для чтения stdout и stderr аудиопроцесса
            # stderr видео читается в _video_feed_loop
            # stdout аудио мы не читали, но для полноты можно добавить
            if is_audio and process.stdout and not process.stdout.closed:
                 audio_stdout_thread = threading.Thread(target=self._read_ffmpeg_pipe, 
                                                        args=(process.stdout, f"{process_name}-stdout", stop_stderr_event_local_stop), 
                                                        daemon=True)
                 audio_stdout_thread.start()
            
            stderr_reader_thread_stop = threading.Thread(target=self._read_ffmpeg_pipe, 
                                                         args=(pipe_to_read_stop, f"{process_name}-stderr", stop_stderr_event_local_stop), 
                                                         daemon=True)
            stderr_reader_thread_stop.start()

        if return_code is None: 
            self.logger(f"[FFmpegRecorder] {process_name} активен. Попытка корректного завершения...")
            if process_name == "FFmpegVideo" and process.stdin and not process.stdin.closed:
                self.logger(f"[FFmpegRecorder] Внимание: stdin {process_name} не закрыт до _stop_ffmpeg_process. Закрытие...")
                try: process.stdin.close()
                except: pass
            try: 
                process.wait(timeout=timeout_graceful)
                return_code = process.returncode 
                self.logger(f"[FFmpegRecorder] {process_name} завершился после wait({timeout_graceful}s) с кодом {return_code}.")
            except subprocess.TimeoutExpired:
                self.logger(f"[FFmpegRecorder] {process_name} не завершился за {timeout_graceful}s. SIGINT/CTRL_C...")
                try: 
                    if os.name == 'nt': process.send_signal(signal.CTRL_C_EVENT)
                    else: process.send_signal(signal.SIGINT)
                    process.wait(timeout=timeout_signal) 
                    return_code = process.returncode
                    self.logger(f"[FFmpegRecorder] {process_name} завершился после сигнала с кодом {return_code}.")
                except subprocess.TimeoutExpired:
                    self.logger(f"[FFmpegRecorder] {process_name} не завершился после сигнала за {timeout_signal}s. Terminate()...")
                    process.terminate()
                    try: process.wait(timeout=timeout_terminate) 
                    except subprocess.TimeoutExpired: 
                        process.kill(); self.logger(f"[FFmpegRecorder] {process_name} убит (kill).")
                    return_code = process.poll() 
                    if not (is_audio and return_code == 1): self._add_error_message(f"{process_name} принудительно завершен.")
                    self.logger(f"[FFmpegRecorder] {process_name} завершен после kill/terminate с кодом {return_code}.")
                except Exception as e_signal_wait: 
                    self._add_error_message(f"Ошибка сигнала/ожидания для {process_name}: {e_signal_wait}")
                    try: process.kill(); return_code = process.poll()
                    except: pass
        else: self.logger(f"[FFmpegRecorder] {process_name} уже был завершен с кодом {return_code}.")
        
        # Останавливаем потоки чтения и ждем их завершения
        stop_stderr_event_local_stop.set() 
        if stderr_reader_thread_stop and stderr_reader_thread_stop.is_alive(): stderr_reader_thread_stop.join(timeout=1.0)
        if is_audio and 'audio_stdout_thread' in locals() and audio_stdout_thread.is_alive(): audio_stdout_thread.join(timeout=1.0)

        # Собираем stderr уже после того, как потоки чтения завершились или были прерваны
        if stderr_buffer_local_stop: process_final_stderr_content = "".join(stderr_buffer_local_stop).strip()
        
        if process_final_stderr_content: self.logger(f"[FFmpegRecorder] {process_name} Stderr (полный лог при остановке):\n{process_final_stderr_content}")
        if return_code is not None and return_code != 0:
            is_killed_audio_ok = is_audio and return_code == 1 and audio_file_path_for_check and os.path.exists(audio_file_path_for_check) and os.path.getsize(audio_file_path_for_check) > 0
            if not is_killed_audio_ok:
                err_msg = f"{process_name} завершился с ошибкой (код {return_code})."
                if process_final_stderr_content: 
                    stderr_preview = (process_final_stderr_content[:100] + '...') if len(process_final_stderr_content) > 100 else process_final_stderr_content
                    err_msg += f" Stderr: {stderr_preview}"
                self._add_error_message(err_msg)
            else: self.logger(f"[FFmpegRecorder] {process_name} (аудио) завершился с кодом {return_code}, но временный файл аудио {os.path.basename(audio_file_path_for_check) if audio_file_path_for_check else ''} существует. Не рассматривается как ошибка.")
        if pipe_to_read_stop and not pipe_to_read_stop.closed:
            try: pipe_to_read_stop.close()
            except: pass
        
    def _mux_files(self):
        # ... (без изменений)
        self.logger("[FFmpegRecorder] Попытка объединения временных файлов...")
        if not os.path.exists(self.temp_video_file) or os.path.getsize(self.temp_video_file) == 0:
            err_msg = "Временный видеофайл отсутствует или пуст. Объединение невозможно."
            self._add_error_message(err_msg, is_critical=True); return False 
        valid_temp_audio_files = [f for f in self.temp_audio_files_list if f and os.path.exists(f) and os.path.getsize(f) > 0]
        mux_cmd_list = self._build_ffmpeg_mux_command(self.temp_video_file, valid_temp_audio_files, self.final_output_file)
        self.logger(f"[FFmpegRecorder] Mux команда: {' '.join(mux_cmd_list)}")
        try:
            mux_process_result = subprocess.run(mux_cmd_list, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
            if mux_process_result.returncode != 0:
                mux_stderr_output = mux_process_result.stderr.strip() if mux_process_result.stderr else "Нет вывода stderr от mux"
                err_msg = f"Ошибка объединения файлов (FFmpeg код {mux_process_result.returncode}). Stderr: {mux_stderr_output}"
                self._add_error_message(err_msg, is_critical=True); return False 
            self.logger("[FFmpegRecorder] Файлы успешно объединены.")
            return True 
        except Exception as e_mux_run: 
            err_msg = f"Исключение при выполнении команды объединения файлов: {e_mux_run}"
            self._add_error_message(err_msg, is_critical=True); return False

    def _cleanup_temp_files(self):
        if DEBUG_KEEP_TEMP_FILES:
            self.logger("[FFmpegRecorder] DEBUG_KEEP_TEMP_FILES=True, временные файлы не удалены.")
            self.logger(f"  Видео: {self.temp_video_file}")
            for i, f_path in enumerate(self.temp_audio_files_list):
                self.logger(f"  Аудио[{i}]: {f_path}")
            return

        files_to_delete = [self.temp_video_file] + self.temp_audio_files_list
        for f_path in files_to_delete:
            if f_path and os.path.exists(f_path):
                try: 
                    os.remove(f_path)
                    self.logger(f"[FFmpegRecorder] Удален временный файл: {f_path}")
                except OSError as e_os: 
                    self.logger(f"[FFmpegRecorder] Не удалось удалить временный файл {f_path} (OSError): {e_os}")
                except Exception as e_gen: 
                    self.logger(f"[FFmpegRecorder] Ошибка при удалении временного файла {f_path}: {e_gen}")
        self.temp_video_file = ""; self.temp_audio_files_list = []
        
    def _cleanup_ffmpeg_processes(self, force_kill=False):
        # ... (без изменений)
        processes_to_clean = []
        if self.ffmpeg_video_process and self.ffmpeg_video_process.poll() is None: processes_to_clean.append(("FFmpegVideo", self.ffmpeg_video_process))
        for i, proc in enumerate(self.ffmpeg_audio_processes_list):
            if proc and proc.poll() is None: processes_to_clean.append((f"FFmpegAudio[{i}]", proc))
        for name, proc in processes_to_clean:
            if force_kill: self.logger(f"[FFmpegRecorder] Экстренная очистка (kill): {name} (PID: {proc.pid}).")
            try: proc.kill()
            except Exception as e_kill: self.logger(f"[FFmpegRecorder] Ошибка при kill() {name}: {e_kill}")
        if processes_to_clean: self.ffmpeg_video_process = None; self.ffmpeg_audio_processes_list = []


    def stop(self):
        # ... (без изменений)
        self.logger(f"[FFmpegRecorder] Команда stop получена (is_recording: {self.is_recording}).")
        if not self.is_recording: 
            self.logger("[FFmpegRecorder] Запись не была активна (is_recording=False при вызове stop).")
            return "; ".join(self.accumulated_error_messages) if self.accumulated_error_messages else None
        self.logger(f"[FFmpegRecorder] Установка _stop_event (время: {time.time():.3f}).")
        self._stop_event.set() 
        if self._video_recording_thread and self._video_recording_thread.is_alive():
            self.logger("[FFmpegRecorder] Ожидание завершения потока _video_feed_loop...")
            self._video_recording_thread.join(timeout=3.0) 
            if self._video_recording_thread.is_alive(): self.logger("[FFmpegRecorder] ВНИМАНИЕ: Поток _video_feed_loop не завершился за 3с.")
            else: self.logger("[FFmpegRecorder] Поток _video_feed_loop завершен.")
        self._video_recording_thread = None 
        if self.frame_grabber: 
            self.logger("[FFmpegRecorder] Закрытие frame_grabber...")
            try: self.frame_grabber.close(); self.logger("[FFmpegRecorder] Frame grabber закрыт.")
            except Exception as e_close_grabber: self.logger(f"[FFmpegRecorder] Ошибка при закрытии frame_grabber: {e_close_grabber}")
            self.frame_grabber = None
        self.logger("[FFmpegRecorder] Остановка видеопроцесса FFmpeg...")
        self._stop_ffmpeg_process(self.ffmpeg_video_process, "FFmpegVideo", timeout_graceful=2, timeout_signal=5, timeout_terminate=2)
        self.ffmpeg_video_process = None 
        for i, audio_proc in enumerate(self.ffmpeg_audio_processes_list):
            if audio_proc:
                temp_file_to_check = self.temp_audio_files_list[i] if i < len(self.temp_audio_files_list) else None
                self.logger(f"[FFmpegRecorder] Остановка аудиопроцесса FFmpeg[{i}] (файл: {os.path.basename(temp_file_to_check) if temp_file_to_check else 'N/A'})...")
                self._stop_ffmpeg_process(audio_proc, f"FFmpegAudio[{i}]", timeout_graceful=2, timeout_signal=10, timeout_terminate=3, is_audio=True, audio_file_path_for_check=temp_file_to_check)
        self.ffmpeg_audio_processes_list = []
        self.logger("[FFmpegRecorder] Начало объединения файлов...")
        mux_successful = self._mux_files() 
        if not mux_successful and not any("Объединение" in msg for msg in self.accumulated_error_messages): 
            self._add_error_message("Объединение временных файлов не удалось (неизвестная причина).", is_critical=True)
        elif mux_successful and self.accumulated_error_messages: 
            self.logger(f"[FFmpegRecorder] Объединение файлов успешно, но ранее возникли сообщения: {'; '.join(self.accumulated_error_messages)}")
        self._cleanup_temp_files()
        self.is_recording = False 
        final_errors_str = "; ".join(self.accumulated_error_messages) if self.accumulated_error_messages else None
        self.logger(f"[FFmpegRecorder] Раздельная запись остановлена. Итоговые сообщения: {final_errors_str if final_errors_str else 'Успешно'}")
        return final_errors_str

    def __del__(self):
        # ... (без изменений)
        if self.is_recording: 
            self.logger(f"[FFmpegRecorder __del__ ID:{id(self)}] Запись активна. Экстренный stop().")
            self.stop() 
        if self.frame_grabber: 
            try: self.frame_grabber.close()
            except: pass 
            self.frame_grabber = None
        self._cleanup_ffmpeg_processes(force_kill=True) 
        self._cleanup_temp_files()
