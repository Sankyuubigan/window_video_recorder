import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import datetime
import win32gui 
import time 
import sys  

from windows_utils import get_active_windows, prevent_minimize_loop, get_window_rect, prevent_resize_loop
from ffmpeg_utils import get_dshow_audio_devices
from config import DEFAULT_FRAMERATE, FFMPEG_PATH, NO_AUDIO_DEVICE_SELECTED 
from settings_manager import load_settings, save_settings
from log_viewer import LogViewerWindow, GLOBAL_LOG_BUFFER
from gui_widgets import RecordingTimer, setup_entry_clipboard_shortcuts
from ffmpeg_recorder import FFmpegRecorder 

class ScreenRecorderApp:
    def __init__(self, master):
        self.master = master
        self.log_viewer_instance = None 
        self.log_buffer = GLOBAL_LOG_BUFFER 
        self.log_message(f"Приложение запущено. Python {sys.version}")
        self.log_message(f"[AppGUI] Используется метод захвата GDI (PrintWindow) + FFmpeg-Python.")
        
        try: 
            final_icon_path = None; current_script_dir = os.path.dirname(os.path.abspath(__file__)); icon_name = "app_icon.ico"
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                base_path_frozen = sys._MEIPASS; icon_path_in_meipass = os.path.join(base_path_frozen, icon_name)
                if os.path.exists(icon_path_in_meipass): final_icon_path = icon_path_in_meipass
                else:
                    executable_dir = os.path.dirname(sys.executable)
                    icon_path_near_executable = os.path.join(executable_dir, icon_name)
                    if os.path.exists(icon_path_near_executable): final_icon_path = icon_path_near_executable
            else:
                project_root_from_core = os.path.dirname(current_script_dir) 
                icon_path_source_relative_to_core = os.path.join(project_root_from_core, icon_name) 
                if os.path.exists(icon_path_source_relative_to_core): final_icon_path = icon_path_source_relative_to_core
                else: 
                    icon_path_in_core_dir = os.path.join(current_script_dir, icon_name)
                    if os.path.exists(icon_path_in_core_dir): final_icon_path = icon_path_in_core_dir
            if final_icon_path and os.path.exists(final_icon_path):
                master.iconbitmap(default=final_icon_path); self.log_message(f"[AppGUI] Иконка установлена из: {final_icon_path}")
            else:
                paths_checked_log = []
                if getattr(sys, 'frozen', False):
                    paths_checked_log.append(f"MEIPASS: {os.path.join(getattr(sys, '_MEIPASS', 'N/A'), icon_name)}")
                    paths_checked_log.append(f"ExecutableDir: {os.path.join(os.path.dirname(sys.executable), icon_name)}")
                else:
                    paths_checked_log.append(f"../{icon_name}: {os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), icon_name)}")
                    paths_checked_log.append(f"./{icon_name}: {os.path.join(os.path.dirname(os.path.abspath(__file__)), icon_name)}")
                self.log_message(f"[AppGUI] Иконка '{icon_name}' не найдена. Проверенные пути: {'; '.join(paths_checked_log)}")
        except Exception as e: self.log_message(f"[AppGUI] Ошибка при установке иконки: {e}")
        
        master.title("Video Recorder v0.27 (Multi-Audio Test)") 
        master.geometry("700x500") # Немного увеличим, если нужно будет больше места для аудио
        
        self.is_recording = False
        self.prevent_minimize_thread = None; self.prevent_minimize_stop_event = None
        self.prevent_resize_thread = None; self.prevent_resize_stop_event = None
        self.initial_target_window_rect = None 

        self.recording_logic_thread = None; self.recorder_instance = None 
        self.selected_hwnd = None; self.window_titles_map = {}
        self.audio_devices = []; self.current_output_file = ""; self.recording_timer = None; self.settings = {} 
        
        self._setup_gui(); self._load_app_settings(); self.populate_window_list(); self.populate_audio_device_lists()
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _handle_critical_error_from_recorder(self, error_message):
        self.log_message(f"[AppGUI CRITICAL_CALLBACK] Получена ошибка от рекордера: {error_message}")
        if self.is_recording: 
            self.is_recording = False 
            if self.recording_timer and self.recording_timer.is_running: self.recording_timer.stop() 
            self._update_gui_for_recording_state(False) 
            self.status_label.config(text=f"Статус: КРИТ. ОШИБКА ЗАПИСИ ({error_message}).")
            if self.master and self.master.winfo_exists():
                messagebox.showerror("Критическая ошибка записи", 
                                     f"Запись была прервана из-за ошибки:\n{error_message}\n\nПожалуйста, проверьте логи.", 
                                     parent=self.master)
            self._stop_window_protection_threads() 
            self.recorder_instance = None 
            self.current_output_file = ""
        else:
            self.log_message("[AppGUI CRITICAL_CALLBACK] Запись уже не была активна.")

    def _start_window_protection_threads(self, hwnd):
        self._stop_window_protection_threads()
        self.prevent_minimize_stop_event = threading.Event()
        self.prevent_minimize_thread = threading.Thread(target=prevent_minimize_loop, args=(hwnd, self.prevent_minimize_stop_event, self.log_message), daemon=True)
        self.prevent_minimize_thread.start()
        self.initial_target_window_rect = get_window_rect(hwnd) 
        if self.initial_target_window_rect == (0,0,0,0) and win32gui.IsWindow(hwnd):
            self.log_message(f"[AppGUI] ВНИМАНИЕ: GetWindowRect для HWND {hwnd} вернул (0,0,0,0). Защита от изменения размера может работать некорректно.")
        self.prevent_resize_stop_event = threading.Event()
        self.prevent_resize_thread = threading.Thread(target=prevent_resize_loop,args=(hwnd, self.initial_target_window_rect, self.prevent_resize_stop_event, self.log_message),daemon=True)
        self.prevent_resize_thread.start()

    def _stop_window_protection_threads(self):
        if self.prevent_minimize_thread and self.prevent_minimize_thread.is_alive():
            if self.prevent_minimize_stop_event: self.prevent_minimize_stop_event.set()
        self.prevent_minimize_thread = None; self.prevent_minimize_stop_event = None
        if self.prevent_resize_thread and self.prevent_resize_thread.is_alive():
            if self.prevent_resize_stop_event: self.prevent_resize_stop_event.set()
        self.prevent_resize_thread = None; self.prevent_resize_stop_event = None
        self.initial_target_window_rect = None

    def log_message(self, message):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        fm = f"[{ts}] {message}"; print(fm) 
        if hasattr(self, 'log_viewer_instance') and self.log_viewer_instance and self.log_viewer_instance.log_window.winfo_exists(): 
            self.log_viewer_instance.add_log_message(fm)
        elif hasattr(self, 'log_buffer') and isinstance(self.log_buffer, list):
            self.log_buffer.append(fm)
            while len(self.log_buffer) > 2000: self.log_buffer.pop(0)

    def _setup_gui(self):
        r = 0
        tk.Label(self.master, text="Окно:").grid(row=r, column=0, padx=5, pady=5, sticky="w")
        self.window_combo = ttk.Combobox(self.master, width=75, state="readonly"); self.window_combo.grid(row=r, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_windows_button = tk.Button(self.master, text="Обновить", command=self.populate_window_list); self.refresh_windows_button.grid(row=r, column=2, padx=5, pady=5); r+=1
        tk.Label(self.master, text="Папка:").grid(row=r, column=0, padx=5, pady=5, sticky="w")
        self.output_dir_entry = tk.Entry(self.master, width=75); self.output_dir_entry.grid(row=r, column=1, padx=5, pady=5, sticky="ew"); setup_entry_clipboard_shortcuts(self.output_dir_entry)
        self.browse_button = tk.Button(self.master, text="Обзор...", command=self.select_output_directory); self.browse_button.grid(row=r, column=2, padx=5, pady=5); r+=1
        
        # Убираем надпись "будет использовано ПЕРВОЕ активное аудиоустройство"
        # audio_notice = "Запись звука: будет использовано ПЕРВОЕ активное аудиоустройство."; 
        # tk.Label(self.master, text=audio_notice, fg="blue").grid(row=r, column=0, columnspan=3, padx=5, pady=2, sticky="w"); r+=1
        
        tk.Label(self.master, text="Микрофон:").grid(row=r, column=0, padx=5, pady=5, sticky="w")
        self.mic_device_combo = ttk.Combobox(self.master, width=75, state="readonly"); self.mic_device_combo.grid(row=r, column=1, padx=5, pady=5, sticky="ew"); r+=1
        tk.Label(self.master, text="Звук Sys1:").grid(row=r, column=0, padx=5, pady=5, sticky="w")
        self.system_audio_device_combo1 = ttk.Combobox(self.master, width=75, state="readonly"); self.system_audio_device_combo1.grid(row=r, column=1, padx=5, pady=5, sticky="ew"); r+=1
        tk.Label(self.master, text="Звук Sys2:").grid(row=r, column=0, padx=5, pady=5, sticky="w")
        self.system_audio_device_combo2 = ttk.Combobox(self.master, width=75, state="readonly"); self.system_audio_device_combo2.grid(row=r, column=1, padx=5, pady=5, sticky="ew")
        self.refresh_audio_button = tk.Button(self.master, text="Обновить Аудио", command=self.populate_audio_device_lists); self.refresh_audio_button.grid(row=r-2, column=2, rowspan=3, padx=5, pady=5, sticky="ns"); r+=1
        
        self.record_button = tk.Button(self.master, text="Начать запись", command=self.toggle_recording, bg="lightgreen", height=2); self.record_button.grid(row=r, column=0, columnspan=2, padx=5, pady=15, sticky="ew")
        self.timer_label = tk.Label(self.master, text="00:00:00", font=("Arial",16), relief=tk.SUNKEN, anchor="center"); 
        self.timer_label.grid(row=r, column=2, padx=5, pady=15, sticky="ewns")
        self.recording_timer = RecordingTimer(self.master, self.timer_label)
        r+=1
        s_frame = ttk.Frame(self.master); s_frame.grid(row=r,column=0,columnspan=3,sticky="ew",padx=5,pady=5); s_frame.columnconfigure(0,weight=1)
        self.status_label = tk.Label(s_frame, text="Статус: Ожидание", relief=tk.SUNKEN, anchor="w"); self.status_label.grid(row=0,column=0,sticky="ew",padx=(0,5))
        self.show_logs_button = tk.Button(s_frame, text="Логи", command=self.show_log_window); self.show_logs_button.grid(row=0,column=1,sticky="e",padx=(5,0)); self.master.grid_columnconfigure(1,weight=1)

    def _load_app_settings(self):
        self.log_message("[AppGUI] Загрузка настроек...")
        self.settings = load_settings(logger_func=self.log_message)
        if self.settings: 
            od = self.settings.get("output_directory")
            if od and os.path.isdir(od): self.output_dir_entry.delete(0, tk.END); self.output_dir_entry.insert(0, od)
            elif od: self.log_message(f"[AppGUI] Папка '{od}' из настроек не найдена.")
        else:
            self.log_message("[AppGUI] Файл настроек не найден/пуст."); 
            dvp = os.path.join(os.path.expanduser("~"),"Videos"); self.output_dir_entry.insert(0, dvp if os.path.isdir(dvp) else os.path.expanduser("~"))
        self.log_message("[AppGUI] Настройки применены (если были).")

    def _save_app_settings(self):
        self.log_message("[AppGUI] Сохранение настроек...")
        settings_to_save = { 
            "output_directory": self.output_dir_entry.get(), 
            "selected_window_title": self.window_combo.get(), 
            "mic_device": self.mic_device_combo.get(), 
            "system_audio_1": self.system_audio_device_combo1.get(), 
            "system_audio_2": self.system_audio_device_combo2.get(), 
        }
        save_settings(settings_to_save, self.log_message)

    def toggle_recording(self): 
        if self.is_recording: self.stop_recording()
        else: self.start_recording_async()

    def populate_window_list(self):
        # ... (без изменений)
        self.window_combo['values']=[]; self.window_titles_map=get_active_windows(); st=sorted(self.window_titles_map.keys()); self.window_combo['values']=st
        swt=self.settings.get("selected_window_title") if self.settings else None
        if swt and swt in st: self.window_combo.set(swt)
        elif st: self.window_combo.current(0)
        if not self.is_recording: self.status_label.config(text="Статус: Окна обновлены."); self.log_message("[AppGUI] Окна обновлены.")


    def populate_audio_device_lists(self):
        # ... (без изменений)
        self.log_message("[AppGUI] Обновление аудио..."); 
        if not self.is_recording: self.status_label.config(text="Статус: Обновление аудио...")
        self.master.update_idletasks(); rad=get_dshow_audio_devices(self.log_message); self.log_message(f"[AppGUI] Найдено аудио: {rad}")
        self.audio_devices=[NO_AUDIO_DEVICE_SELECTED]+rad
        pm,ps1,ps2 = self.mic_device_combo.get(), self.system_audio_device_combo1.get(), self.system_audio_device_combo2.get()
        if self.settings:
            pm = pm or self.settings.get("mic_device", NO_AUDIO_DEVICE_SELECTED)
            ps1 = ps1 or self.settings.get("system_audio_1", NO_AUDIO_DEVICE_SELECTED)
            ps2 = ps2 or self.settings.get("system_audio_2", NO_AUDIO_DEVICE_SELECTED)
        self.mic_device_combo['values']=self.system_audio_device_combo1['values']=self.system_audio_device_combo2['values']=self.audio_devices
        def set_combo(combo, prev_val, keywords, exclude_vals=None):
            if exclude_vals is None: exclude_vals = []
            val_to_set = None
            if prev_val and prev_val in self.audio_devices: val_to_set = prev_val
            current_exclude_vals = [ev for ev in exclude_vals if ev != NO_AUDIO_DEVICE_SELECTED] if val_to_set == NO_AUDIO_DEVICE_SELECTED else exclude_vals
            if val_to_set and val_to_set not in current_exclude_vals : combo.set(val_to_set)
            elif rad: 
                found_by_keyword = False
                for i,d_name in enumerate(rad): 
                    if d_name in current_exclude_vals: continue
                    if any(kw in d_name.lower() for kw in keywords): combo.current(i+1); found_by_keyword=True; break
                if not found_by_keyword and self.audio_devices: combo.current(0) 
                elif not self.audio_devices: combo.set('') 
            elif self.audio_devices: combo.current(0) 
            else: combo.set('')
        set_combo(self.mic_device_combo, pm, ["микрофон", "microphone", "mic"])
        set_combo(self.system_audio_device_combo1, ps1, ["стерео микшер", "stereo mix", "what u hear", "смеситель"], [self.mic_device_combo.get()])
        set_combo(self.system_audio_device_combo2, ps2, ["line out", "speakers"], [self.mic_device_combo.get(), self.system_audio_device_combo1.get()])
        if not self.is_recording: self.status_label.config(text="Статус: Аудио обновлены."); self.log_message("[AppGUI] Аудио обновлены.")
        if not rad and not self.is_recording: self.status_label.config(text="Статус: Аудио не найдены."); messagebox.showwarning("Аудио", "Аудиоустройства DirectShow не найдены.", parent=self.master)


    def select_output_directory(self):
        # ... (без изменений)
        initial_dir_val = self.output_dir_entry.get()
        if not initial_dir_val or not os.path.isdir(initial_dir_val): initial_dir_val = os.path.expanduser("~") 
        dp=filedialog.askdirectory(initialdir=initial_dir_val, parent=self.master)
        if dp: self.output_dir_entry.delete(0,tk.END); self.output_dir_entry.insert(0,dp)

    def _perform_recording_logic(self):
        # ... (без изменений)
        success_start, error_msg_start = self.recorder_instance.start() 
        if success_start:
            self.log_message("[AppGUI] FFmpegRecorder успешно запущен.")
            self.is_recording = True 
            self.master.after(0, self._update_gui_for_recording_state, True) 
            self.master.after(0, self.recording_timer.start) 
            self.master.after(0, self._update_status_recording_in_progress)
        else: 
            self.log_message(f"[AppGUI] Ошибка запуска FFmpegRecorder: {error_msg_start}")
            self.is_recording = False 
            self.master.after(0, self._handle_recording_result, False, error_msg_start)
            self.recorder_instance = None 

    def _update_status_recording_in_progress(self):
        # ... (без изменений)
        if self.is_recording: 
            if self.current_output_file: self.status_label.config(text=f"Статус: Запись в {os.path.basename(self.current_output_file)}...")
            else: self.status_label.config(text="Статус: Идет запись...")

    def _handle_recording_result(self, success, message):
        # ... (без изменений)
        self.log_message(f"[AppGUI] Результат записи: Успех={success}, Сообщение='{message}'")
        final_status_message = ""
        if not success: 
            self.is_recording = False 
            final_status_message = f"Статус: Ошибка ({message})."
            if self.master and self.master.winfo_exists():
                messagebox.showerror("Ошибка записи/остановки", f"Произошла ошибка:\n{message}\n\nСм. логи.", parent=self.master)
        else: 
            if not self.is_recording: 
                final_status_message = f"Статус: Запись успешно остановлена. {message if message else ''}"
        if final_status_message: self.status_label.config(text=final_status_message)
        if not self.is_recording:
            self._update_gui_for_recording_state(False)
            self.recording_timer.stop() 
            if not success: self.recorder_instance = None; self.current_output_file = ""


    def start_recording_async(self):
        if self.is_recording: self.log_message("[AppGUI] Попытка начать запись, когда уже идет запись."); return
        
        selected_window_title_str = self.window_combo.get(); output_dir_str = self.output_dir_entry.get()
        
        # Собираем список активных аудиоустройств
        mic_dev = self.mic_device_combo.get()
        sys_audio1_dev = self.system_audio_device_combo1.get()
        sys_audio2_dev = self.system_audio_device_combo2.get()
        
        selected_audio_devices_list = []
        if mic_dev != NO_AUDIO_DEVICE_SELECTED: selected_audio_devices_list.append(mic_dev)
        if sys_audio1_dev != NO_AUDIO_DEVICE_SELECTED: selected_audio_devices_list.append(sys_audio1_dev)
        if sys_audio2_dev != NO_AUDIO_DEVICE_SELECTED: selected_audio_devices_list.append(sys_audio2_dev)
        
        # Удаляем дубликаты, сохраняя порядок (важно, если пользователь выбрал одно и то же устройство в разных слотах)
        # Это не самый эффективный способ, но для 3 элементов подойдет.
        unique_selected_audio_devices = []
        for item in selected_audio_devices_list:
            if item not in unique_selected_audio_devices:
                unique_selected_audio_devices.append(item)
        selected_audio_devices_list = unique_selected_audio_devices

        if not selected_window_title_str: messagebox.showerror("Ошибка","Выберите окно.",parent=self.master); return
        if not output_dir_str or not os.path.isdir(output_dir_str): messagebox.showerror("Ошибка",f"Папка '{output_dir_str}' некорректна.",parent=self.master); return
        
        self.selected_hwnd = self.window_titles_map.get(selected_window_title_str)
        if not self.selected_hwnd or not win32gui.IsWindow(self.selected_hwnd): 
            messagebox.showerror("Ошибка",f"Окно '{selected_window_title_str}' больше не существует или невалидно.", parent=self.master)
            self.populate_window_list(); return
        
        if not selected_audio_devices_list: # Если список пуст
            if not messagebox.askyesno("Предупреждение","Аудиоустройства не выбраны. Продолжить запись без звука?", parent=self.master): return
            self.log_message("[AppGUI] Запись будет без звука (пользователь подтвердил).")
        else: 
            self.log_message(f"[AppGUI] Выбранные аудиоустройства для записи: {selected_audio_devices_list}")
        
        self.current_output_file = os.path.join(output_dir_str, f"record_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.mp4")
        self.log_message(f"[AppGUI] Запуск GDI Recorder для '{selected_window_title_str}' (HWND: {self.selected_hwnd}) -> '{self.current_output_file}'")
        
        self.recorder_instance = FFmpegRecorder(
            hwnd=self.selected_hwnd, 
            output_file=self.current_output_file, 
            audio_device_names_list=selected_audio_devices_list, # Передаем список
            framerate=DEFAULT_FRAMERATE, 
            logger_func=self.log_message,
            on_critical_error_callback=lambda err_msg: self.master.after(0, self._handle_critical_error_from_recorder, err_msg)
        )
        self.recording_timer.set_source(
            get_frames_callback=lambda: self.recorder_instance.get_frames_written() if self.recorder_instance else 0,
            target_fps=self.recorder_instance.framerate 
        )
        self.status_label.config(text="Статус: Запуск записи..."); 
        self._update_gui_for_recording_state(True) 
        self.recording_logic_thread = threading.Thread(target=self._perform_recording_logic, daemon=True); self.recording_logic_thread.start()
        self._save_app_settings()
        self._start_window_protection_threads(self.selected_hwnd)

    def _update_gui_for_recording_state(self, is_starting_or_is_recording): 
        # ... (без изменений)
        bt, bb, widget_state_disabled, widget_state_readonly, status_text_default = \
            ("Остановить запись", "salmon", "disabled", "disabled", "Статус: Ожидание") \
            if is_starting_or_is_recording else \
            ("Начать запись", "lightgreen", "normal", "readonly", "Статус: Ожидание")
        self.record_button.config(text=bt, bg=bb)
        entry_state = "disabled" if is_starting_or_is_recording else "normal"
        button_state = "disabled" if is_starting_or_is_recording else "normal"
        self.output_dir_entry.config(state=entry_state)
        self.browse_button.config(state=button_state)
        self.refresh_windows_button.config(state=button_state)
        self.refresh_audio_button.config(state=button_state)
        combo_state = "disabled" if is_starting_or_is_recording else "readonly"
        self.window_combo.config(state=combo_state)
        self.mic_device_combo.config(state=combo_state)
        self.system_audio_device_combo1.config(state=combo_state)
        self.system_audio_device_combo2.config(state=combo_state)
        if not is_starting_or_is_recording: 
            current_status_text = self.status_label.cget("text")
            if "Запись" not in current_status_text and "Ошибка" not in current_status_text and "остановлена" not in current_status_text and "КРИТ." not in current_status_text:
                self.status_label.config(text=status_text_default)


    def stop_recording(self):
        # ... (без изменений)
        if not self.is_recording or not self.recorder_instance:
            self.log_message("[AppGUI] stop_recording: запись не активна или нет экземпляра рекордера.")
            if self.is_recording: self.is_recording = False 
            self._update_gui_for_recording_state(False)
            self.recording_timer.reset() 
            self.status_label.config(text="Статус: Запись не была активна.")
            return
        self.log_message("[AppGUI] Пользователь остановил запись.")
        self.status_label.config(text="Статус: Остановка записи..."); self.master.update_idletasks()
        self._stop_window_protection_threads() 
        error_msg_stop = self.recorder_instance.stop() 
        self.is_recording = False 
        if error_msg_stop: 
            self.log_message(f"[AppGUI] Ошибка при остановке FFmpegRecorder: {error_msg_stop}")
            self._handle_recording_result(False, f"Ошибка остановки: {error_msg_stop}")
        else: 
            self.log_message("[AppGUI] FFmpegRecorder успешно остановлен.")
            self._handle_recording_result(True, "Запись успешно остановлена.") 
        self.recorder_instance = None 
        self.current_output_file = "" 


    def on_closing(self): 
        # ... (без изменений)
        close_app = True
        if self.is_recording:
            if not messagebox.askyesno("Запись активна","Выйти? (Запись остановится и будет сохранена)", parent=self.master): 
                close_app = False
        if close_app:
            self.log_message("[AppGUI] Закрытие приложения...")
            if self.is_recording and self.recorder_instance: 
                self.log_message("[AppGUI] Остановка записи при закрытии...")
                self.stop_recording() 
            self._stop_window_protection_threads() 
            if self.recording_logic_thread and self.recording_logic_thread.is_alive():
                self.log_message("[AppGUI] Ожидание завершения потока логики записи...")
                self.recording_logic_thread.join(timeout=10) 
                if self.recording_logic_thread.is_alive():
                     self.log_message("[AppGUI] Поток логики записи не завершился.")
            self._save_app_settings()
            if self.master and self.master.winfo_exists(): self.master.destroy()

    def show_log_window(self):
        # ... (без изменений)
        if not self.log_viewer_instance or not self.log_viewer_instance.log_window.winfo_exists():
            parent_for_log = self.master if self.master and self.master.winfo_exists() else None
            if not parent_for_log: return 
            self.log_viewer_instance=LogViewerWindow(parent_for_log,"Логи VideoConfRecorder")
            if hasattr(self, 'log_buffer') and self.log_buffer:
                for m in list(self.log_buffer): 
                    if self.log_viewer_instance and self.log_viewer_instance.log_window.winfo_exists(): 
                        self.log_viewer_instance.add_log_message(m)
        if self.log_viewer_instance and self.log_viewer_instance.log_window.winfo_exists(): self.log_viewer_instance.show()
