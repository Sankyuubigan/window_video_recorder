import tkinter as tk
from tkinter import scrolledtext, messagebox

class LogViewerWindow:
    def __init__(self, parent, title="Окно логов"):
        self.parent = parent
        self.log_window = tk.Toplevel(parent)
        self.log_window.title(title)
        self.log_window.geometry("800x600")
        self.log_window.transient(parent) # Делает окно модальным по отношению к родителю

        self.log_text_widget = scrolledtext.ScrolledText(self.log_window, wrap=tk.WORD, state='normal', height=25, width=100)
        self.log_text_widget.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        # Позволяем выделение и копирование, но не редактирование пользователем напрямую
        self.log_text_widget.configure(state='normal') # Должен быть normal для вставки
                                                     # Можно сделать 'disabled' после вставки, чтобы запретить ручной ввод
                                                     # но это также запретит копирование из виджета стандартными средствами.
                                                     # ScrolledText по умолчанию позволяет копирование.

        button_frame = tk.Frame(self.log_window)
        button_frame.pack(pady=5)

        self.copy_all_button = tk.Button(button_frame, text="Копировать всё", command=self.copy_all_logs)
        self.copy_all_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(button_frame, text="Очистить лог", command=self.clear_logs)
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
        self.close_button = tk.Button(button_frame, text="Закрыть", command=self.log_window.destroy)
        self.close_button.pack(side=tk.LEFT, padx=5)

        self.log_window.protocol("WM_DELETE_WINDOW", self.on_close) # Обработка закрытия окна через "крестик"

    def on_close(self):
        # Можно добавить логику перед закрытием, если нужно
        self.log_window.destroy()

    def add_log_message(self, message):
        if self.log_window.winfo_exists(): # Проверяем, существует ли еще окно
            current_state = self.log_text_widget.cget('state')
            self.log_text_widget.config(state='normal')
            self.log_text_widget.insert(tk.END, message + "\n")
            self.log_text_widget.see(tk.END) # Автопрокрутка к последнему сообщению
            self.log_text_widget.config(state=current_state) # Возвращаем исходное состояние (если оно было 'disabled')
                                                              # Для ScrolledText лучше оставить 'normal' для копирования

    def copy_all_logs(self):
        if self.log_window.winfo_exists():
            try:
                log_content = self.log_text_widget.get(1.0, tk.END)
                self.log_window.clipboard_clear()
                self.log_window.clipboard_append(log_content)
                messagebox.showinfo("Копирование", "Содержимое лога скопировано в буфер обмена.", parent=self.log_window)
            except tk.TclError:
                messagebox.showerror("Ошибка", "Не удалось скопировать текст. Возможно, буфер обмена недоступен.", parent=self.log_window)


    def clear_logs(self):
        if self.log_window.winfo_exists():
            current_state = self.log_text_widget.cget('state')
            self.log_text_widget.config(state='normal')
            self.log_text_widget.delete(1.0, tk.END)
            self.log_text_widget.config(state=current_state)

    def show(self):
        self.log_window.deiconify()
        self.log_window.lift()
        self.log_window.focus_set()

# Глобальный буфер для сообщений лога, если окно еще не создано или закрыто
# Этим будет управлять основной класс приложения
GLOBAL_LOG_BUFFER = []

# Глобальный обработчик логов, который можно переопределить в основном приложении
def central_logger(message, app_instance=None):
    """
    Центральная функция для логирования.
    Печатает в консоль и добавляет в буфер/окно логов, если app_instance предоставлен.
    """
    print(message) # Всегда выводим в консоль
    if app_instance is not None:
        app_instance.add_message_to_log_system(message)


if __name__ == '__main__':
    root = tk.Tk()
    root.title("Тестовое родительское окно")
    root.geometry("300x200")

    # Имитация основного приложения для логирования
    class MockApp:
        def __init__(self, master_root):
            self.log_viewer_instance = None
            self.log_buffer = [] # Буфер для сообщений, если окно логов закрыто/не открыто
            self.master = master_root

        def add_message_to_log_system(self, message):
            if self.log_viewer_instance and self.log_viewer_instance.log_window.winfo_exists():
                self.log_viewer_instance.add_log_message(message)
            else:
                self.log_buffer.append(message)
                if len(self.log_buffer) > 1000: # Ограничение размера буфера
                    self.log_buffer.pop(0)
        
        def show_log_window_action(self):
            if not self.log_viewer_instance or not self.log_viewer_instance.log_window.winfo_exists():
                self.log_viewer_instance = LogViewerWindow(self.master)
                # Загружаем сообщения из буфера в новое окно
                for msg in self.log_buffer:
                    self.log_viewer_instance.add_log_message(msg)
                # self.log_buffer.clear() # Опционально: очистить буфер после отображения
            self.log_viewer_instance.show()

    mock_app = MockApp(root)

    # Используем central_logger с передачей mock_app
    central_logger("Это тестовое сообщение лога 1.", mock_app)
    central_logger("Это тестовое сообщение лога 2, которое чуть длиннее.", mock_app)

    show_logs_button = tk.Button(root, text="Показать логи", command=mock_app.show_log_window_action)
    show_logs_button.pack(pady=20)
    
    add_log_button = tk.Button(root, text="Добавить лог", command=lambda: central_logger(f"Новое сообщение: {tk.StringVar().set(str(len(mock_app.log_buffer)))}", mock_app))
    add_log_button.pack(pady=5)

    root.mainloop()
