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

    def set_source(self, get_frames_callback, target_fps):
        self.get_frames_callback = get_frames_callback
        self.target_fps = target_fps if target_fps > 0 else 25
        self.label_widget.config(text="00:00:00") # Сброс при установке нового источника

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.label_widget.config(text="00:00:00") 
            self._update_display()
            if not self.label_widget.winfo_ismapped(): # Показываем, если скрыт
                self.label_widget.grid() 

    def stop(self):
        if self.timer_job_id:
            self.master.after_cancel(self.timer_job_id)
            self.timer_job_id = None
        self.is_running = False
        # Оставляем последнее значение времени на дисплее при остановке

    def reset(self):
        self.stop() 
        self.label_widget.config(text="00:00:00")
        # Если таймер должен быть скрыт при сбросе:
        # if self.label_widget.winfo_ismapped():
        # self.label_widget.grid_remove()

    def _update_display(self):
        if self.is_running:
            current_time_str = "00:00:00" # Значение по умолчанию
            if self.get_frames_callback:
                try:
                    frames_count = self.get_frames_callback()
                    # self.master.winfo_exists() проверяет, что главное окно еще есть
                    if self.master.winfo_exists() and frames_count is not None and frames_count >= 0:
                        # Рассчитываем время на основе количества кадров и FPS
                        # Если target_fps 0 или меньше, используем 1 чтобы избежать деления на ноль
                        effective_fps = self.target_fps if self.target_fps > 0 else 1.0
                        elapsed_seconds_float = frames_count / effective_fps
                        elapsed_seconds_int = int(elapsed_seconds_float)
                        
                        hours = elapsed_seconds_int // 3600
                        minutes = (elapsed_seconds_int % 3600) // 60
                        seconds = elapsed_seconds_int % 60
                        current_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except Exception as e: 
                    # Если колбэк не доступен или ошибка, используем предыдущее значение или 00:00:00
                    # print(f"Timer update error: {e}") # Для отладки
                    pass 
            
            if self.master.winfo_exists(): # Обновляем только если виджет еще существует
                self.label_widget.config(text=current_time_str)
                self.timer_job_id = self.master.after(500, self._update_display) # Обновляем дважды в секунду для большей плавности
        else: # Если is_running стал False, но _update_display еще был запланирован
            if self.timer_job_id:
                self.master.after_cancel(self.timer_job_id)
                self.timer_job_id = None


def setup_entry_clipboard_shortcuts(entry_widget):
    entry_widget.bind("<KeyPress>", lambda event, widget=entry_widget: _handle_entry_keypress(event, widget))

def _handle_entry_keypress(event, widget):
    if event.char == '\x16' and (event.state & CONTROL_MASK): # Ctrl+V
        if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox)):
            try:
                clipboard_content = widget.clipboard_get()
                if clipboard_content:
                    if isinstance(widget, tk.Entry) and widget.selection_present():
                        widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    widget.insert(tk.INSERT, clipboard_content)
                return "break"  
            except tk.TclError: pass 

    elif event.char == '\x03' and (event.state & CONTROL_MASK): # Ctrl+C
        if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox)):
            if widget.selection_present():
                try:
                    selected_text = widget.selection_get()
                    if selected_text:
                        widget.clipboard_clear(); widget.clipboard_append(selected_text)
                    return "break" 
                except tk.TclError: pass 
    return None


if __name__ == '__main__':
    root = tk.Tk()
    root.title("Тест GUI виджетов")
    root.geometry("400x300")

    timer_label_widget = tk.Label(root, text="00:00:00", font=("Arial", 16))
    timer_label_widget.pack(pady=10)

    recording_timer_instance = RecordingTimer(root, timer_label_widget)

    # Имитация источника кадров
    mock_frames_data = {"count": 0, "fps": 25}
    def get_mock_frames():
        mock_frames_data["count"] += mock_frames_data["fps"] // 2 # Имитируем ~0.5 сек кадров
        return mock_frames_data["count"]

    recording_timer_instance.set_source(get_mock_frames, mock_frames_data["fps"])

    start_button = tk.Button(root, text="Старт Таймер", command=recording_timer_instance.start)
    start_button.pack()
    stop_button = tk.Button(root, text="Стоп Таймер", command=lambda: (recording_timer_instance.stop(), print(f"Таймер остановлен. Последнее значение: {timer_label_widget.cget('text')}")))
    stop_button.pack()
    reset_button = tk.Button(root, text="Сброс Таймер", command=lambda: (mock_frames_data.update({"count":0}), recording_timer_instance.reset())) # Сбрасываем и счетчик кадров
    reset_button.pack()

    tk.Label(root, text="\nПоле для теста Ctrl+C, Ctrl+V:").pack(pady=(10,0))
    test_entry = tk.Entry(root, width=50)
    test_entry.pack(pady=5)
    test_entry.insert(0, "Пример текста для копирования и вставки.")
    setup_entry_clipboard_shortcuts(test_entry)

    root.mainloop()