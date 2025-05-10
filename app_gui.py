import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import datetime
import win32gui
import win32con
import numpy as np 
import cv2         
import time 
import sys  
import subprocess

from windows_utils import get_active_windows, prevent_minimize_loop, get_window_geometry
from ffmpeg_utils import get_dshow_audio_devices, run_ffmpeg_recording_from_pipe 
from config import DEFAULT_FRAMERATE 
from window_capture import WindowCapture 

class ScreenRecorderApp:
    def __init__(self, master): # (Без изменений от v0.14.1)
        self.master = master
        try: 
            final_icon_path = None;
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                base_path_frozen = sys._MEIPASS; icon_path_frozen_meipass = os.path.join(base_path_frozen, "app_icon.ico")
                if os.path.exists(icon_path_frozen_meipass): final_icon_path = icon_path_frozen_meipass
                else:
                    executable_dir = os.path.dirname(sys.executable); icon_path_executable_dir = os.path.join(executable_dir, "app_icon.ico")
                    if os.path.exists(icon_path_executable_dir): final_icon_path = icon_path_executable_dir
                    else: print(f"[AppGUI] Файл иконки app_icon.ico не найден ни в MEIPASS ({base_path_frozen}), ни рядом с exe ({executable_dir}).")
            else:
                current_script_dir = os.path.dirname(os.path.abspath(__file__)); icon_path_source = os.path.join(current_script_dir, "app_icon.ico")
                if os.path.exists(icon_path_source): final_icon_path = icon_path_source
                else: print(f"[AppGUI] Файл иконки app_icon.ico не найден в {current_script_dir}.")
            if final_icon_path: master.iconbitmap(final_icon_path); print(f"[AppGUI] Иконка установлена из: {final_icon_path}")
            else: print(f"[AppGUI] Файл иконки app_icon.ico не найден. Используется иконка по умолчанию.")
        except Exception as e: print(f"[AppGUI] Не удалось установить иконку окна: {e}")
        master.title("Video Conference Recorder v0.14.2 (Syntax & Path Fix)"); master.geometry("700x400") 
        self.is_recording = False; self.prevent_minimize_thread = None; self.recording_thread = None
        self.capture_thread_obj = None; self.ffmpeg_process = None; self.ffmpeg_stderr_thread = None 
        self.stop_event = threading.Event(); self.selected_hwnd = None; self.window_titles_map = {}
        self.audio_devices = []; self.current_output_file = ""; self.window_capturer = None 
        self._setup_gui(); self.populate_window_list(); self.populate_audio_device_lists(); master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_gui(self): # (Без изменений от v0.14.1)
        tk.Label(self.master, text="Окно для записи:").grid(row=0, column=0, padx=5, pady=5, sticky="w"); self.window_combo = ttk.Combobox(self.master, width=75, state="readonly"); self.window_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew"); self.refresh_windows_button = tk.Button(self.master, text="Обновить Окна", command=self.populate_window_list); self.refresh_windows_button.grid(row=0, column=2, padx=5, pady=5); tk.Label(self.master, text="Папка для сохранения:").grid(row=1, column=0, padx=5, pady=5, sticky="w"); self.output_dir_entry = tk.Entry(self.master, width=75); self.output_dir_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew"); self.browse_button = tk.Button(self.master, text="Обзор...", command=self.select_output_directory); self.browse_button.grid(row=1, column=2, padx=5, pady=5); tk.Label(self.master, text="Микрофон (dshow):").grid(row=2, column=0, padx=5, pady=5, sticky="w"); self.mic_device_combo = ttk.Combobox(self.master, width=75, state="readonly"); self.mic_device_combo.grid(row=2, column=1, padx=5, pady=5, sticky="ew"); tk.Label(self.master, text="Системный звук (dshow):").grid(row=3, column=0, padx=5, pady=5, sticky="w"); self.system_audio_device_combo = ttk.Combobox(self.master, width=75, state="readonly"); self.system_audio_device_combo.grid(row=3, column=1, padx=5, pady=5, sticky="ew"); self.refresh_audio_button = tk.Button(self.master, text="Обновить Аудио", command=self.populate_audio_device_lists); self.refresh_audio_button.grid(row=2, column=2, rowspan=2, padx=5, pady=5, sticky="ns"); self.record_button = tk.Button(self.master, text="Начать запись", command=self.toggle_recording, bg="lightgreen", height=2); self.record_button.grid(row=4, column=0, columnspan=3, padx=5, pady=15, sticky="ew"); self.status_label = tk.Label(self.master, text="Статус: Ожидание", relief=tk.SUNKEN, anchor="w"); self.status_label.grid(row=5, column=0, columnspan=3, padx=5, pady=5, sticky="ew"); self.master.grid_columnconfigure(1, weight=1)

    def toggle_recording(self): # (без изменений)
        if self.is_recording: self.stop_recording()
        else: self.start_recording()

    def populate_window_list(self): # (Без изменений от v0.14.1)
        self.window_combo['values'] = []; self.window_titles_map = get_active_windows(); sorted_titles = sorted(self.window_titles_map.keys()); self.window_combo['values'] = sorted_titles; 
        if sorted_titles: self.window_combo.current(0)
        if not self.is_recording: self.status_label.config(text="Статус: Список окон обновлен.")

    def populate_audio_device_lists(self): # (Без изменений от v0.14.1)
        print("[AppGUI] Обновление списка аудиоустройств..."); 
        if not self.is_recording: self.status_label.config(text="Статус: Обновление списка аудиоустройств...")
        self.master.update_idletasks(); self.audio_devices = get_dshow_audio_devices(); print(f"[AppGUI] Получены аудиоустройства (после get_dshow_audio_devices): {self.audio_devices}"); self.mic_device_combo['values'] = self.audio_devices; self.system_audio_device_combo['values'] = self.audio_devices
        if self.audio_devices:
            default_mic_idx, default_system_idx = -1, -1; mic_keywords = ["микрофон", "microphone", "mic array", "(realtek(r) audio)"]; default_mic_idx = next((i for i, device in enumerate(self.audio_devices) if any(keyword in device.lower() for keyword in mic_keywords) and "voicemeeter" not in device.lower()), -1)
            if default_mic_idx == -1: default_mic_idx = next((i for i, device in enumerate(self.audio_devices) if any(keyword in device.lower() for keyword in mic_keywords)), -1)
            if default_mic_idx != -1: self.mic_device_combo.current(default_mic_idx)
            elif self.audio_devices: self.mic_device_combo.current(0)
            system_keywords = ["стерео микшер", "stereo mix", "what u hear", "смеситель"]; default_system_idx = next((i for i, device in enumerate(self.audio_devices) if any(keyword in device.lower() for keyword in system_keywords) and "voicemeeter" not in device.lower() and (default_mic_idx == -1 or i != default_mic_idx)), -1)
            if default_system_idx == -1: default_system_idx = next((i for i, device in enumerate(self.audio_devices) if "voicemeeter out" in device.lower() and (default_mic_idx == -1 or i != default_mic_idx) and not (default_mic_idx != -1 and self.audio_devices[default_mic_idx] == device and len(self.audio_devices) > (default_mic_idx +1))), -1)
            if default_system_idx != -1: self.system_audio_device_combo.current(default_system_idx)
            elif len(self.audio_devices) > 1: self.system_audio_device_combo.current(1 if default_mic_idx == 0 else 0)
            elif self.audio_devices: self.system_audio_device_combo.current(0)
            if not self.is_recording: self.status_label.config(text="Статус: Аудиоустройства обновлены.")
        else:
            if not self.is_recording: self.status_label.config(text="Статус: Аудиоустройства не найдены. Проверьте консоль."); messagebox.showwarning("Аудио", "Не удалось найти аудиоустройства DirectShow.")

    def select_output_directory(self): # (без изменений)
        dir_path = filedialog.askdirectory();
        if dir_path: self.output_dir_entry.delete(0, tk.END); self.output_dir_entry.insert(0, dir_path)
    
    def _capture_and_pipe_to_ffmpeg(self, ffmpeg_process_stdin, target_width, target_height, stop_event):
        frame_count = 0; fps = DEFAULT_FRAMERATE; frame_duration = 1.0 / fps
        ffmpeg_input_width = int(target_width // 2 * 2); ffmpeg_input_height = int(target_height // 2 * 2)
        
        if ffmpeg_input_width <= 0 or ffmpeg_input_height <= 0: 
            print(f"[CaptureThread] Ошибка: Некорректные целевые размеры: {ffmpeg_input_width}x{ffmpeg_input_height}")
            if hasattr(ffmpeg_process_stdin, 'close') and not ffmpeg_process_stdin.closed:
                try: ffmpeg_process_stdin.close()
                except Exception: pass # Исправлено: добавлен Exception
            self.master.after(0, lambda: messagebox.showerror("Ошибка Захвата", "Некорректные размеры окна.")); self.master.after(0, self.stop_recording); return
        
        print(f"[CaptureThread] Захват окна ({self.window_capturer.hwnd}): -> FFmpeg {ffmpeg_input_width}x{ffmpeg_input_height} @ {fps} FPS")
        try:
            last_frame_time = time.perf_counter()
            while not stop_event.is_set():
                current_time = time.perf_counter(); sleep_duration = frame_duration - (current_time - last_frame_time)
                if sleep_duration > 0: time.sleep(sleep_duration)
                last_frame_time = time.perf_counter()
                if not self.window_capturer or not win32gui.IsWindow(self.window_capturer.hwnd): print("[CaptureThread] Окно закрыто/capturer невалиден."); break
                
                window_frame = self.window_capturer.grab_frame()
                # print(f"[CaptureThread] window_frame is None: {window_frame is None}") 
                
                if window_frame is None: 
                    # print(f"[CaptureThread] grab_frame() вернул None для HWND {self.window_capturer.hwnd}")
                    time.sleep(0.01); continue
                
                # Убедимся, что размеры кадра соответствуют ожидаемым FFmpeg
                if window_frame.shape[1] != ffmpeg_input_width or window_frame.shape[0] != ffmpeg_input_height:
                    final_frame = cv2.resize(window_frame, (ffmpeg_input_width, ffmpeg_input_height), interpolation=cv2.INTER_AREA)
                else: 
                    final_frame = window_frame
                
                try:
                    ffmpeg_process_stdin.write(final_frame.tobytes()); ffmpeg_process_stdin.flush(); frame_count += 1
                except (OSError, ValueError, BrokenPipeError) as e: 
                    if not stop_event.is_set(): print(f"[CaptureThread] Ошибка записи в stdin FFmpeg: {e}."); break 
        except Exception as e: print(f"[CaptureThread] Ошибка в цикле захвата: {e}")
        finally:
            if hasattr(ffmpeg_process_stdin, 'close') and not ffmpeg_process_stdin.closed:
                try: 
                    print("[CaptureThread] Закрытие stdin FFmpeg.")
                    ffmpeg_process_stdin.close()
                except Exception as e_close: # Исправлено: добавлен except
                    print(f"[CaptureThread] Ошибка при закрытии stdin FFmpeg: {e_close}")
            print(f"[CaptureThread] Завершено. Записано кадров: {frame_count}")

    def _run_recording_thread(self, window_title, output_file, mic_device, system_audio_device, geometry):
        target_width = geometry['width']; target_height = geometry['height']
        input_width = int(target_width // 2 * 2); input_height = int(target_height // 2 * 2)
        if input_width <= 0 or input_height <= 0: self.master.after(0, self._handle_ffmpeg_result, {"return_code": -101, "stderr": "Некорректные размеры."}); return
        if not self.window_capturer: self.master.after(0, self._handle_ffmpeg_result, {"return_code": -102, "stderr": "Window capturer не инициализирован."}); return
        
        self.ffmpeg_process = run_ffmpeg_recording_from_pipe(output_file, mic_device, system_audio_device, input_width, input_height, DEFAULT_FRAMERATE)
        if not self.ffmpeg_process or self.ffmpeg_process.poll() is not None:
            stderr_output = "Неизвестная ошибка FFmpeg.";
            if self.ffmpeg_process:
                try: stderr_bytes = self.ffmpeg_process.stderr.read() if self.ffmpeg_process.stderr else b""; self.ffmpeg_process.stdout.read() ; stderr_output = stderr_bytes.decode('utf-8', errors='ignore');
                except Exception as e_read_err: stderr_output = f"FFmpeg завершился, не удалось прочитать stderr: {e_read_err}"
            else: stderr_output = "FFmpeg не был запущен."
            self.master.after(0, self._handle_ffmpeg_result, { "return_code": self.ffmpeg_process.returncode if self.ffmpeg_process else -100, "stderr": f"Не удалось запустить FFmpeg.\n{stderr_output}" }); return
        
        self.master.after(0, self._update_gui_for_recording_state_running)
        self.capture_thread_obj = threading.Thread(target=self._capture_and_pipe_to_ffmpeg, args=(self.ffmpeg_process.stdin, input_width, input_height, self.stop_event), daemon=True); self.capture_thread_obj.start()
        
        ffmpeg_stderr_lines = []
        def log_ffmpeg_stderr():
            remaining_stderr_str = "" # Инициализация
            try:
                for line_bytes in iter(self.ffmpeg_process.stderr.readline, b''):
                    line_str = line_bytes.decode('utf-8', errors='ignore').strip();
                    if line_str: ffmpeg_stderr_lines.append(line_str); print(f"[FFmpeg STDERR] {line_str}") 
                    if self.stop_event.is_set() and self.ffmpeg_process.poll() is not None: break
                remaining_stderr_bytes = self.ffmpeg_process.stderr.read()
                if remaining_stderr_bytes: remaining_stderr_str = remaining_stderr_bytes.decode('utf-8', errors='ignore').strip(); # Эта строка была продублирована
                if remaining_stderr_str: # Проверка на непустую строку
                     print(f"[FFmpeg STDERR - remaining] {remaining_stderr_str}"); ffmpeg_stderr_lines.extend(remaining_stderr_str.splitlines())
            except Exception as e: print(f"[FFmpeg STDERR Thread] Ошибка чтения stderr: {e}")
            finally:
                if self.ffmpeg_process and hasattr(self.ffmpeg_process.stderr, 'close') and not self.ffmpeg_process.stderr.closed:
                     try: self.ffmpeg_process.stderr.close()
                     except Exception: pass 
                print("[FFmpeg STDERR Thread] Завершён.")
        self.ffmpeg_stderr_thread = threading.Thread(target=log_ffmpeg_stderr, daemon=True); self.ffmpeg_stderr_thread.start()
        
        ffmpeg_return_code = self.ffmpeg_process.wait() 
        
        if self.ffmpeg_stderr_thread and self.ffmpeg_stderr_thread.is_alive(): print("[RecordingThread] Ожидание завершения потока чтения FFmpeg stderr..."); self.ffmpeg_stderr_thread.join(timeout=1)
        if self.capture_thread_obj and self.capture_thread_obj.is_alive(): print("[RecordingThread] Ожидание завершения потока захвата после FFmpeg..."); self.capture_thread_obj.join(timeout=1) 
        
        ffmpeg_stdout_output = ""
        try:
            if self.ffmpeg_process.stdout: 
                stdout_bytes = self.ffmpeg_process.stdout.read(); ffmpeg_stdout_output = stdout_bytes.decode('utf-8', errors='ignore')
                if hasattr(self.ffmpeg_process.stdout, 'close') and not self.ffmpeg_process.stdout.closed: self.ffmpeg_process.stdout.close()
        except Exception as e_stdout: print(f"[RecordingThread] Ошибка чтения stdout FFmpeg: {e_stdout}")
        
        self.master.after(0, self._handle_ffmpeg_result, { "return_code": ffmpeg_return_code, "stdout": ffmpeg_stdout_output, "stderr": "\n".join(ffmpeg_stderr_lines) })

    def _update_gui_for_recording_state_running(self): # (без изменений)
        if self.is_recording:
            if self.current_output_file: self.status_label.config(text=f"Статус: Идет запись в {os.path.basename(self.current_output_file)}...")
            else: self.status_label.config(text="Статус: Идет запись...")

    def _handle_ffmpeg_result(self, ffmpeg_result): # (Без изменений от v0.14.1)
        if not ffmpeg_result: self.status_label.config(text="Статус: Ошибка запуска FFmpeg."); self.stop_recording_logic_if_needed(); return
        return_code = ffmpeg_result.get("return_code", -1); stderr_data = ffmpeg_result.get("stderr", ""); stdout_data = ffmpeg_result.get("stdout", "")
        log_message = f"FFmpeg завершился.\nКод: {return_code}\n";
        if stdout_data: log_message += f"STDOUT:\n{stdout_data[-1000:]}\n" 
        if stderr_data: log_message += f"STDERR:\n{stderr_data[-2000:]}\n" 
        print(f"[AppGUI] Результат FFmpeg:\n{log_message}")
        if return_code == -102: messagebox.showerror("Ошибка Захвата", stderr_data or "Window capturer не был инициализирован."); self.status_label.config(text="Статус: Ошибка инициализации захвата.")
        elif return_code == -99: messagebox.showerror("Ошибка FFmpeg", stderr_data or "FFmpeg не найден."); self.status_label.config(text="Статус: Ошибка! FFmpeg не найден.")
        elif return_code == -100: messagebox.showerror("Ошибка запуска FFmpeg", stderr_data or "Не удалось запустить FFmpeg."); self.status_label.config(text="Статус: Ошибка запуска FFmpeg.")
        elif return_code == -101: messagebox.showerror("Ошибка геометрии", stderr_data or "Некорректные размеры окна."); self.status_label.config(text="Статус: Ошибка геометрии окна.")
        elif return_code != 0 : 
            short_err_for_msgbox = stderr_data if len(stderr_data) < 1000 else stderr_data[-1000:]
            messagebox.showerror("Ошибка FFmpeg", f"FFmpeg завершился с ошибкой.\nКод: {return_code}\n\nSTDERR (часть):\n{short_err_for_msgbox}\n\nСмотрите полную консоль для деталей.")
            if not self.stop_event.is_set(): self.status_label.config(text=f"Статус: Ошибка FFmpeg (код {return_code}).")
            else: self.status_label.config(text=f"Статус: Запись остановлена (FFmpeg код {return_code}).")
        elif self.stop_event.is_set(): self.status_label.config(text=f"Статус: Запись остановлена (FFmpeg код {return_code}).")
        else: self.status_label.config(text="Статус: Запись успешно завершена.") 
        self.stop_recording_logic_if_needed()
    
    def start_recording(self): # (Без изменений от v0.14.1)
        selected_title = self.window_combo.get(); output_dir = self.output_dir_entry.get(); mic_device = self.mic_device_combo.get(); system_audio_device = self.system_audio_device_combo.get()
        if not selected_title: messagebox.showerror("Ошибка", "Выберите окно."); return
        if not output_dir: messagebox.showerror("Ошибка", "Укажите папку."); return
        if not os.path.isdir(output_dir): messagebox.showerror("Ошибка", f"Папка '{output_dir}' не существует."); return
        if not mic_device: messagebox.showerror("Ошибка", "Выберите микрофон."); return
        if not system_audio_device: messagebox.showerror("Ошибка", "Выберите устройство системного звука."); return
        if mic_device == system_audio_device:
            if not messagebox.askyesno("Предупреждение", "Микрофон и системный звук выбраны одинаковыми. Продолжить?"): return
        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"); filename = f"record_{current_time}.mp4"; self.current_output_file = os.path.join(output_dir, filename) 
        self.selected_hwnd = self.window_titles_map.get(selected_title)
        if not self.selected_hwnd or not win32gui.IsWindow(self.selected_hwnd): messagebox.showerror("Ошибка", f"Окно '{selected_title}' больше не существует."); self.populate_window_list(); return
        self.stop_event.clear(); self.prevent_minimize_thread = threading.Thread(target=prevent_minimize_loop, args=(self.selected_hwnd, self.stop_event), daemon=True); self.prevent_minimize_thread.start(); time.sleep(0.2) 
        initial_window_geom = None
        for attempt in range(10): 
            if win32gui.IsWindow(self.selected_hwnd) and win32gui.IsIconic(self.selected_hwnd): print(f"[AppGUI] Окно '{selected_title}' свернуто (попытка {attempt+1}). Восстанавливаем..."); win32gui.ShowWindow(self.selected_hwnd, win32con.SW_RESTORE); time.sleep(0.2) ; self.master.update_idletasks()
            geom_candidate = get_window_geometry(self.selected_hwnd)
            if geom_candidate and geom_candidate['width'] > 32 and geom_candidate['height'] > 32 and geom_candidate['x'] > -32000: initial_window_geom = geom_candidate; print(f"[AppGUI] Геометрия окна получена (попытка {attempt+1}): {initial_window_geom}"); break
            print(f"[AppGUI] Попытка {attempt+1} получить геометрию: {geom_candidate}. Ожидание..."); time.sleep(0.15); self.master.update_idletasks() 
        if not initial_window_geom:
            self.stop_event.set(); 
            if self.prevent_minimize_thread and self.prevent_minimize_thread.is_alive(): self.prevent_minimize_thread.join(timeout=0.5)
            messagebox.showerror("Ошибка", f"Не удалось получить корректную геометрию окна '{selected_title}'."); return
        try:
            print(f"[AppGUI] Инициализация WindowCapture для HWND: {self.selected_hwnd}")
            self.window_capturer = WindowCapture(self.selected_hwnd) 
            if self.window_capturer.width <=0 or self.window_capturer.height <=0: raise RuntimeError("WindowCapture инициализирован с некорректными размерами.")
            print(f"[AppGUI] WindowCapture инициализирован. Размеры клиентской области: {self.window_capturer.width}x{self.window_capturer.height}")
            capture_geom_for_ffmpeg = {'width': self.window_capturer.width, 'height': self.window_capturer.height}
        except Exception as e_capture_init:
            print(f"[AppGUI] Ошибка инициализации WindowCapture: {e_capture_init}"); messagebox.showerror("Ошибка захвата", f"Не удалось инициализировать захват окна: {e_capture_init}")
            self.stop_event.set(); 
            if self.prevent_minimize_thread and self.prevent_minimize_thread.is_alive(): self.prevent_minimize_thread.join(timeout=0.5)
            return
        self.is_recording = True; self._update_gui_for_recording_state(True) 
        self.recording_thread = threading.Thread(target=self._run_recording_thread, args=(selected_title, self.current_output_file, mic_device, system_audio_device, capture_geom_for_ffmpeg), daemon=True); self.recording_thread.start()

    def _update_gui_for_recording_state(self, recording_active): # (без изменений)
        btn_text, btn_bg = ("Остановить запись", "salmon") if recording_active else ("Начать запись", "lightgreen"); widget_state, combo_state = ("disabled", "disabled") if recording_active else ("normal", "readonly"); self.record_button.config(text=btn_text, bg=btn_bg); 
        for widget in [self.browse_button, self.refresh_windows_button, self.refresh_audio_button, self.output_dir_entry]: widget.config(state=widget_state)
        for combo in [self.window_combo, self.mic_device_combo, self.system_audio_device_combo]: combo.config(state=combo_state)
        if recording_active: 
            if self.current_output_file: self.status_label.config(text=f"Статус: Идет запись в {os.path.basename(self.current_output_file)}...")
            else: self.status_label.config(text="Статус: Идет запись...")

    def stop_recording_logic_if_needed(self): # (без изменений)
        if self.is_recording: print("[AppGUI] stop_recording_logic_if_needed: Обновляем GUI."); 
        if not self.stop_event.is_set(): self.stop_event.set(); self.stop_recording_logic() 

    def stop_recording_logic(self):
        print("[AppGUI] Вызвана stop_recording_logic"); self.is_recording = False; self._update_gui_for_recording_state(False); 
        if self.capture_thread_obj and self.capture_thread_obj.is_alive(): print("[AppGUI] stop_recording_logic: Поток захвата жив, ожидание..."); self.capture_thread_obj.join(timeout=1) 
        if self.ffmpeg_stderr_thread and self.ffmpeg_stderr_thread.is_alive(): print("[AppGUI] stop_recording_logic: Поток stderr FFmpeg жив, ожидание..."); self.ffmpeg_stderr_thread.join(timeout=1)
        
        if self.window_capturer:
            print("[AppGUI] Освобождение ресурсов WindowCapture...")
            self.window_capturer.close() # Используем явный метод close
            self.window_capturer = None

        self.prevent_minimize_thread = None; self.recording_thread = None ; self.capture_thread_obj = None; self.ffmpeg_stderr_thread = None; self.ffmpeg_process = None ; self.current_output_file = "" 

    def stop_recording(self): # (Без изменений от v0.14.1)
        if not self.is_recording: return
        print("[AppGUI] Пользователь остановил запись."); self.status_label.config(text="Статус: Остановка записи..."); self.master.update_idletasks(); self.stop_event.set() 
        if self.recording_thread and self.recording_thread.is_alive(): print("[AppGUI] Ожидание завершения основного потока записи (FFmpeg)..."); self.recording_thread.join(timeout=10) 
        if self.prevent_minimize_thread and self.prevent_minimize_thread.is_alive(): print("[AppGUI] Ожидание завершения потока защиты от сворачивания..."); self.prevent_minimize_thread.join(timeout=1)
        if self.recording_thread and self.recording_thread.is_alive():
            print("[AppGUI] stop_recording: Поток записи НЕ завершился по таймауту. FFmpeg мог зависнуть.")
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                print("[AppGUI] FFmpeg все еще работает. Принудительное завершение (terminate).")
                try: self.ffmpeg_process.terminate()
                except Exception as e_term: print(f"Ошибка при terminate FFmpeg: {e_term}")
                try: self.ffmpeg_process.wait(timeout=2) 
                except subprocess.TimeoutExpired: print("[AppGUI] FFmpeg не завершился после terminate. Принудительное завершение (kill).");
                try: self.ffmpeg_process.kill()
                except Exception as e_kill: print(f"Ошибка при kill FFmpeg: {e_kill}")
            self.stop_recording_logic()
        else: 
            if self.is_recording: print("[AppGUI] stop_recording: Поток записи завершен, вызываем stop_recording_logic."); self.stop_recording_logic()
        current_status = self.status_label.cget("text")
        if "Остановка записи..." in current_status or "Идет запись" in current_status or "Подготовка к записи" in current_status: self.status_label.config(text="Статус: Запись остановлена пользователем.")
        print("[AppGUI] Процесс остановки записи (пользователем) завершен.")

    def on_closing(self): # (без изменений)
        if self.is_recording:
            if messagebox.askyesno("Запись активна", "Идет запись. Вы уверены, что хотите выйти?"): self.stop_recording(); self.master.destroy()
        else: self.master.destroy()