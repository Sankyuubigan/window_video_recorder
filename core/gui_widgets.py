import tkinter as tk
import time
from config import CONTROL_MASK

class RecordingTimer:
    def __init__(self, master, label_widget):
        self.master = master
        self.label_widget = label_widget
        self.timer_job_id = None
        self.is_running = False
        self.get_frames_callback = None 
        self.target_fps = 25 
        self.start_time_display = None # Для расчета времени по системным часам, если коллбэк недоступен

    def set_source(self, get_frames_callback, target_fps):
        self.get_frames_callback = get_frames_callback
        self.target_fps = target_fps if target_fps > 0 else 25
        self.label_widget.config(text="00:00:00") 
        self.start_time_display = None # Сбрасываем при установке нового источника

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.label_widget.config(text="00:00:00") # Сброс на 00:00:00 при старте
            self.start_time_display = time.monotonic() # Запоминаем время начала для альтернативного расчета
            self._update_display()
            if hasattr(self.label_widget, 'winfo_ismapped') and not self.label_widget.winfo_ismapped(): 
                self.label_widget.grid() 

    def stop(self):
        if self.timer_job_id:
            if self.master and hasattr(self.master, 'after_cancel') and self.master.winfo_exists():
                self.master.after_cancel(self.timer_job_id)
            self.timer_job_id = None
        self.is_running = False
        self.start_time_display = None # Сбрасываем время начала

    def reset(self):
        self.stop() 
        self.label_widget.config(text="00:00:00")
        self.start_time_display = None


    def _update_display(self):
        if self.is_running:
            current_time_str = "00:00:00" 
            elapsed_seconds_int = 0

            if self.get_frames_callback:
                frames_count = None
                # Добавляем проверку существования master перед вызовом winfo_exists
                # и проверку, что get_frames_callback вообще существует
                master_exists = self.master and hasattr(self.master, 'winfo_exists') and self.master.winfo_exists()
                
                if master_exists and callable(self.get_frames_callback):
                    try:
                        frames_count = self.get_frames_callback()
                    except Exception as e_cb_timer:
                        # Логируем ошибку коллбэка, если есть логгер или print
                        log_func = getattr(self.master, 'log_message', print) if hasattr(self.master, 'log_message') else print
                        log_func(f"[RecordingTimer] Ошибка в get_frames_callback: {e_cb_timer}")
                        frames_count = None # Сбрасываем, чтобы использовать альтернативный метод

                if frames_count is not None and frames_count >= 0:
                    effective_fps = self.target_fps if self.target_fps > 0 else 1.0
                    elapsed_seconds_float = frames_count / effective_fps
                    elapsed_seconds_int = int(elapsed_seconds_float)
                # Если frames_count None (из-за ошибки коллбэка или он не задан),
                # и start_time_display было установлено, считаем по системному времени.
                elif self.start_time_display is not None: 
                    elapsed_seconds_int = int(time.monotonic() - self.start_time_display)
            
            elif self.start_time_display is not None: # Если коллбэка нет, но есть время старта
                 elapsed_seconds_int = int(time.monotonic() - self.start_time_display)

            hours = elapsed_seconds_int // 3600
            minutes = (elapsed_seconds_int % 3600) // 60
            seconds = elapsed_seconds_int % 60
            current_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Обновляем только если виджет и master еще существуют
            if self.master and hasattr(self.master, 'winfo_exists') and self.master.winfo_exists() and \
               hasattr(self.label_widget, 'winfo_exists') and self.label_widget.winfo_exists():
                self.label_widget.config(text=current_time_str)
                self.timer_job_id = self.master.after(500, self._update_display) 
        else: 
            if self.timer_job_id:
                if self.master and hasattr(self.master, 'after_cancel') and self.master.winfo_exists():
                    self.master.after_cancel(self.timer_job_id)
                self.timer_job_id = None


def setup_entry_clipboard_shortcuts(entry_widget):
    # Проверяем, что entry_widget это действительно виджет (имеет метод bind)
    if not (hasattr(entry_widget, 'bind') and callable(entry_widget.bind)):
        print(f"[GUI Widgets] Ошибка: setup_entry_clipboard_shortcuts получил невалидный виджет: {type(entry_widget)}")
        return

    entry_widget.bind("<KeyPress>", lambda event, widget=entry_widget: _handle_entry_keypress(event, widget))

