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

NO_AUDIO_DEVICE_SELECTED = "<Нет>" 

class ScreenRecorderApp:
    def __init__(self, master):
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
            
        master.title("Video Recorder v0.16.0 (Triple Audio Input)") 
        master.geometry("700x480") # Немного увеличим высоту для нового поля
        self.is_recording = False; self.prevent_minimize_thread = None; self.recording_thread = None
        self.capture_thread_obj = None; self.ffmpeg_process = None; self.ffmpeg_stderr_thread = None 
        self.stop_event = threading.Event(); self.selected_hwnd = None; self.window_titles_map = {}
        self.audio_devices = []; self.current_output_file = ""; self.window_capturer = None 
        self._setup_gui(); self.populate_window_list(); self.populate_audio_device_lists(); master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_gui(self):
        row_idx = 0
        tk.Label(self.master, text="Окно для записи:").grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
        self.window_combo = ttk.Combobox(self.master, width=75, state="readonly")
        self.window_combo.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_windows_button = tk.Button(self.master, text="Обновить Окна", command=self.populate_window_list)
        self.refresh_windows_button.grid(row=row_idx, column=2, padx=5, pady=5)
        row_idx += 1

        tk.Label(self.master, text="Папка для сохранения:").grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
        self.output_dir_entry = tk.Entry(self.master, width=75)
        self.output_dir_entry.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = tk.Button(self.master, text="Обзор...", command=self.select_output_directory)
        self.browse_button.grid(row=row_idx, column=2, padx=5, pady=5)
        row_idx += 1

        tk.Label(self.master, text="Микрофон (dshow):").grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
        self.mic_device_combo = ttk.Combobox(self.master, width=75, state="readonly")
        self.mic_device_combo.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
        row_idx += 1

        tk.Label(self.master, text="Звук системы 1 (dshow):").grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
        self.system_audio_device_combo1 = ttk.Combobox(self.master, width=75, state="readonly")
        self.system_audio_device_combo1.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
        row_idx += 1
        
        tk.Label(self.master, text="Звук системы 2 (dshow):").grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
        self.system_audio_device_combo2 = ttk.Combobox(self.master, width=75, state="readonly")
        self.system_audio_device_combo2.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
        
        self.refresh_audio_button = tk.Button(self.master, text="Обновить Аудио", command=self.populate_audio_device_lists)
        self.refresh_audio_button.grid(row=row_idx-2, column=2, rowspan=3, padx=5, pady=5, sticky="ns") 
        row_idx += 1

        self.record_button = tk.Button(self.master, text="Начать запись", command=self.toggle_recording, bg="lightgreen", height=2)
        self.record_button.grid(row=row_idx, column=0, columnspan=3, padx=5, pady=15, sticky="ew")
        row_idx += 1
        
        self.status_label = tk.Label(self.master, text="Статус: Ожидание", relief=tk.SUNKEN, anchor="w")
        self.status_label.grid(row=row_idx, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        self.master.grid_columnconfigure(1, weight=1)

    def toggle_recording(self):
        if self.is_recording: self.stop_recording()
        else: self.start_recording()

    def populate_window_list(self): # (без изменений)
        self.window_combo['values'] = []; self.window_titles_map = get_active_windows(); sorted_titles = sorted(self.window_titles_map.keys()); self.window_combo['values'] = sorted_titles; 
        if sorted_titles: self.window_combo.current(0)
        if not self.is_recording: self.status_label.config(text="Статус: Список окон обновлен.")

    def populate_audio_device_lists(self): # (Изменена логика выбора по умолчанию)
        print("[AppGUI] Обновление списка аудиоустройств..."); 
        if not self.is_recording: self.status_label.config(text="Статус: Обновление списка аудиоустройств...")
        self.master.update_idletasks()
        
        raw_audio_devices = get_dshow_audio_devices()
        print(f"[AppGUI] Получены аудиоустройства (после get_dshow_audio_devices): {raw_audio_devices}")
        
        self.audio_devices = [NO_AUDIO_DEVICE_SELECTED] + raw_audio_devices
        
        self.mic_device_combo['values'] = self.audio_devices
        self.system_audio_device_combo1['values'] = self.audio_devices
        self.system_audio_device_combo2['values'] = self.audio_devices

        # Установка значений по умолчанию
        self.mic_device_combo.current(0) # По умолчанию "<Нет>"
        self.system_audio_device_combo1.current(0) # По умолчанию "<Нет>"
        self.system_audio_device_combo2.current(0) # По умолчанию "<Нет>"

        if raw_audio_devices:
            # Пытаемся найти микрофон
            mic_keywords = ["микрофон", "microphone", "mic array", "nvidia broadcast"]
            default_mic_idx = 0 
            for i, device in enumerate(raw_audio_devices):
                if any(keyword in device.lower() for keyword in mic_keywords):
                    self.mic_device_combo.current(i + 1)
                    default_mic_idx = i + 1
                    break
            
            # Пытаемся найти первый системный звук (не микрофон)
            system_keywords1 = ["стерео микшер", "stereo mix", "what u hear", "смеситель", "voicemeeter out a1"]
            default_sys1_idx = 0
            for i, device in enumerate(raw_audio_devices):
                if self.audio_devices[default_mic_idx] == device and default_mic_idx != 0: # Не выбираем тот же, что и микрофон
                    continue
                if any(keyword in device.lower() for keyword in system_keywords1):
                    self.system_audio_device_combo1.current(i + 1)
                    default_sys1_idx = i + 1
                    break
            if default_sys1_idx == 0 and len(raw_audio_devices) > (1 if default_mic_idx !=0 else 0) : # Если не нашли, но есть еще устройства
                # Пытаемся выбрать первое не микрофонное устройство
                candidate_idx = 1
                if default_mic_idx == 1 and len(raw_audio_devices) > 1: candidate_idx = 2
                if candidate_idx <= len(raw_audio_devices):
                     self.system_audio_device_combo1.current(candidate_idx)
                     default_sys1_idx = candidate_idx


            # Пытаемся найти второй системный звук (не микрофон и не первый системный)
            system_keywords2 = ["voicemeeter out a2", "voicemeeter out b1"] # Приоритет для других шин Voicemeeter
            default_sys2_idx = 0
            for i, device in enumerate(raw_audio_devices):
                if self.audio_devices[default_mic_idx] == device and default_mic_idx != 0:
                    continue
                if self.audio_devices[default_sys1_idx] == device and default_sys1_idx != 0:
                    continue
                if any(keyword in device.lower() for keyword in system_keywords2):
                    self.system_audio_device_combo2.current(i + 1)
                    default_sys2_idx = i + 1
                    break
            # Если не нашли по приоритетным, ищем по общим системным, отличным от уже выбранных
            if default_sys2_idx == 0:
                 for i, device in enumerate(raw_audio_devices):
                    if self.audio_devices[default_mic_idx] == device and default_mic_idx != 0: continue
                    if self.audio_devices[default_sys1_idx] == device and default_sys1_idx != 0: continue
                    if any(keyword in device.lower() for keyword in system_keywords1): # Используем общие ключевые слова
                        self.system_audio_device_combo2.current(i + 1)
                        break


            if not self.is_recording: self.status_label.config(text="Статус: Аудиоустройства обновлены.")
        else: 
            if not self.is_recording: self.status_label.config(text="Статус: Аудиоустройства не найдены. Проверьте консоль.");
            messagebox.showwarning("Аудио", "Не удалось найти аудиоустройства DirectShow. Запись звука будет невозможна.")

    def select_output_directory(self): # (без изменений)
        dir_path = filedialog.askdirectory();
        if dir_path: self.output_dir_entry.delete(0, tk.END); self.output_dir_entry.insert(0, dir_path)
    
    def _capture_and_pipe_to_ffmpeg(self, ffmpeg_process_stdin, target_width, target_height, stop_event): # (Без изменений)
        frame_count = 0; fps = DEFAULT_FRAMERATE; frame_duration = 1.0 / fps
        ffmpeg_input_width = int(target_width // 2 * 2); ffmpeg_input_height = int(target_height // 2 * 2)
        
        if ffmpeg_input_width <= 0 or ffmpeg_input_height <= 0: 
            print(f"[CaptureThread] Ошибка: Некорректные целевые размеры: {ffmpeg_input_width}x{ffmpeg_input_height}")
            if hasattr(ffmpeg_process_stdin, 'close') and not ffmpeg_process_stdin.closed:
                try: ffmpeg_process_stdin.close()
                except Exception as e_close_pipe: print(f"[CaptureThread] Ошибка при закрытии stdin (некорр. размеры): {e_close_pipe}")
            self.master.after(0, lambda: messagebox.showerror("Ошибка Захвата", "Некорректные размеры окна.")); self.master.after(0, self.stop_recording); return
        
        print(f"[CaptureThread] Захват окна ({self.window_capturer.hwnd}): -> FFmpeg {ffmpeg_input_width}x{ffmpeg_input_height} @ {fps} FPS")
        
        try:
            last_frame_time = time.perf_counter()
            while not stop_event.is_set():
                current_time = time.perf_counter(); sleep_duration = frame_duration - (current_time - last_frame_time)
                if sleep_duration > 0: time.sleep(sleep_duration)
                last_frame_time = time.perf_counter()
                
                if not self.window_capturer or not win32gui.IsWindow(self.window_capturer.hwnd): 
                    print("[CaptureThread] Окно закрыто или capturer невалиден."); break
                
                window_frame = self.window_capturer.grab_frame()
                
                if window_frame is None: 
                    time.sleep(0.01); continue 
                
                if window_frame.shape[1] != ffmpeg_input_width or window_frame.shape[0] != ffmpeg_input_height:
                    final_frame = cv2.resize(window_frame, (ffmpeg_input_width, ffmpeg_input_height), interpolation=cv2.INTER_AREA)
                else: 
                    final_frame = window_frame
                
                try:
                    ffmpeg_process_stdin.write(final_frame.tobytes()); ffmpeg_process_stdin.flush(); frame_count += 1
                except (OSError, ValueError, BrokenPipeError) as e_pipe: 
                    if not stop_event.is_set(): print(f"[CaptureThread] Ошибка записи в stdin FFmpeg: {e_pipe}."); 
                    break 
        except Exception as e_loop: 
            print(f"[CaptureThread] Ошибка в цикле захвата: {e_loop}")
        finally:
            if hasattr(ffmpeg_process_stdin, 'close') and not ffmpeg_process_stdin.closed:
                try: 
                    print("[CaptureThread] Закрытие stdin FFmpeg.")
                    ffmpeg_process_stdin.close()
                except Exception as e_close_final: 
                    print(f"[CaptureThread] Ошибка при закрытии stdin FFmpeg в finally: {e_close_final}")
            print(f"[CaptureThread] Завершено. Записано кадров: {frame_count}")

    def _run_recording_thread(self, window_title, output_file, audio_device_list, geometry): # Изменен параметр
        
        # audio_device_list теперь содержит имена выбранных устройств (или None)
        # ffmpeg_utils.py будет отвечать за их обработку

        target_width = geometry['width']; target_height = geometry['height']
        input_width = int(target_width // 2 * 2); input_height = int(target_height // 2 * 2)

        if input_width <= 0 or input_height <= 0: 
            self.master.after(0, self._handle_ffmpeg_result, {"return_code": -101, "stderr": "Некорректные размеры."})
            return
        if not self.window_capturer: 
            self.master.after(0, self._handle_ffmpeg_result, {"return_code": -102, "stderr": "Window capturer не инициализирован."})
            return
        
        record_audio_flag = any(audio_device_list) # True если хотя бы одно устройство выбрано

        self.ffmpeg_process = run_ffmpeg_recording_from_pipe(
            output_file, 
            audio_device_list, # Передаем список имен устройств
            input_width, input_height, DEFAULT_FRAMERATE, 
            record_audio=record_audio_flag
        )
        
        if not self.ffmpeg_process or self.ffmpeg_process.poll() is not None:
            stderr_output = "Неизвестная ошибка FFmpeg.";
            if self.ffmpeg_process:
                try: 
                    stderr_bytes = self.ffmpeg_process.stderr.read() if self.ffmpeg_process.stderr else b""
                    stderr_output = stderr_bytes.decode('utf-8', errors='ignore');
                except Exception as e_read_err: stderr_output = f"FFmpeg завершился, не удалось прочитать stderr: {e_read_err}"
            else: stderr_output = "FFmpeg не был запущен."
            self.master.after(0, self._handle_ffmpeg_result, { "return_code": self.ffmpeg_process.returncode if self.ffmpeg_process else -100, "stderr": f"Не удалось запустить FFmpeg.\n{stderr_output}" }); return
        
        self.master.after(0, self._update_gui_for_recording_state_running)
        self.capture_thread_obj = threading.Thread(target=self._capture_and_pipe_to_ffmpeg, args=(self.ffmpeg_process.stdin, input_width, input_height, self.stop_event), daemon=True); self.capture_thread_obj.start()
        
        ffmpeg_stderr_lines = []
        def log_ffmpeg_stderr(): # (Без изменений)
            remaining_stderr_str = "" 
            try:
                for line_bytes in iter(self.ffmpeg_process.stderr.readline, b''): 
                    line_str = line_bytes.decode('utf-8', errors='ignore').strip();
                    if line_str: ffmpeg_stderr_lines.append(line_str); print(f"[FFmpeg STDERR] {line_str}") 
                    if self.stop_event.is_set() and self.ffmpeg_process.poll() is not None: break
                
                if self.ffmpeg_process.stderr and not self.ffmpeg_process.stderr.closed:
                    remaining_stderr_bytes = self.ffmpeg_process.stderr.read()
                    if remaining_stderr_bytes: 
                        remaining_stderr_str = remaining_stderr_bytes.decode('utf-8', errors='ignore').strip();
                        if remaining_stderr_str: 
                             print(f"[FFmpeg STDERR - remaining] {remaining_stderr_str}"); ffmpeg_stderr_lines.extend(remaining_stderr_str.splitlines())
            except Exception as e_stderr_read: 
                print(f"[FFmpeg STDERR Thread] Ошибка чтения stderr: {e_stderr_read}")
            finally:
                if self.ffmpeg_process and hasattr(self.ffmpeg_process.stderr, 'close') and not self.ffmpeg_process.stderr.closed:
                     try: self.ffmpeg_process.stderr.close()
                     except Exception: pass 
                print("[FFmpeg STDERR Thread] Завершён.")
        self.ffmpeg_stderr_thread = threading.Thread(target=log_ffmpeg_stderr, daemon=True); self.ffmpeg_stderr_thread.start()
        
        ffmpeg_return_code = self.ffmpeg_process.wait() 
        
        if self.ffmpeg_stderr_thread and self.ffmpeg_stderr_thread.is_alive(): 
            print("[RecordingThread] Ожидание завершения потока чтения FFmpeg stderr..."); self.ffmpeg_stderr_thread.join(timeout=1)
        if self.capture_thread_obj and self.capture_thread_obj.is_alive(): 
            print("[RecordingThread] Ожидание завершения потока захвата после FFmpeg..."); self.capture_thread_obj.join(timeout=1) 
        
        ffmpeg_stdout_output = ""
        if self.ffmpeg_process.stdout and not self.ffmpeg_process.stdout.closed:
            try:
                stdout_bytes = self.ffmpeg_process.stdout.read(); 
                ffmpeg_stdout_output = stdout_bytes.decode('utf-8', errors='ignore')
                self.ffmpeg_process.stdout.close()
            except Exception as e_stdout: 
                print(f"[RecordingThread] Ошибка чтения/закрытия stdout FFmpeg: {e_stdout}")
        
        self.master.after(0, self._handle_ffmpeg_result, { "return_code": ffmpeg_return_code, "stdout": ffmpeg_stdout_output, "stderr": "\n".join(ffmpeg_stderr_lines) })

    def _update_gui_for_recording_state_running(self): # (без изменений)
        if self.is_recording:
            if self.current_output_file: self.status_label.config(text=f"Статус: Идет запись в {os.path.basename(self.current_output_file)}...")
            else: self.status_label.config(text="Статус: Идет запись...")

    def _handle_ffmpeg_result(self, ffmpeg_result): # (без изменений)
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
    
    def start_recording(self): # (Изменено для сбора трех аудиоустройств)
        selected_title = self.window_combo.get()
        output_dir = self.output_dir_entry.get()
        
        mic_device_selected = self.mic_device_combo.get()
        system_audio1_selected = self.system_audio_device_combo1.get()
        system_audio2_selected = self.system_audio_device_combo2.get()
        
        if not selected_title: messagebox.showerror("Ошибка", "Выберите окно."); return
        if not output_dir: messagebox.showerror("Ошибка", "Укажите папку."); return
        if not os.path.isdir(output_dir): messagebox.showerror("Ошибка", f"Папка '{output_dir}' не существует."); return
        
        # Собираем список активных аудиоустройств
        active_audio_devices = []
        if mic_device_selected != NO_AUDIO_DEVICE_SELECTED:
            active_audio_devices.append(mic_device_selected)
        if system_audio1_selected != NO_AUDIO_DEVICE_SELECTED:
            active_audio_devices.append(system_audio1_selected)
        if system_audio2_selected != NO_AUDIO_DEVICE_SELECTED:
            active_audio_devices.append(system_audio2_selected)

        # Проверка на дубликаты среди выбранных устройств
        if len(active_audio_devices) != len(set(active_audio_devices)) and len(active_audio_devices) > 0 :
             if not messagebox.askyesno("Предупреждение", "Выбраны одинаковые аудиоустройства в разных полях. Это может привести к неожиданному результату. Продолжить?"):
                return

        if not active_audio_devices: # Если ни одно аудиоустройство не выбрано
            if not messagebox.askyesno("Предупреждение", "Аудиоустройства не выбраны. Запись будет без звука. Продолжить?"):
                return
        
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
        
        # Формируем список устройств для передачи в _run_recording_thread
        # None будет передан, если выбрано NO_AUDIO_DEVICE_SELECTED
        audio_devices_to_pass = [
            mic_device_selected if mic_device_selected != NO_AUDIO_DEVICE_SELECTED else None,
            system_audio1_selected if system_audio1_selected != NO_AUDIO_DEVICE_SELECTED else None,
            system_audio2_selected if system_audio2_selected != NO_AUDIO_DEVICE_SELECTED else None,
        ]
        # Убираем None из списка, чтобы передать только активные устройства
        active_audio_devices_for_thread = [dev for dev in audio_devices_to_pass if dev is not None]
        
        # Убираем дубликаты перед передачей в поток, если они все же есть
        final_unique_audio_devices_for_thread = []
        for dev in active_audio_devices_for_thread:
            if dev not in final_unique_audio_devices_for_thread:
                final_unique_audio_devices_for_thread.append(dev)

        self.recording_thread = threading.Thread(
            target=self._run_recording_thread, 
            args=(selected_title, self.current_output_file, final_unique_audio_devices_for_thread, capture_geom_for_ffmpeg), 
            daemon=True
        )
        self.recording_thread.start()

    def _update_gui_for_recording_state(self, recording_active): # (без изменений)
        btn_text, btn_bg = ("Остановить запись", "salmon") if recording_active else ("Начать запись", "lightgreen"); widget_state, combo_state = ("disabled", "disabled") if recording_active else ("normal", "readonly"); self.record_button.config(text=btn_text, bg=btn_bg); 
        for widget in [self.browse_button, self.refresh_windows_button, self.refresh_audio_button, self.output_dir_entry]: widget.config(state=widget_state)
        for combo in [self.window_combo, self.mic_device_combo, self.system_audio_device_combo1, self.system_audio_device_combo2]: combo.config(state=combo_state)
        if recording_active: 
            if self.current_output_file: self.status_label.config(text=f"Статус: Идет запись в {os.path.basename(self.current_output_file)}...")
            else: self.status_label.config(text="Статус: Идет запись...")

    def stop_recording_logic_if_needed(self): # (без изменений)
        if self.is_recording: print("[AppGUI] stop_recording_logic_if_needed: Обновляем GUI."); 
        if not self.stop_event.is_set(): self.stop_event.set(); self.stop_recording_logic() 

    def stop_recording_logic(self): # (без изменений)
        print("[AppGUI] Вызвана stop_recording_logic"); self.is_recording = False; self._update_gui_for_recording_state(False); 
        if self.capture_thread_obj and self.capture_thread_obj.is_alive(): print("[AppGUI] stop_recording_logic: Поток захвата жив, ожидание..."); self.capture_thread_obj.join(timeout=1) 
        if self.ffmpeg_stderr_thread and self.ffmpeg_stderr_thread.is_alive(): print("[AppGUI] stop_recording_logic: Поток stderr FFmpeg жив, ожидание..."); self.ffmpeg_stderr_thread.join(timeout=1)
        if self.window_capturer:
            print("[AppGUI] Освобождение ресурсов WindowCapture...")
            self.window_capturer.close() 
            self.window_capturer = None
        self.prevent_minimize_thread = None; self.recording_thread = None ; self.capture_thread_obj = None; self.ffmpeg_stderr_thread = None; self.ffmpeg_process = None ; self.current_output_file = "" 

    def stop_recording(self): # (без изменений)
        if not self.is_recording: return
        print("[AppGUI] Пользователь остановил запись."); self.status_label.config(text="Статус: Остановка записи..."); self.master.update_idletasks(); self.stop_event.set(); time.sleep(0.1) 
        if self.recording_thread and self.recording_thread.is_alive(): print("[AppGUI] Ожидание завершения основного потока записи (FFmpeg)..."); self.recording_thread.join(timeout=7) 
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
