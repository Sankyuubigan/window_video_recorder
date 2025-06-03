import numpy as np
import cv2 
import threading
import time
import os
import win32gui
import win32con
import subprocess 
import signal
import tempfile # Для временных файлов

from config import DEFAULT_FRAMERATE, FFMPEG_PATH, NO_AUDIO_DEVICE_SELECTED
from config import DEFAULT_VIDEO_PRESET, DEFAULT_VIDEO_CRF, DEFAULT_AUDIO_CODEC, DEFAULT_AUDIO_BITRATE
from window_utils import WindowFrameGrabberGDI 

class FFmpegRecorder:
    def __init__(self, hwnd, output_file, audio_device_name, framerate, logger_func):
        self.hwnd = hwnd
        self.final_output_file = output_file # Итоговый файл
        self.audio_device_name = audio_device_name 
        self.framerate = framerate if framerate > 0 else DEFAULT_FRAMERATE
        self.logger = logger_func
        
        self.frame_grabber = None 
        self.ffmpeg_video_process = None 
        self.ffmpeg_audio_process = None
        self._stop_event = threading.Event()
        self._video_recording_thread = None # Поток для передачи видеокадров
        
        self.temp_video_file = ""
        self.temp_audio_file = ""
        
        self.is_recording = False
        self.error_message = None

    def _initialize_grabber(self):
        if not (self.hwnd and win32gui.IsWindow(self.hwnd)):
            self.error_message = "HWND окна недействителен или окно закрыто."; return False
        if win32gui.IsIconic(self.hwnd): 
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE); time.sleep(0.5) 
            if not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd):
                self.error_message = "Не удалось восстановить свернутое окно."; return False
        try:
            self.frame_grabber = WindowFrameGrabberGDI(self.hwnd, self.logger)
            if not self.frame_grabber.is_initialized or self.frame_grabber.width <= 0 or self.frame_grabber.height <= 0:
                self.error_message = f"GDI граббер: ошибка инициализации/размеров."
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
        command.extend(['-nostdin', '-threads', '1'])
        command.extend(['-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(self.framerate), '-i', 'pipe:0'])
        command.extend(['-c:v', 'libx264', '-preset', DEFAULT_VIDEO_PRESET, '-crf', str(DEFAULT_VIDEO_CRF)])
        command.extend(['-pix_fmt', 'yuv420p', '-an']) # -an для видео без звука
        command.extend([temp_video_path, '-y'])
        return command

    def _build_ffmpeg_audio_command(self, temp_audio_path):
        if not self.audio_device_name or self.audio_device_name == NO_AUDIO_DEVICE_SELECTED:
            return None # Нет аудио для записи
        
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-nostdin', '-threads', '1']) # Для аудио тоже может быть полезно
        command.extend(['-f', 'dshow', '-guess_layout_max', '0', '-i', f'audio={self.audio_device_name}'])
        command.extend(['-c:a', DEFAULT_AUDIO_CODEC, '-b:a', DEFAULT_AUDIO_BITRATE, '-ar', '44100', '-ac', '2'])
        command.extend([temp_audio_path, '-y'])
        return command

    def _build_ffmpeg_mux_command(self, temp_video_path, temp_audio_path, final_output_path):
        command = [FFMPEG_PATH if FFMPEG_PATH.lower() != "ffmpeg" and os.path.exists(FFMPEG_PATH) else "ffmpeg"]
        command.extend(['-i', temp_video_path])
        if temp_audio_path and os.path.exists(temp_audio_path): # Если аудио записывалось и файл существует
            command.extend(['-i', temp_audio_path])
            command.extend(['-c:v', 'copy', '-c:a', 'copy']) # Копируем потоки без перекодирования
            command.extend(['-map', '0:v:0', '-map', '1:a:0']) # Явно мапим
        else: # Если аудио не было или не записалось
            command.extend(['-c:v', 'copy', '-an']) # Копируем видео, аудио нет
            command.extend(['-map', '0:v:0'])
        
        command.extend(['-movflags', '+faststart']) # Для итогового файла
        command.extend([final_output_path, '-y'])
        return command

    def start(self):
        self.logger("[FFmpegRecorder] Попытка запуска раздельной записи видео и аудио...")
        if self.is_recording: return True, None

        if not self._initialize_grabber():
            self.logger(f"[FFmpegRecorder] Отмена запуска (ошибка инициализации граббера): {self.error_message}")
            return False, self.error_message 

        self._stop_event.clear(); self.error_message = None
        
        # Создаем имена для временных файлов
        # Используем tempfile.NamedTemporaryFile, чтобы получить уникальные имена, затем удалим и используем имена
        # Это более безопасно, чем просто генерировать имена.
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', prefix='_rec_vid_') as f_vid:
                self.temp_video_file = f_vid.name
            with tempfile.NamedTemporaryFile(delete=False, suffix='.aac', prefix='_rec_aud_') as f_aud: # или .mp3 если меняли кодек
                self.temp_audio_file = f_aud.name
            # Файлы созданы, но сразу закрыты и удалены (delete=False), мы используем только их имена.
            # FFmpeg их пересоздаст.
            if os.path.exists(self.temp_video_file): os.remove(self.temp_video_file)
            if os.path.exists(self.temp_audio_file): os.remove(self.temp_audio_file)

        except Exception as e_temp:
            self.error_message = f"Ошибка создания временных файлов: {e_temp}"
            self.logger(f"[FFmpegRecorder] {self.error_message}"); return False, self.error_message

        try:
            # --- Запуск FFmpeg для видео ---
            video_cmd_list = self._build_ffmpeg_video_command(
                self.frame_grabber.width, self.frame_grabber.height, self.temp_video_file
            )
            self.logger(f"[FFmpegRecorder] Видео команда: {' '.join(video_cmd_list)}")
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            self.ffmpeg_video_process = subprocess.Popen(
                video_cmd_list, stdin=subprocess.PIPE, stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, creationflags=creationflags
            )
            self.logger(f"[FFmpegRecorder] FFmpeg ВИДЕО процесс запущен (PID: {self.ffmpeg_video_process.pid}).")

            # --- Запуск FFmpeg для аудио (если нужно) ---
            if self.audio_device_name and self.audio_device_name != NO_AUDIO_DEVICE_SELECTED:
                audio_cmd_list = self._build_ffmpeg_audio_command(self.temp_audio_file)
                if audio_cmd_list:
                    self.logger(f"[FFmpegRecorder] Аудио команда: {' '.join(audio_cmd_list)}")
                    # Для аудио stdin не нужен, stdout/stderr для логов
                    self.ffmpeg_audio_process = subprocess.Popen(
                        audio_cmd_list, stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, creationflags=creationflags
                    )
                    self.logger(f"[FFmpegRecorder] FFmpeg АУДИО процесс запущен (PID: {self.ffmpeg_audio_process.pid}).")
                else: # Не должно случиться, если audio_device_name валидно
                    self.ffmpeg_audio_process = None 
            else:
                self.ffmpeg_audio_process = None # Явно указываем, что аудио не пишется
                self.temp_audio_file = "" # Сбрасываем путь, если аудио нет

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

    def _read_ffmpeg_pipe(self, pipe, pipe_name_prefix):
        # ... (без изменений) ...
        try:
            for line_bytes in iter(pipe.readline, b''):
                if self._stop_event.is_set() and "stderr" in pipe_name_prefix.lower() : pass 
                line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                if line_str: self.logger(f"[{pipe_name_prefix}] {line_str}")
        except: pass 
        finally:
            if hasattr(pipe, 'close') and not pipe.closed: pipe.close()

    def _video_feed_loop(self):
        self.logger("[FFmpegRecorder] Начало цикла передачи видеокадров...")
        frames_written = 0; start_time = time.time()
        # Потоки для чтения stdout/stderr от ffmpeg_video_process
        vid_stdout_thread, vid_stderr_thread = None, None
        if self.ffmpeg_video_process:
            if self.ffmpeg_video_process.stdout:
                vid_stdout_thread = threading.Thread(target=self._read_ffmpeg_pipe, args=(self.ffmpeg_video_process.stdout, "FFmpegVideo-stdout"), daemon=True); vid_stdout_thread.start()
            if self.ffmpeg_video_process.stderr:
                vid_stderr_thread = threading.Thread(target=self._read_ffmpeg_pipe, args=(self.ffmpeg_video_process.stderr, "FFmpegVideo-stderr"), daemon=True); vid_stderr_thread.start()
        try:
            if not self.frame_grabber or not self.frame_grabber.is_initialized:
                self.error_message = "GDI граббер не инициализирован перед видео циклом."; return
            
            expected_w = self.frame_grabber.width; expected_h = self.frame_grabber.height
            while not self._stop_event.is_set():
                if not (self.hwnd and win32gui.IsWindow(self.hwnd)): self.error_message = "Окно захвата закрыто (видеоцикл)."; break
                if self.ffmpeg_video_process.poll() is not None: self.error_message = self.error_message or f"FFmpeg видео неожиданно завершился ({self.ffmpeg_video_process.poll()})."; break
                if not self.ffmpeg_video_process.stdin or self.ffmpeg_video_process.stdin.closed: self.error_message = self.error_message or "FFmpeg видео stdin закрыт."; break
                
                frame_bgr = self.frame_grabber.grab_frame()
                if frame_bgr is None:
                    if not self.frame_grabber.is_initialized: self.error_message = "GDI граббер стал неинициализированным (видеоцикл)."; break
                    time.sleep(0.005); continue # Короткая пауза, если кадр не получен
                
                fh, fw, _ = frame_bgr.shape
                if fw != expected_w or fh != expected_h: # Если граббер переинициализировался с другими размерами
                    self.error_message = f"Размер видеокадра ({fw}x{fh}) не совпал с ffmpeg ({expected_w}x{expected_h})."; break 
                try:
                    self.ffmpeg_video_process.stdin.write(frame_bgr.tobytes()); frames_written += 1
                except (IOError, BrokenPipeError) as e_pipe: self.error_message = self.error_message or f"Видео Pipe error: {e_pipe}"; break
                except Exception as e_write: self.error_message = f"Видео Stdin write error: {e_write}"; break
        finally:
            self.logger("[FFmpegRecorder] Цикл передачи видеокадров завершается.")
            if self.ffmpeg_video_process and self.ffmpeg_video_process.stdin and not self.ffmpeg_video_process.stdin.closed:
                try: self.ffmpeg_video_process.stdin.close()
                except: pass
            if vid_stdout_thread and vid_stdout_thread.is_alive(): vid_stdout_thread.join(timeout=0.5)
            if vid_stderr_thread and vid_stderr_thread.is_alive(): vid_stderr_thread.join(timeout=0.5)
        if frames_written > 0: self.logger(f"[FFmpegRecorder] Видеоцикл: {frames_written} кадров за {time.time()-start_time:.2f}с.")

    def _stop_ffmpeg_process(self, process, process_name, timeout_graceful=5, timeout_signal=10, timeout_terminate=5):
        """Останавливает один процесс ffmpeg с несколькими попытками."""
        if not process: return None
        
        return_code = process.poll()
        current_error = None
        if return_code is None:
            self.logger(f"[FFmpegRecorder] {process_name} активен. Попытка корректного завершения...")
            # 1. Закрываем stdin, если он есть и открыт (для видеопроцесса)
            if process.stdin and not process.stdin.closed:
                try: process.stdin.close()
                except: pass
            
            # 2. Ждем немного
            try:
                process.wait(timeout=timeout_graceful)
                return_code = process.returncode
                self.logger(f"[FFmpegRecorder] {process_name} завершился после wait({timeout_graceful}s) с кодом {return_code}.")
            except subprocess.TimeoutExpired:
                self.logger(f"[FFmpegRecorder] {process_name} не завершился за {timeout_graceful}с. Попытка SIGINT/CTRL_C...")
                try:
                    if os.name == 'nt': process.send_signal(signal.CTRL_C_EVENT)
                    else: process.send_signal(signal.SIGINT)
                    process.wait(timeout=timeout_signal)
                    return_code = process.returncode
                    self.logger(f"[FFmpegRecorder] {process_name} завершился после сигнала с кодом {return_code}.")
                except subprocess.TimeoutExpired:
                    self.logger(f"[FFmpegRecorder] {process_name} не завершился после сигнала за {timeout_signal}с. Terminate()...")
                    process.terminate()
                    try: process.wait(timeout=timeout_terminate)
                    except subprocess.TimeoutExpired: process.kill(); self.logger(f"[FFmpegRecorder] {process_name} пришлось убить (kill).")
                    return_code = process.poll()
                    current_error = f"{process_name} принудительно завершен."
                    self.logger(f"[FFmpegRecorder] {process_name} завершен после kill/terminate с кодом {return_code}.")
                except Exception as e_s:
                    current_error = f"Ошибка сигнала/ожидания для {process_name}: {e_s}"; self.logger(f"[FFmpegRecorder] {current_error}")
                    try: process.kill()
                    except: pass
                    return_code = process.poll()
        else:
            self.logger(f"[FFmpegRecorder] {process_name} уже был завершен с кодом {return_code}.")

        if return_code is not None and return_code != 0:
            current_error = current_error or f"{process_name} ошибка (код {return_code})."
        
        # Читаем остатки stderr, если есть
        stderr_output = ""
        if process.stderr:
            try: stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
            except: pass
        if stderr_output: self.logger(f"[FFmpegRecorder] {process_name} Stderr при остановке: {stderr_output.strip()}")
        if current_error and stderr_output.strip(): current_error += f" Stderr: {stderr_output.strip()[:200]}" # Первые 200 символов

        return current_error # Возвращает сообщение об ошибке или None

    def _mux_files(self):
        self.logger("[FFmpegRecorder] Попытка объединения временных файлов...")
        if not os.path.exists(self.temp_video_file) or os.path.getsize(self.temp_video_file) == 0:
            self.error_message = self.error_message or "Временный видеофайл отсутствует или пуст. Объединение невозможно."
            self.logger(f"[FFmpegRecorder] {self.error_message}")
            return False
        
        # Если аудиофайл не создавался или пуст, temp_audio_file может быть "" или не существовать
        use_audio = bool(self.temp_audio_file and os.path.exists(self.temp_audio_file) and os.path.getsize(self.temp_audio_file) > 0)
        
        mux_cmd_list = self._build_ffmpeg_mux_command(
            self.temp_video_file, 
            self.temp_audio_file if use_audio else None, # Передаем None, если аудио нет
            self.final_output_file
        )
        self.logger(f"[FFmpegRecorder] Mux команда: {' '.join(mux_cmd_list)}")
        try:
            # Запускаем синхронно, так как это быстрая операция
            mux_process = subprocess.run(mux_cmd_list, capture_output=True, text=True, check=False) # check=False чтобы самим обработать ошибку
            if mux_process.returncode != 0:
                self.error_message = self.error_message or f"Ошибка объединения файлов. FFmpeg stderr: {mux_process.stderr}"
                self.logger(f"[FFmpegRecorder] {self.error_message}")
                return False
            self.logger("[FFmpegRecorder] Файлы успешно объединены.")
            return True
        except Exception as e_mux:
            self.error_message = self.error_message or f"Исключение при объединении файлов: {e_mux}"
            self.logger(f"[FFmpegRecorder] {self.error_message}")
            return False

    def _cleanup_temp_files(self):
        if self.temp_video_file and os.path.exists(self.temp_video_file):
            try: os.remove(self.temp_video_file); self.logger(f"[FFmpegRecorder] Удален временный видеофайл: {self.temp_video_file}")
            except: pass
        if self.temp_audio_file and os.path.exists(self.temp_audio_file):
            try: os.remove(self.temp_audio_file); self.logger(f"[FFmpegRecorder] Удален временный аудиофайл: {self.temp_audio_file}")
            except: pass
        self.temp_video_file = ""
        self.temp_audio_file = ""
        
    def _cleanup_ffmpeg_processes(self):
        if self.ffmpeg_video_process and self.ffmpeg_video_process.poll() is None:
            try: self.ffmpeg_video_process.kill()
            except: pass
        if self.ffmpeg_audio_process and self.ffmpeg_audio_process.poll() is None:
            try: self.ffmpeg_audio_process.kill()
            except: pass
        self.ffmpeg_video_process = None
        self.ffmpeg_audio_process = None

    def stop(self):
        self.logger("[FFmpegRecorder] Попытка остановки раздельной записи...")
        if not self.is_recording:
            self.logger("[FFmpegRecorder] Запись не была активна."); return self.error_message
        
        self._stop_event.set() 
        if self._video_recording_thread and self._video_recording_thread.is_alive():
            self._video_recording_thread.join(timeout=5)
        
        if self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
        
        err_vid = self._stop_ffmpeg_process(self.ffmpeg_video_process, "FFmpegVideo")
        err_aud = None
        if self.ffmpeg_audio_process: # Останавливаем аудио только если оно было запущено
            err_aud = self._stop_ffmpeg_process(self.ffmpeg_audio_process, "FFmpegAudio")

        # Собираем ошибки
        if err_vid: self.error_message = self.error_message or err_vid
        if err_aud: self.error_message = (self.error_message + "; " + err_aud) if self.error_message else err_aud
        
        # Даже если были ошибки при остановке процессов, пытаемся смержить то, что есть
        mux_success = self._mux_files()
        
        if not mux_success and not self.error_message: # Если mux не удался, но ошибок от ffmpeg не было
            self.error_message = "Ошибка объединения временных файлов (детали в логе)."
        elif mux_success and self.error_message: # Если mux удался, но были ошибки остановки ffmpeg
            self.logger(f"[FFmpegRecorder] Объединение успешно, но были ошибки при остановке процессов: {self.error_message}")
            # Решаем, считать ли это общей ошибкой. Пока что, если mux успешен, то это главное.
            # self.error_message = None # Можно сбросить ошибку, если mux прошел
            pass


        self._cleanup_temp_files()
        self.is_recording = False; self._video_recording_thread = None
        self.ffmpeg_video_process = None; self.ffmpeg_audio_process = None
        self.logger(f"[FFmpegRecorder] Раздельная запись остановлена. Итоговая ошибка: {self.error_message}")
        return self.error_message

    def __del__(self):
        if self.is_recording: self.stop()
        elif self.frame_grabber: self.frame_grabber.close(); self.frame_grabber = None
        self._cleanup_ffmpeg_processes() # На всякий случай
        self._cleanup_temp_files()
