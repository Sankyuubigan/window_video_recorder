import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import datetime
import win32gui 

from windows_utils import get_active_windows, prevent_minimize_loop
from ffmpeg_utils import get_dshow_audio_devices, run_ffmpeg_recording

class ScreenRecorderApp:
    def __init__(self, master):
        self.master = master
        try:
            base_path = os.path.dirname(os.path.abspath(__file__)) 
            icon_path = os.path.join(base_path, "app_icon.ico") 
            if os.path.exists(icon_path):
                master.iconbitmap(icon_path)
            else:
                project_root_icon_path = os.path.join(os.path.dirname(base_path), "app_icon.ico")
                if os.path.exists(project_root_icon_path):
                     master.iconbitmap(project_root_icon_path)
                else:
                    print(f"[AppGUI] Файл иконки не найден ни по пути {icon_path}, ни по {project_root_icon_path}")
        except Exception as e:
            print(f"[AppGUI] Не удалось установить иконку окна: {e}")
            
        master.title("Video Conference Recorder v0.9 (Verbose Logging)")
        master.geometry("700x450")

        self.is_recording = False
        self.prevent_minimize_thread = None
        self.recording_thread = None
        self.stop_event = threading.Event()
        self.selected_hwnd = None
        self.window_titles_map = {}
        self.audio_devices = []

        self._setup_gui()
        self.populate_window_list()
        self.populate_audio_device_lists() 
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_gui(self):
        # (Без изменений)
        tk.Label(self.master, text="Окно для записи:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.window_combo = ttk.Combobox(self.master, width=75, state="readonly")
        self.window_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_windows_button = tk.Button(self.master, text="Обновить Окна", command=self.populate_window_list)
        self.refresh_windows_button.grid(row=0, column=2, padx=5, pady=5)
        tk.Label(self.master, text="Папка для сохранения:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.output_dir_entry = tk.Entry(self.master, width=75)
        self.output_dir_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = tk.Button(self.master, text="Обзор...", command=self.select_output_directory)
        self.browse_button.grid(row=1, column=2, padx=5, pady=5)
        tk.Label(self.master, text="Микрофон (dshow):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.mic_device_combo = ttk.Combobox(self.master, width=75, state="readonly")
        self.mic_device_combo.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        tk.Label(self.master, text="Системный звук (dshow):").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.system_audio_device_combo = ttk.Combobox(self.master, width=75, state="readonly")
        self.system_audio_device_combo.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_audio_button = tk.Button(self.master, text="Обновить Аудио", command=self.populate_audio_device_lists)
        self.refresh_audio_button.grid(row=2, column=2, rowspan=2, padx=5, pady=5, sticky="ns")
        self.record_button = tk.Button(self.master, text="Начать запись", command=self.toggle_recording, bg="lightgreen", height=2)
        self.record_button.grid(row=5, column=0, columnspan=3, padx=5, pady=15, sticky="ew")
        self.status_label = tk.Label(self.master, text="Статус: Ожидание", relief=tk.SUNKEN, anchor="w")
        self.status_label.grid(row=6, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        self.master.grid_columnconfigure(1, weight=1)

    def populate_window_list(self): # (Без изменений)
        self.window_combo['values'] = []
        self.window_titles_map = get_active_windows()
        sorted_titles = sorted(self.window_titles_map.keys())
        self.window_combo['values'] = sorted_titles
        if sorted_titles: self.window_combo.current(0)
        self.status_label.config(text="Статус: Список окон обновлен.")

    def populate_audio_device_lists(self): # (Без изменений)
        print("[AppGUI] Обновление списка аудиоустройств...")
        self.status_label.config(text="Статус: Обновление списка аудиоустройств...")
        self.master.update_idletasks()
        self.audio_devices = get_dshow_audio_devices() 
        print(f"[AppGUI] Получены аудиоустройства (после get_dshow_audio_devices): {self.audio_devices}")
        self.mic_device_combo['values'] = self.audio_devices
        self.system_audio_device_combo['values'] = self.audio_devices
        if self.audio_devices:
            default_mic_idx, default_system_idx = -1, -1
            mic_keywords = ["микрофон", "microphone", "mic array", "(realtek(r) audio)"]
            for i, device in enumerate(self.audio_devices):
                if any(keyword in device.lower() for keyword in mic_keywords) and "voicemeeter" not in device.lower():
                    default_mic_idx = i; break
            if default_mic_idx == -1: 
                 for i, device in enumerate(self.audio_devices):
                    if any(keyword in device.lower() for keyword in mic_keywords):
                        default_mic_idx = i; break
            if default_mic_idx != -1: self.mic_device_combo.current(default_mic_idx)
            elif self.audio_devices: self.mic_device_combo.current(0)
            system_keywords = ["стерео микшер", "stereo mix", "what u hear", "смеситель"]
            for i, device in enumerate(self.audio_devices):
                if any(keyword in device.lower() for keyword in system_keywords) and \
                   "voicemeeter" not in device.lower() and \
                   (default_mic_idx == -1 or i != default_mic_idx):
                    default_system_idx = i; break
            if default_system_idx == -1:
                for i, device in enumerate(self.audio_devices):
                    if "voicemeeter out" in device.lower() and (default_mic_idx == -1 or i != default_mic_idx):
                        default_system_idx = i; break
            if default_system_idx != -1: self.system_audio_device_combo.current(default_system_idx)
            elif len(self.audio_devices) > 1:
                potential_sys_idx = 1 if default_mic_idx == 0 else 0
                self.system_audio_device_combo.current(potential_sys_idx)
            elif self.audio_devices: self.system_audio_device_combo.current(0)
            self.status_label.config(text="Статус: Аудиоустройства обновлены.")
        else:
            self.status_label.config(text="Статус: Аудиоустройства не найдены. Проверьте консоль.")

    def select_output_directory(self): # (Без изменений)
        dir_path = filedialog.askdirectory()
        if dir_path: self.output_dir_entry.delete(0, tk.END); self.output_dir_entry.insert(0, dir_path)

    def _run_recording_thread(self, window_title, output_file, mic_device, system_audio_device): # (Без изменений)
        stop_event_ref = [self.stop_event] 
        ffmpeg_result = run_ffmpeg_recording(window_title, output_file, mic_device, system_audio_device, stop_event_ref)
        self.master.after(0, self._handle_ffmpeg_result, ffmpeg_result)

    def _handle_ffmpeg_result(self, ffmpeg_result):
        if not ffmpeg_result:
            self.status_label.config(text="Статус: Ошибка запуска FFmpeg.")
            self.stop_recording_logic_if_needed()
            return

        return_code = ffmpeg_result.get("return_code", -1)
        stderr_data = ffmpeg_result.get("stderr", "")
        stdout_data = ffmpeg_result.get("stdout", "") # Получаем и stdout

        # Формируем сообщение для лога и messagebox
        log_message = f"FFmpeg завершился.\nКод: {return_code}\n"
        if stdout_data: log_message += f"STDOUT:\n{stdout_data[-1000:]}\n" # Последние 1000 символов
        if stderr_data: log_message += f"STDERR:\n{stderr_data[-2000:]}\n" # Последние 2000 символов

        if return_code == -99: # FFmpeg не найден
             messagebox.showerror("Ошибка FFmpeg", stderr_data) # stderr_data уже содержит сообщение
             self.status_label.config(text="Статус: Ошибка! FFmpeg не найден.")
        elif return_code == -100: # Другая ошибка запуска
             messagebox.showerror("Ошибка запуска FFmpeg", stderr_data) # stderr_data уже содержит сообщение
             self.status_label.config(text="Статус: Ошибка запуска FFmpeg.")
        elif return_code != 0 : # Любая ошибка во время работы или при остановке
            # Показываем лог всегда, если код не 0
            messagebox.showerror("Ошибка FFmpeg", log_message)
            if not self.stop_event.is_set(): # Если не мы остановили
                self.status_label.config(text=f"Статус: Ошибка FFmpeg (код {return_code}).")
            else: # Мы остановили, но была ошибка
                self.status_label.config(text=f"Статус: Запись остановлена (FFmpeg код {return_code}).")
        elif self.stop_event.is_set(): # Остановлено пользователем, ffmpeg завершился корректно (код 0)
             self.status_label.config(text="Статус: Запись остановлена.")
        else: # Успешное завершение (код 0, не по stop_event)
             self.status_label.config(text="Статус: Запись успешно завершена.")
        
        print(f"[AppGUI] Результат FFmpeg обработан:\n{log_message}") # Логируем в консоль тоже
        self.stop_recording_logic_if_needed()

    def toggle_recording(self): # (Без изменений)
        if self.is_recording: self.stop_recording()
        else: self.start_recording()

    def start_recording(self): # (Без изменений)
        selected_title = self.window_combo.get()
        output_dir = self.output_dir_entry.get()
        mic_device = self.mic_device_combo.get()
        system_audio_device = self.system_audio_device_combo.get()
        if not selected_title: messagebox.showerror("Ошибка", "Выберите окно."); return
        if not output_dir: messagebox.showerror("Ошибка", "Укажите папку."); return
        if not os.path.isdir(output_dir): messagebox.showerror("Ошибка", f"Папка '{output_dir}' не существует."); return
        if not mic_device: messagebox.showerror("Ошибка", "Выберите микрофон."); return
        if not system_audio_device: messagebox.showerror("Ошибка", "Выберите устройство системного звука."); return
        if mic_device == system_audio_device:
            if not messagebox.askyesno("Предупреждение", "Микрофон и системный звук выбраны одинаковыми. Это может привести к удвоению звука микрофона. Продолжить?"): return
        current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"record_{current_time}.mp4"
        output_file = os.path.join(output_dir, filename)
        self.selected_hwnd = self.window_titles_map.get(selected_title)
        if not self.selected_hwnd or not win32gui.IsWindow(self.selected_hwnd):
            messagebox.showerror("Ошибка", f"Окно '{selected_title}' больше не существует. Обновите список."); self.populate_window_list(); return
        self.is_recording = True; self.stop_event.clear(); self._update_gui_for_recording_state(True)
        self.prevent_minimize_thread = threading.Thread(target=prevent_minimize_loop, args=(self.selected_hwnd, self.stop_event), daemon=True); self.prevent_minimize_thread.start()
        self.recording_thread = threading.Thread(target=self._run_recording_thread, args=(selected_title, output_file, mic_device, system_audio_device), daemon=True); self.recording_thread.start()

    def _update_gui_for_recording_state(self, recording_active): # (Без изменений)
        btn_text, btn_bg = ("Остановить запись", "salmon") if recording_active else ("Начать запись", "lightgreen")
        widget_state, combo_state = ("disabled", "disabled") if recording_active else ("normal", "readonly")
        self.record_button.config(text=btn_text, bg=btn_bg)
        for widget in [self.browse_button, self.refresh_windows_button, self.refresh_audio_button, self.output_dir_entry]: widget.config(state=widget_state)
        for combo in [self.window_combo, self.mic_device_combo, self.system_audio_device_combo]: combo.config(state=combo_state)
        if recording_active: self.status_label.config(text="Статус: Подготовка к записи...")

    def stop_recording_logic_if_needed(self): # (Без изменений)
        if self.is_recording and (not self.recording_thread or not self.recording_thread.is_alive()):
            print("[AppGUI] Поток записи завершен (или не был запущен), обновляем GUI, если еще не остановлено.")
            if not self.stop_event.is_set(): self.stop_event.set() 
            self.stop_recording_logic()

    def stop_recording_logic(self): # (Без изменений)
        print("[AppGUI] Вызвана stop_recording_logic")
        self.is_recording = False; self._update_gui_for_recording_state(False)
        self.prevent_minimize_thread = None; self.recording_thread = None

    def stop_recording(self): # (Без изменений)
        if not self.is_recording: return
        print("[AppGUI] Пользователь остановил запись.")
        self.status_label.config(text="Статус: Остановка записи...")
        self.stop_event.set()
        if self.prevent_minimize_thread and self.prevent_minimize_thread.is_alive(): self.prevent_minimize_thread.join(timeout=1)
        if self.recording_thread and self.recording_thread.is_alive(): self.recording_thread.join(timeout=10) 
        self.stop_recording_logic() 
        current_status = self.status_label.cget("text")
        if current_status == "Статус: Остановка записи..." or "Подготовка к записи" in current_status:
             self.status_label.config(text="Статус: Запись остановлена пользователем.")
        print("[AppGUI] Процесс остановки записи завершен.")

    def on_closing(self): # (Без изменений)
        if self.is_recording:
            if messagebox.askyesno("Запись активна", "Идет запись. Вы уверены, что хотите выйти? Запись будет остановлена."):
                self.stop_recording(); self.master.destroy()
        else: self.master.destroy()