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

class FFmpegRecorder:
    def __init__(self, hwnd, output_file, audio_device_name, framerate, logger_func):
        self.hwnd = hwnd
        self.final_output_file = output_file 
        self.audio_device_name = audio_device_name 
        self.framerate = framerate if framerate > 0 else DEFAULT_FRAMERATE
        self.logger = logger_func
        
        self.frame_grabber = None 
        self.ffmpeg_video_process = None 
        self.ffmpeg_audio_process = None
        self._stop_event = threading.Event()
        self._video_recording_thread = None 
        
        self.temp_video_file = ""
        self.temp_audio_file = ""
        
        self.is_recording = False
        self.error_message = None 
        self.frames_written_count = 0 # Счетчик записанных кадров для таймера

    def get_frames_written(self):
        """Возвращает количество кадров, отправленных в FFmpeg."""
        return self.frames_written_count

    def _initialize_grabber(self):
        if not (self.hwnd and win32gui.IsWindow(self.hwnd)):
            self.error_message = "HWND окна недействителен или окно закрыто."; return False
        if win32gui.IsIconic(self.hwnd): 
            self.logger(f"[FFmpegRecorder] Окно {self.hwnd} свернуто, попытка восстановления...")
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE); time.sleep(0.5) 
            if not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd):
                self.error_message = "Не удалось восстановить свернутое окно."; return False
            self.logger(f"[FFmpegRecorder] Окно {self.hwnd} восстановлено.")
        try:
            self.frame_grabber = WindowFrameGrabberGDI(self.hwnd, self.logger)
            if not self.frame_grabber.is_initialized or self.frame_grabber.width <= 0 or self.frame_grabber.height <= 0:
                w_val = self.frame_grabber.width if self.frame_grabber else "N/A"
                h_val = self.frame_grabber.height if self.frame_grabber else "N/A"
                self.error_message = f"GDI граббер: ошибка инициализации/размеров (w={w_val}, h={h_val})."
                if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
                return False
            self.logger(f"[FFmpegRecorder] GDI граббер инициализирован: {self.frame_grabber.width}x{self.frame_grabber.height}")
            return True
        except Exception as e:
            self.error_message = f"Ошибка WindowFrameGrabberGDI: {e}"; import traceback; self.logger(traceback.format_exc())
            if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
            return False

    def _build_ffmpeg_video_command(self, width, height, temp_video_path):
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-nostdin', '-threads', '1', '-hide_banner', '-loglevel', 'error'])
        # Используем -fflags +genpts для генерации PTS, если rawvideo их не предоставляет
        # Убираем -vf setpts=PTS-STARTPTS, так как genpts должен справиться с этим для потока из pipe.
        command.extend(['-fflags', '+genpts', '-f', 'rawvideo', '-pix_fmt', 'bgr24', 
                        '-s', f'{width}x{height}', '-r', str(self.framerate), '-i', 'pipe:0'])
        # Если нужно дополнительно обработать PTS после genpts (маловероятно):
        # command.extend(['-vf', 'setpts=PTS-STARTPTS']) 
        command.extend(['-c:v', 'libx264', '-preset', DEFAULT_VIDEO_PRESET, '-crf', str(DEFAULT_VIDEO_CRF)])
        command.extend(['-pix_fmt', 'yuv420p', '-an']) 
        command.extend([temp_video_path, '-y'])
        return command

    def _build_ffmpeg_audio_command(self, temp_audio_path):
        if not self.audio_device_name or self.audio_device_name == NO_AUDIO_DEVICE_SELECTED:
            return None 
        
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-nostdin', '-threads', '1', '-nostats', '-hide_banner', '-loglevel', 'error']) 
        command.extend(['-f', 'dshow', '-guess_layout_max', '0', 
                        # Попробуем добавить -use_wallclock_as_timestamps 1 для dshow,
                        # это может помочь с более реалистичными временными метками от dshow.
                        # Эта опция может конфликтовать с -copyts при объединении, если dshow дает "плохие" метки.
                        # Пока оставим, но если синхронизация ухудшится, уберем.
                        # '-use_wallclock_as_timestamps', '1', # Экспериментально
                        '-i', f'audio={self.audio_device_name}'])
        # Убираем -af asetpts=PTS-STARTPTS, так как будем использовать -copyts -start_at_zero для аудио при объединении
        command.extend(['-c:a', DEFAULT_AUDIO_CODEC, '-b:a', DEFAULT_AUDIO_BITRATE, '-ar', '44100', '-ac', '2'])
        command.extend([temp_audio_path, '-y'])
        return command

    def _build_ffmpeg_mux_command(self, temp_video_path, temp_audio_path, final_output_path):
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-hide_banner', '-loglevel', 'error']) 
        
        # Для видео файла, который уже должен иметь корректные PTS от -fflags +genpts (или setpts)
        command.extend(['-i', temp_video_path])
        
        if temp_audio_path and os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 0:
            # Для аудио используем -copyts (копировать временные метки как есть от dshow)
            # и -start_at_zero (сдвинуть их, чтобы поток начинался с 0).
            # Важно: -copyts должно идти перед -i для аудиофайла.
            command.extend(['-copyts', '-start_at_zero', '-i', temp_audio_path])
            command.extend(['-c:v', 'copy', '-c:a', 'copy']) 
            command.extend(['-map', '0:v:0', '-map', '1:a:0']) 
        else: 
            command.extend(['-c:v', 'copy', '-an']) 
            command.extend(['-map', '0:v:0'])
        
        command.extend(['-shortest']) 
        command.extend(['-movflags', '+faststart']) 
        command.extend([final_output_path, '-y'])
        return command

    def start(self):
        self.logger("[FFmpegRecorder] Попытка запуска раздельной записи видео и аудио...")
        if self.is_recording: self.logger("[FFmpegRecorder] Запись уже идет."); return True, None

        self.frames_written_count = 0 # Сброс счетчика кадров при новом старте
        if not self._initialize_grabber(): 
            self.logger(f"[FFmpegRecorder] Отмена запуска (ошибка инициализации граббера): {self.error_message}")
            return False, self.error_message 

        self._stop_event.clear(); self.error_message = None 
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', prefix='_rec_vid_') as f_vid:
                self.temp_video_file = f_vid.name
            with tempfile.NamedTemporaryFile(delete=False, suffix='.aac', prefix='_rec_aud_') as f_aud: 
                self.temp_audio_file = f_aud.name
            
            if os.path.exists(self.temp_video_file): os.remove(self.temp_video_file)
            if os.path.exists(self.temp_audio_file): os.remove(self.temp_audio_file)

        except Exception as e_temp:
            self.error_message = f"Ошибка создания временных файлов: {e_temp}"
            self.logger(f"[FFmpegRecorder] {self.error_message}"); return False, self.error_message

        try:
            video_cmd_list = self._build_ffmpeg_video_command(
                self.frame_grabber.width, self.frame_grabber.height, self.temp_video_file
            )
            self.logger(f"[FFmpegRecorder] Видео команда: {' '.join(video_cmd_list)}")
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            self.ffmpeg_video_process = subprocess.Popen(
                video_cmd_list, stdin=subprocess.PIPE, 
                stderr=subprocess.PIPE, creationflags=creationflags, bufsize=0 
            )
            self.logger(f"[FFmpegRecorder] FFmpeg ВИДЕО процесс запущен (PID: {self.ffmpeg_video_process.pid}).")

            if self.audio_device_name and self.audio_device_name != NO_AUDIO_DEVICE_SELECTED:
                audio_cmd_list = self._build_ffmpeg_audio_command(self.temp_audio_file)
                if audio_cmd_list:
                    self.logger(f"[FFmpegRecorder] Аудио команда: {' '.join(audio_cmd_list)}")
                    self.ffmpeg_audio_process = subprocess.Popen(
                        audio_cmd_list, stdout=subprocess.DEVNULL, 
                        stderr=subprocess.PIPE, creationflags=creationflags
                    )
                    self.logger(f"[FFmpegRecorder] FFmpeg АУДИО процесс запущен (PID: {self.ffmpeg_audio_process.pid}).")
            else:
                self.ffmpeg_audio_process = None 
                self.temp_audio_file = "" 

        except Exception as e_start: 
            self.error_message = f"Ошибка при запуске процессов ffmpeg: {e_start}"
            self.logger(f"[FFmpegRecorder] КРИТИЧЕСКАЯ ОШИБКА ЗАПУСКА: {self.error_message}")
            self._cleanup_ffmpeg_processes(); self._cleanup_temp_files()
            if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
            return False, self.error_message

        self.is_recording = True
        self._video_recording_thread = threading.Thread(target=self._video_feed_loop, daemon=True)
        self._video_recording_thread.start()
        self.logger("[FFmpegRecorder] Поток передачи видеокадров запущен.")
        return True, None 

    def _read_ffmpeg_pipe(self, pipe, pipe_name_prefix, stop_event_local=None):
        try:
            while True:
                if stop_event_local and stop_event_local.is_set() and pipe.closed: break 
                # Неблокирующее чтение или чтение с таймаутом здесь было бы сложнее.
                # readline() будет блокировать, пока не придет строка или пайп не закроется.
                line_bytes = pipe.readline() 
                if not line_bytes: break 
                
                line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                if line_str: self.logger(f"[{pipe_name_prefix}] {line_str}")
        except Exception: pass # Игнорируем ошибки чтения, если пайп закрылся неожиданно.
        finally:
            if hasattr(pipe, 'close') and not pipe.closed: 
                try: pipe.close()
                except: pass

    def _video_feed_loop(self):
        self.logger("[FFmpegRecorder] Начало цикла передачи видеокадров...")
        # self.frames_written_count уже сброшен в start()
        frames_written_in_loop_local = 0 # Локальный счетчик для этого вызова цикла
        start_time_loop_overall = time.time() 
        
        vid_stderr_thread = None
        if self.ffmpeg_video_process and self.ffmpeg_video_process.stderr:
            vid_stderr_thread = threading.Thread(target=self._read_ffmpeg_pipe, 
                                                 args=(self.ffmpeg_video_process.stderr, "FFmpegVideo-stderr", self._stop_event), 
                                                 daemon=True)
            vid_stderr_thread.start()
        
        time_per_frame = 1.0 / self.framerate
        loop_internal_error_message = None

        try:
            if not self.frame_grabber or not self.frame_grabber.is_initialized:
                loop_internal_error_message = "GDI граббер не инициализирован перед видео циклом."
                raise RuntimeError(loop_internal_error_message) 
            
            expected_w = self.frame_grabber.width
            expected_h = self.frame_grabber.height
            last_frame_target_time = time.time() # Время, когда должен был быть отправлен предыдущий кадр

            while True: 
                if self._stop_event.is_set():
                    self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (начало цикла), выход."); break

                current_iteration_start_time = time.time()

                if not (self.hwnd and win32gui.IsWindow(self.hwnd)): 
                    loop_internal_error_message = "Окно захвата закрыто (видеоцикл)."; break 
                if self.ffmpeg_video_process.poll() is not None: 
                    loop_internal_error_message = f"FFmpeg видео завершился (код: {self.ffmpeg_video_process.poll()})."; break 
                if not self.ffmpeg_video_process.stdin or self.ffmpeg_video_process.stdin.closed: 
                    loop_internal_error_message = "FFmpeg видео stdin закрыт."; break 
                
                frame_bgr = self.frame_grabber.grab_frame()

                if self._stop_event.is_set():
                    self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (после grab_frame), выход."); break 

                if frame_bgr is None:
                    if not self.frame_grabber.is_initialized: 
                        loop_internal_error_message = "GDI граббер неинициализирован (видеоцикл)."; break 
                    # Пропускаем итерацию, но пытаемся выдержать ритм FPS для следующего кадра
                    # last_frame_target_time не обновляется, так как кадр не был отправлен
                    # Ждем до следующего "тика" time_per_frame
                    time_to_next_tick = last_frame_target_time + time_per_frame - time.time()
                    if time_to_next_tick > 0.001:
                        time.sleep(min(time_to_next_tick, 0.01)) # Короткий сон, чтобы не блокировать надолго
                    if self._stop_event.is_set(): break # Проверка после сна
                    continue 
                
                fh, fw, _ = frame_bgr.shape
                if fw != expected_w or fh != expected_h: 
                    loop_internal_error_message = f"Размер кадра ({fw}x{fh}) != ожидаемого ({expected_w}x{expected_h})."; break 
                
                try:
                    self.ffmpeg_video_process.stdin.write(frame_bgr.tobytes())
                    frames_written_in_loop_local += 1
                    self.frames_written_count = frames_written_in_loop_local 
                except (IOError, BrokenPipeError) as e_pipe: 
                    loop_internal_error_message = f"Видео Pipe error: {e_pipe}"; break 
                except Exception as e_write: 
                    loop_internal_error_message = f"Видео Stdin write error: {e_write}"; break 
                
                # Обновляем время, когда должен быть отправлен следующий кадр
                last_frame_target_time += time_per_frame
                
                # Сколько спать до этого времени
                current_time_after_send = time.time()
                sleep_duration = last_frame_target_time - current_time_after_send

                if sleep_duration > 0:
                    # Делаем прерываемый сон
                    sleep_chunk = 0.005 
                    end_sleep_time = current_time_after_send + sleep_duration
                    while time.time() < end_sleep_time:
                        if self._stop_event.is_set(): break
                        actual_sleep_this_chunk = min(sleep_chunk, end_sleep_time - time.time())
                        if actual_sleep_this_chunk <=0: break
                        time.sleep(actual_sleep_this_chunk)
                
                if self._stop_event.is_set():
                    self.logger("[FFmpegRecorder _video_feed_loop] _stop_event (после сна), выход."); break
                
                # Если сильно отстали, сбрасываем last_frame_target_time, чтобы не пытаться "догнать" слишком много
                if time.time() > last_frame_target_time + time_per_frame : # Если опоздали больше чем на кадр
                     last_frame_target_time = time.time()


        except RuntimeError as e_runtime_loop: 
             if not loop_internal_error_message: loop_internal_error_message = str(e_runtime_loop)
        except Exception as e_generic_loop: 
             if not loop_internal_error_message: loop_internal_error_message = f"Неожиданная ошибка в видеоцикле: {e_generic_loop}"
             import traceback; self.logger(traceback.format_exc())

        finally:
            self.logger("[FFmpegRecorder] Цикл передачи видеокадров завершается.")
            if loop_internal_error_message and not self.error_message:
                self.error_message = loop_internal_error_message 
            
            if self.ffmpeg_video_process and self.ffmpeg_video_process.stdin and \
               not self.ffmpeg_video_process.stdin.closed:
                self.logger("[FFmpegRecorder] Закрытие stdin видеопроцесса FFmpeg (из finally)...")
                try: 
                    self.ffmpeg_video_process.stdin.flush()
                    self.ffmpeg_video_process.stdin.close()
                    self.logger("[FFmpegRecorder] stdin видеопроцесса FFmpeg успешно закрыт (из finally).")
                except Exception as e_close_stdin_finally:
                     self.logger(f"[FFmpegRecorder] Ошибка при закрытии stdin (finally): {e_close_stdin_finally}")
            
            if vid_stderr_thread and vid_stderr_thread.is_alive(): 
                # self._stop_event уже должен быть установлен, если мы здесь
                vid_stderr_thread.join(timeout=2.0) 
                if vid_stderr_thread.is_alive():
                    self.logger("[FFmpegRecorder] Поток чтения stderr видео не завершился.")

        actual_duration_of_loop = time.time() - start_time_loop_overall
        if self.frames_written_count > 0 : # Используем обновленный self.frames_written_count
            avg_fps_sent_actual = self.frames_written_count / actual_duration_of_loop if actual_duration_of_loop > 0.01 else self.framerate
            self.logger(f"[FFmpegRecorder] Видеоцикл: {self.frames_written_count} кадров за {actual_duration_of_loop:.2f}с. (Отправлено ~{avg_fps_sent_actual:.1f} FPS).")
        elif actual_duration_of_loop > 0.1 : # Если цикл работал, но кадров 0
             self.logger(f"[FFmpegRecorder] Видеоцикл: 0 кадров за {actual_duration_of_loop:.2f}с.")


        if self.error_message: 
            self.logger(f"[FFmpegRecorder] Сообщение об ошибке после видеоцикла: {self.error_message}")

    def _stop_ffmpeg_process(self, process, process_name, timeout_graceful=3, timeout_signal=7, timeout_terminate=3):
        if not process: return None 
        
        return_code = process.poll()
        accumulated_error_message_stop = None 
        process_final_stderr_stop = "" 

        stderr_reader_thread_stop = None
        pipe_to_read_stop = process.stderr
        stderr_buffer_local_stop = [] 
        stop_stderr_event_local_stop = threading.Event() 
        
        if pipe_to_read_stop and not pipe_to_read_stop.closed:
            def _stderr_reader_func_local_stop_unique(pipe, buffer_list, stop_event): 
                try:
                    while not stop_event.is_set():
                        line_bytes = pipe.readline()
                        if not line_bytes: break 
                        buffer_list.append(line_bytes.decode('utf-8', errors='ignore'))
                        if len(buffer_list) > 200: buffer_list.pop(0) 
                except: pass 
                finally:
                    try: 
                        remaining_bytes = pipe.read() 
                        if remaining_bytes: buffer_list.append(remaining_bytes.decode('utf-8', errors='ignore'))
                    except: pass

            stderr_reader_thread_stop = threading.Thread(target=_stderr_reader_func_local_stop_unique, 
                                                         args=(pipe_to_read_stop, stderr_buffer_local_stop, stop_stderr_event_local_stop), 
                                                         daemon=True)
            stderr_reader_thread_stop.start()

        if return_code is None: 
            self.logger(f"[FFmpegRecorder] {process_name} активен. Попытка корректного завершения...")
            if process_name == "FFmpegVideo" and process.stdin and not process.stdin.closed:
                self.logger(f"[FFmpegRecorder] Внимание: stdin {process_name} не был закрыт до _stop_ffmpeg_process. Закрытие...")
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
                    err_msg_force = f"{process_name} принудительно завершен."
                    accumulated_error_message_stop = (accumulated_error_message_stop + "; " + err_msg_force) if accumulated_error_message_stop else err_msg_force
                    self.logger(f"[FFmpegRecorder] {process_name} завершен после kill/terminate с кодом {return_code}.")
                except Exception as e_signal_wait: 
                    err_msg_signal = f"Ошибка сигнала/ожидания для {process_name}: {e_signal_wait}"
                    accumulated_error_message_stop = (accumulated_error_message_stop + "; " + err_msg_signal) if accumulated_error_message_stop else err_msg_signal
                    self.logger(f"[FFmpegRecorder] {err_msg_signal}")
                    try: process.kill(); return_code = process.poll()
                    except: pass
        else: 
            self.logger(f"[FFmpegRecorder] {process_name} уже был завершен с кодом {return_code}.")

        if stderr_reader_thread_stop:
            stop_stderr_event_local_stop.set() 
            stderr_reader_thread_stop.join(timeout=1.5) 
            if stderr_buffer_local_stop:
                process_final_stderr_stop = "".join(stderr_buffer_local_stop).strip()
        
        if not process_final_stderr_stop and pipe_to_read_stop and not pipe_to_read_stop.closed:
            try:
                # Даем небольшой шанс дочитать, если процесс только что завершился
                pipe_to_read_stop.timeout = 0.1 # Не работает для файловых объектов из Popen
                remaining_bytes_direct = pipe_to_read_stop.read() # Может блокировать, если что-то пошло не так
                if remaining_bytes_direct:
                    process_final_stderr_stop = remaining_bytes_direct.decode('utf-8', errors='ignore').strip()
            except: pass 
        
        if process_final_stderr_stop: 
            self.logger(f"[FFmpegRecorder] {process_name} Stderr (полный лог при остановке): {process_final_stderr_stop}")
        
        if return_code is not None and return_code != 0:
            err_msg_exit_code = f"{process_name} завершился с ошибкой (код {return_code})."
            accumulated_error_message_stop = (accumulated_error_message_stop + "; " + err_msg_exit_code) if accumulated_error_message_stop else err_msg_exit_code
            if process_final_stderr_stop: 
                stderr_preview = (process_final_stderr_stop[:150] + '...') if len(process_final_stderr_stop) > 150 else process_final_stderr_stop
                accumulated_error_message_stop += f" Stderr: {stderr_preview}"
        
        if pipe_to_read_stop and not pipe_to_read_stop.closed:
            try: pipe_to_read_stop.close()
            except: pass

        return accumulated_error_message_stop 

    def _mux_files(self):
        self.logger("[FFmpegRecorder] Попытка объединения временных файлов...")
        mux_internal_error = None

        if not os.path.exists(self.temp_video_file) or os.path.getsize(self.temp_video_file) == 0:
            mux_internal_error = "Временный видеофайл отсутствует или пуст. Объединение невозможно."
            self.logger(f"[FFmpegRecorder] {mux_internal_error}")
            if not self.error_message or "видеофайл отсутствует" not in self.error_message:
                self.error_message = (self.error_message + "; " + mux_internal_error) if self.error_message else mux_internal_error
            return False 
        
        use_audio_in_mux = bool(self.temp_audio_file and \
                                os.path.exists(self.temp_audio_file) and \
                                os.path.getsize(self.temp_audio_file) > 0)
        
        mux_cmd_list = self._build_ffmpeg_mux_command(
            self.temp_video_file, 
            self.temp_audio_file if use_audio_in_mux else None, 
            self.final_output_file
        )
        self.logger(f"[FFmpegRecorder] Mux команда: {' '.join(mux_cmd_list)}")
        
        try:
            mux_process_result = subprocess.run(mux_cmd_list, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
            
            if mux_process_result.returncode != 0:
                mux_stderr_output = mux_process_result.stderr.strip() if mux_process_result.stderr else "Нет вывода stderr от mux"
                mux_internal_error = f"Ошибка объединения файлов (FFmpeg код {mux_process_result.returncode}). Stderr: {mux_stderr_output}"
                self.logger(f"[FFmpegRecorder] {mux_internal_error}")
                self.error_message = (self.error_message + "; " + mux_internal_error) if self.error_message else mux_internal_error
                return False 
            
            self.logger("[FFmpegRecorder] Файлы успешно объединены.")
            return True 

        except Exception as e_mux_run: 
            mux_internal_error = f"Исключение при выполнении команды объединения файлов: {e_mux_run}"
            self.logger(f"[FFmpegRecorder] {mux_internal_error}")
            self.error_message = (self.error_message + "; " + mux_internal_error) if self.error_message else mux_internal_error
            return False

    def _cleanup_temp_files(self):
        files_to_delete = [self.temp_video_file, self.temp_audio_file]
        for f_path in files_to_delete:
            if f_path and os.path.exists(f_path):
                try: 
                    os.remove(f_path)
                    self.logger(f"[FFmpegRecorder] Удален временный файл: {f_path}")
                except OSError as e_os: 
                    self.logger(f"[FFmpegRecorder] Не удалось удалить временный файл {f_path} (OSError): {e_os}")
                except Exception as e_gen: 
                    self.logger(f"[FFmpegRecorder] Ошибка при удалении временного файла {f_path}: {e_gen}")
        
        self.temp_video_file = ""
        self.temp_audio_file = ""
        
    def _cleanup_ffmpeg_processes(self):
        processes_to_clean = []
        if self.ffmpeg_video_process and self.ffmpeg_video_process.poll() is None:
            processes_to_clean.append(("FFmpegVideo", self.ffmpeg_video_process))
        if self.ffmpeg_audio_process and self.ffmpeg_audio_process.poll() is None:
            processes_to_clean.append(("FFmpegAudio", self.ffmpeg_audio_process))

        for name, proc in processes_to_clean:
            self.logger(f"[FFmpegRecorder] Экстренная очистка: Попытка kill() для {name} (PID: {proc.pid}).")
            try: proc.kill()
            except Exception as e_kill: self.logger(f"[FFmpegRecorder] Ошибка при kill() {name}: {e_kill}")
        
        if processes_to_clean:
            self.ffmpeg_video_process = None
            self.ffmpeg_audio_process = None

    def stop(self):
        self.logger(f"[FFmpegRecorder] Команда stop получена (is_recording: {self.is_recording}).")
        if not self.is_recording: 
            self.logger("[FFmpegRecorder] Запись не была активна (is_recording=False при вызове stop).")
            return self.error_message or None 

        self.logger(f"[FFmpegRecorder] Установка _stop_event (время: {time.time():.3f}).")
        self._stop_event.set() 
        
        if self._video_recording_thread and self._video_recording_thread.is_alive():
            self.logger("[FFmpegRecorder] Ожидание завершения потока _video_feed_loop...")
            self._video_recording_thread.join(timeout=3.0) # Уменьшаем таймаут, цикл должен реагировать быстрее
            if self._video_recording_thread.is_alive():
                self.logger("[FFmpegRecorder] ВНИМАНИЕ: Поток _video_feed_loop не завершился за 3с.")
            else:
                self.logger("[FFmpegRecorder] Поток _video_feed_loop завершен.")
        self._video_recording_thread = None 
        
        if self.frame_grabber: 
            self.logger("[FFmpegRecorder] Закрытие frame_grabber...")
            try: self.frame_grabber.close(); self.logger("[FFmpegRecorder] Frame grabber закрыт.")
            except Exception as e_close_grabber: self.logger(f"[FFmpegRecorder] Ошибка при закрытии frame_grabber: {e_close_grabber}")
            self.frame_grabber = None
        
        self.logger("[FFmpegRecorder] Остановка видеопроцесса FFmpeg...")
        err_vid_stop = self._stop_ffmpeg_process(self.ffmpeg_video_process, "FFmpegVideo", timeout_graceful=2, timeout_signal=5, timeout_terminate=2)
        if err_vid_stop:
            self.error_message = (self.error_message + "; " + err_vid_stop) if self.error_message else err_vid_stop
        self.ffmpeg_video_process = None 

        if self.ffmpeg_audio_process:
            self.logger("[FFmpegRecorder] Остановка аудиопроцесса FFmpeg...")
            err_aud_stop = self._stop_ffmpeg_process(self.ffmpeg_audio_process, "FFmpegAudio", timeout_graceful=2, timeout_signal=10, timeout_terminate=3)
            if err_aud_stop:
                self.error_message = (self.error_message + "; " + err_aud_stop) if self.error_message else err_aud_stop
            self.ffmpeg_audio_process = None 
        
        self.logger("[FFmpegRecorder] Начало объединения файлов...")
        mux_successful = self._mux_files() 
        
        if not mux_successful and (not self.error_message or "Объединение" not in self.error_message) : 
            err_mux = "Объединение временных файлов не удалось (детали в логе выше)."
            self.error_message = (self.error_message + "; " + err_mux) if self.error_message else err_mux
        elif mux_successful and self.error_message: 
            self.logger(f"[FFmpegRecorder] Объединение файлов успешно, но ранее возникли ошибки: {self.error_message}")
            
        self._cleanup_temp_files()
        self.is_recording = False 
        
        final_result_message = self.error_message or None 
        self.logger(f"[FFmpegRecorder] Раздельная запись остановлена. Итоговое сообщение: {final_result_message}")
        return final_result_message

    def __del__(self):
        if self.is_recording: 
            self.logger(f"[FFmpegRecorder __del__ ID:{id(self)}] Запись активна. Экстренный stop().")
            self.stop() 
        if self.frame_grabber: 
            try: self.frame_grabber.close()
            except: pass 
            self.frame_grabber = None
        self._cleanup_ffmpeg_processes() 
        self._cleanup_temp_files()
        # self.logger(f"[FFmpegRecorder __del__ ID:{id(self)}] Объект уничтожен.") # Убрал, чтобы не спамить при обычном выходе
