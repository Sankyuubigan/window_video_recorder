import tkinter as tk
import time
from config import CONTROL_MASK

class RecordingTimer:
    def __init__(self, master, label_widget):
        self.master = master
        self.label_widget = label_widget
        self.recording_start_time = None
        self.timer_job_id = None
        self.is_running = False

    def start(self):
        if not self.is_running:
            self.recording_start_time = time.time()
            self.is_running = True
            self._update_display()
            self.label_widget.grid() # Показываем таймер

    def stop(self):
        if self.timer_job_id:
            self.master.after_cancel(self.timer_job_id)
            self.timer_job_id = None
        self.is_running = False
        self.label_widget.config(text="00:00:00")
        # self.label_widget.grid_remove() # Скрываем таймер при остановке (опционально)


    def reset(self):
        self.stop()
        self.label_widget.config(text="00:00:00")
        # self.label_widget.grid_remove() # Скрываем таймер при сбросе

    def _update_display(self):
        if self.is_running and self.recording_start_time is not None:
            elapsed_seconds = int(time.time() - self.recording_start_time)
            hours = elapsed_seconds // 3600
            minutes = (elapsed_seconds % 3600) // 60
            seconds = elapsed_seconds % 60
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.label_widget.config(text=time_str)
            self.timer_job_id = self.master.after(1000, self._update_display)
        else:
            # Если таймер был остановлен внешне, но _update_display вызван
            if self.timer_job_id:
                 self.master.after_cancel(self.timer_job_id)
                 self.timer_job_id = None


def setup_entry_clipboard_shortcuts(entry_widget):
    """
    Настраивает обработчики Ctrl+C и Ctrl+V для указанного виджета Entry.
    """
    entry_widget.bind("<KeyPress>", lambda event, widget=entry_widget: _handle_entry_keypress(event, widget))

def _handle_entry_keypress(event, widget):
    """
    Обрабатывает события KeyPress для Ctrl+C и Ctrl+V.
    event.char: Символ нажатой клавиши.
    event.state: Битовая маска состояния модификаторов (Shift, Control, Alt).
    """
    # Анализ атрибутов события
    # print(f"KeyPress: char='{event.char}' (repr: {repr(event.char)}), state={event.state}, keysym='{event.keysym}'")

    # Ctrl+V (Paste) - ASCII \x16 (SYN)
    if event.char == '\x16' and (event.state & CONTROL_MASK):
        if isinstance(widget, tk.Entry) or isinstance(widget, tk.Text) or isinstance(widget, tk.Spinbox):
            try:
                clipboard_content = widget.clipboard_get()
                if clipboard_content:
                    # Для Entry, удаляем выделенный текст перед вставкой, если есть
                    if isinstance(widget, tk.Entry) and widget.selection_present():
                        widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    widget.insert(tk.INSERT, clipboard_content)
                return "break"  # Предотвращаем дальнейшую обработку события
            except tk.TclError: # Буфер обмена пуст или содержит не текст
                pass # Ничего не делаем, если буфер пуст

    # Ctrl+C (Copy) - ASCII \x03 (ETX)
    elif event.char == '\x03' and (event.state & CONTROL_MASK):
        if isinstance(widget, tk.Entry) or isinstance(widget, tk.Text) or isinstance(widget, tk.Spinbox):
            if widget.selection_present():
                try:
                    selected_text = widget.selection_get()
                    if selected_text:
                        widget.clipboard_clear()
                        widget.clipboard_append(selected_text)
                    return "break" # Предотвращаем дальнейшую обработку события
                except tk.TclError: # Ошибка при работе с выделением
                     pass # Ничего не делаем

    # Стандартное поведение Tkinter для Ctrl+C/V/X/A обычно работает хорошо.
    # Этот обработчик нужен, если требуется специфическое поведение или анализ.
    # Для других комбинаций клавиш, позволим Tkinter обрабатывать их по умолчанию.
    return None


if __name__ == '__main__':
    root = tk.Tk()
    root.title("Тест GUI виджетов")
    root.geometry("400x300")

    # Тест Таймера
    timer_label_widget = tk.Label(root, text="00:00:00", font=("Arial", 16))
    timer_label_widget.pack(pady=10)
    # timer_label_widget.grid_remove() # Изначально скрыт

    recording_timer_instance = RecordingTimer(root, timer_label_widget)

    start_button = tk.Button(root, text="Старт Таймер", command=recording_timer_instance.start)
    start_button.pack()
    stop_button = tk.Button(root, text="Стоп Таймер", command=recording_timer_instance.stop)
    stop_button.pack()
    reset_button = tk.Button(root, text="Сброс Таймер", command=recording_timer_instance.reset)
    reset_button.pack()

    # Тест Ctrl+C / Ctrl+V
    tk.Label(root, text="\nПоле для теста Ctrl+C, Ctrl+V:").pack(pady=(10,0))
    test_entry = tk.Entry(root, width=50)
    test_entry.pack(pady=5)
    test_entry.insert(0, "Пример текста для копирования и вставки.")
    setup_entry_clipboard_shortcuts(test_entry)

    root.mainloop()