def _handle_entry_keypress(event, widget):
    # Добавляем проверки на существование методов перед их вызовом
    if event.char == '\x16' and (event.state & CONTROL_MASK): # Ctrl+V
        if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox)) and \
           hasattr(widget, 'clipboard_get') and callable(widget.clipboard_get) and \
           hasattr(widget, 'insert') and callable(widget.insert):
            try:
                clipboard_content = widget.clipboard_get()
                if clipboard_content: # Проверяем, что есть что вставлять
                    if isinstance(widget, tk.Entry) and hasattr(widget, 'selection_present') and widget.selection_present():
                        if hasattr(widget, 'delete') and callable(widget.delete) and hasattr(tk, 'SEL_FIRST') and hasattr(tk, 'SEL_LAST'):
                            widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    widget.insert(tk.INSERT, clipboard_content)
                return "break"  
            except tk.TclError: pass # Ошибки Tcl (например, пустой буфер) игнорируем

    elif event.char == '\x03' and (event.state & CONTROL_MASK): # Ctrl+C
        if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox)) and \
           hasattr(widget, 'selection_present') and callable(widget.selection_present) and \
           widget.selection_present(): # Копируем только если есть выделение
            if hasattr(widget, 'selection_get') and callable(widget.selection_get) and \
               hasattr(widget, 'clipboard_clear') and callable(widget.clipboard_clear) and \
               hasattr(widget, 'clipboard_append') and callable(widget.clipboard_append):
                try:
                    selected_text = widget.selection_get()
                    if selected_text: # Проверяем, что есть что копировать
                        widget.clipboard_clear(); widget.clipboard_append(selected_text)
                    return "break" 
                except tk.TclError: pass 
    return None # Возвращаем None, если событие не обработано


if __name__ == '__main__':
    root = tk.Tk()
    root.title("Тест GUI виджетов")
    root.geometry("400x300")

    timer_label_widget = tk.Label(root, text="00:00:00", font=("Arial", 16))
    timer_label_widget.pack(pady=10)

    recording_timer_instance = RecordingTimer(root, timer_label_widget)

    mock_frames_data = {"count": 0, "fps": 25, "error_after_n_calls": -1, "calls": 0} # -1 для отсутствия ошибки
    
    def get_mock_frames_with_error():
        mock_frames_data["calls"] += 1
        if mock_frames_data["error_after_n_calls"] > 0 and \
           mock_frames_data["calls"] > mock_frames_data["error_after_n_calls"]:
            raise ValueError("Тестовая ошибка в get_frames_callback")
        
        # Имитируем получение кадров ~ каждые 0.5 сек реального времени
        # Вместо инкремента на target_fps / 2, будем использовать реальное прошедшее время
        # Это не используется напрямую таймером, но полезно для симуляции
        if recording_timer_instance.start_time_display:
             mock_frames_data["count"] = int((time.monotonic() - recording_timer_instance.start_time_display) * mock_frames_data["fps"])
        return mock_frames_data["count"]


    recording_timer_instance.set_source(get_mock_frames_with_error, mock_frames_data["fps"])

    def start_timer_action():
        mock_frames_data["count"] = 0
        mock_frames_data["calls"] = 0
        recording_timer_instance.start()

    start_button = tk.Button(root, text="Старт Таймер", command=start_timer_action)
    start_button.pack()
    stop_button = tk.Button(root, text="Стоп Таймер", command=lambda: (recording_timer_instance.stop(), print(f"Таймер остановлен. Последнее значение: {timer_label_widget.cget('text')}")))
    stop_button.pack()
    
    def reset_timer_action():
        mock_frames_data.update({"count":0, "calls": 0})
        recording_timer_instance.reset()
        
    reset_button = tk.Button(root, text="Сброс Таймер", command=reset_timer_action)
    reset_button.pack()

    # Кнопка для имитации ошибки в коллбэке таймера
    def simulate_callback_error():
        mock_frames_data["error_after_n_calls"] = mock_frames_data["calls"] + 2 # Ошибка через 2 вызова
        print("Коллбэк таймера выдаст ошибку через ~1 секунду")

    error_button = tk.Button(root, text="Ошибка в таймере (через 1с)", command=simulate_callback_error)
    error_button.pack(pady=5)


    tk.Label(root, text="\nПоле для теста Ctrl+C, Ctrl+V:").pack(pady=(10,0))
    test_entry = tk.Entry(root, width=50)
    test_entry.pack(pady=5)
    test_entry.insert(0, "Пример текста для копирования и вставки.")
    setup_entry_clipboard_shortcuts(test_entry)

    root.mainloop()