from PIL import Image, ImageTk
import tkinter as tk
from sort_profanity_windows_gui import *
from header import *
import queue

class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        self.log_queue.put(self.format(record))
# --- GUI App class (unchanged except for using the above logic) ---
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Serato Crate Profanity Filter - DJ. Gadget")
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
        self.queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(self.queue_handler)
        logging.getLogger().setLevel(logging.INFO)

        # --- Banner Row: Instructions (left) and Logo (right) ---
        banner_frame = tk.Frame(root, height=180, bg="white")
        banner_frame.pack_propagate(False)
        banner_frame.pack(fill=tk.X, padx=0, pady=(0, 0))

        instructions = (
            "Instructions:\n"
            "1. Click 'Browse' to select your Serato crate directory (e.g. _Serato_\\Subcrates folder).\n"
            "2. Check the crates you want to process (or use Select All/Deselect All).\n"
            "3. Choose Default or Custom banned words.\n"
            "4. Click 'Start' to begin processing. You can Pause/Resume or Stop at any time.\n"
            "5. Progress and logs will appear below.\n\n"
            "Created by DJ. Gadget\n"
            "Insta: @d.j_gadget, @dejay_gajet\n"
        )
        self.instr_label = tk.Label(
            banner_frame, text=instructions, justify=tk.LEFT, fg="#0a3d91",
            font=("Segoe UI", 10, "bold"), bg="white", anchor="nw", wraplength=650
        )
        self.instr_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 10), pady=10)

        try:
            self.logo_img_orig = Image.open("dj_gadget_logo.png")
        except Exception:
            self.logo_img_orig = None

        self.logo_label = tk.Label(banner_frame, bg="white")
        self.logo_label.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 20), pady=10)

        def resize_logo(event=None):
            if self.logo_img_orig:
                max_height = 80
                h = min(banner_frame.winfo_height() or max_height, max_height)
                w = int(self.logo_img_orig.width * h / self.logo_img_orig.height * 1.3)
                img = self.logo_img_orig.resize((w, h), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
                self.logo_label.config(image=self.logo_img)
        self.root.bind("<Configure>", resize_logo)
        banner_frame.bind("<Configure>", resize_logo)

        dir_frame = ttk.Frame(root, padding=(10, 0))
        dir_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(dir_frame, text="Crate Directory:", font=("Segoe UI", 10, "bold"), foreground="#0a3d91").pack(side=tk.LEFT)
        self.dir_var = tk.StringVar()
        dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var, width=60)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        ttk.Button(dir_frame, text="Browse", command=self.browse_dir).pack(side=tk.LEFT)

        banned_option_frame = ttk.Frame(root, padding=(10, 0))
        banned_option_frame.pack(fill=tk.X, pady=(0, 0))
        self.banned_mode = tk.StringVar(value="default")
        ttk.Label(banned_option_frame, text="Banned Words:", font=("Segoe UI", 10, "bold"), foreground="#0a3d91").pack(side=tk.LEFT)
        ttk.Radiobutton(banned_option_frame, text="Default", variable=self.banned_mode, value="default", command=self.update_banned_mode).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(banned_option_frame, text="Custom", variable=self.banned_mode, value="custom", command=self.update_banned_mode).pack(side=tk.LEFT, padx=5)

        banned_frame = ttk.Frame(root, padding=(10, 0))
        banned_frame.pack(fill=tk.X, pady=(0, 5))
        self.banned_text = tk.Text(banned_frame, height=2, width=60, font=("Segoe UI", 10))
        self.banned_text.pack(fill=tk.X, padx=(0, 0))
        self.banned_text.insert(tk.END, ", ".join(sorted(DEFAULT_BANNED_WORDS)))
        self.banned_text.config(state='disabled')

        select_frame = ttk.Frame(root, padding=(10, 0))
        select_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(select_frame, text="Select Crates to Process:", font=("Segoe UI", 10, "bold"), foreground="#0a3d91").pack(anchor=tk.W)

        self.crate_canvas = tk.Canvas(select_frame, height=180)
        self.crate_scrollbar = ttk.Scrollbar(select_frame, orient="vertical", command=self.crate_canvas.yview)
        self.crate_checks_frame = ttk.Frame(self.crate_canvas)

        self.crate_checks_frame.bind(
            "<Configure>",
            lambda e: self.crate_canvas.configure(
                scrollregion=self.crate_canvas.bbox("all")
            )
        )
        self.crate_canvas.create_window((0, 0), window=self.crate_checks_frame, anchor="nw")
        self.crate_canvas.configure(yscrollcommand=self.crate_scrollbar.set)

        self.crate_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.crate_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        btns_frame = ttk.Frame(select_frame)
        btns_frame.pack(fill=tk.X, pady=(2, 2))
        ttk.Button(btns_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns_frame, text="Deselect All", command=self.deselect_all).pack(side=tk.LEFT, padx=2)

        btn_frame = ttk.Frame(root, padding=(10, 0))
        btn_frame.pack(fill=tk.X, pady=(5, 5))
        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.pause_btn = ttk.Button(btn_frame, text="Pause", command=self.pause, state='disabled')
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.progress = ttk.Progressbar(btn_frame, orient='horizontal', length=300, mode='determinate')
        self.progress.pack(side=tk.LEFT, padx=20, fill=tk.X, expand=True)
        self.percent_label = ttk.Label(btn_frame, text="0%")
        self.percent_label.pack(side=tk.LEFT)

        log_frame = ttk.Frame(root, padding=(10, 0))
        log_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(log_frame, text="Log Output:", font=("Segoe UI", 10, "bold"), foreground="#0a3d91").pack(anchor=tk.W)
        self.log_text = tk.Text(log_frame, height=18, state='disabled', font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.root.after(100, self.poll_log_queue)
        self.thread = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.paused = False

        self.crate_checks = []
        self.crate_vars = []
        self.crate_files = []

    def update_banned_mode(self):
        if self.banned_mode.get() == "default":
            self.banned_text.config(state='normal')
            self.banned_text.delete("1.0", tk.END)
            self.banned_text.insert(tk.END, ", ".join(sorted(DEFAULT_BANNED_WORDS)))
            self.banned_text.config(state='disabled')
        else:
            self.banned_text.config(state='normal')

    def browse_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.dir_var.set(d)
            self.update_crate_checks()

    def update_crate_checks(self):
        for widget in self.crate_checks_frame.winfo_children():
            widget.destroy()
        self.crate_checks.clear()
        self.crate_vars.clear()
        self.crate_files.clear()
        dir_path = self.dir_var.get().strip()
        if os.path.isdir(dir_path):
            crate_files = [f for f in os.listdir(dir_path) if f.lower().endswith('.crate') and not f.lower().endswith('_clean.crate')]
            self.crate_files = [os.path.join(dir_path, f) for f in crate_files]
            for i, f in enumerate(crate_files):
                var = tk.BooleanVar(value=True)
                chk = ttk.Checkbutton(self.crate_checks_frame, text=f, variable=var)
                chk.pack(anchor=tk.W)
                self.crate_checks.append(chk)
                self.crate_vars.append(var)

    def select_all(self):
        for var in self.crate_vars:
            var.set(True)

    def deselect_all(self):
        for var in self.crate_vars:
            var.set(False)

    def poll_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, msg + '\n')
                self.log_text.see(tk.END)
                self.log_text.config(state='disabled')
        self.root.after(100, self.poll_log_queue)

    def start(self):
        dir_path = self.dir_var.get().strip()
        if not os.path.isdir(dir_path):
            messagebox.showerror("Error", "Please select a valid directory.")
            return
        if self.banned_mode.get() == "default":
            pf = get_profanity_filter(DEFAULT_BANNED_WORDS)
        else:
            words = self.banned_text.get("1.0", tk.END).strip()
            custom_words = {w.strip().lower() for w in words.split(",") if w.strip()}
            pf = get_profanity_filter(custom_words)
        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='normal', text='Pause')
        self.stop_btn.config(state='normal')
        self.progress['value'] = 0
        self.percent_label.config(text="0%")
        self.pause_event.clear()
        self.stop_event.clear()
        self.paused = False

        selected_files = [f for f, var in zip(self.crate_files, self.crate_vars) if var.get()]
        if not selected_files:
            messagebox.showerror("Error", "Please select at least one crate file.")
            self.start_btn.config(state='normal')
            return

        self.thread = threading.Thread(target=self.run_main, args=(selected_files, pf), daemon=True)
        self.thread.start()
        self.root.after(100, self.check_thread)

    def pause(self):
        if not self.paused:
            self.pause_event.set()
            self.pause_btn.config(text='Resume')
            self.paused = True
        else:
            self.pause_event.clear()
            self.pause_btn.config(text='Pause')
            self.paused = False

    def stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        self.pause_btn.config(state='disabled')
        self.stop_btn.config(state='disabled')
        self.start_btn.config(state='normal')

    def check_thread(self):
        if self.thread and self.thread.is_alive():
            self.root.after(100, self.check_thread)
        else:
            self.start_btn.config(state='normal')
            self.pause_btn.config(state='disabled')
            self.stop_btn.config(state='disabled')
            self.progress['value'] = 0
            self.percent_label.config(text="0%")

    def run_main(self, crate_files, pf):
        global sp_clients, genius, spotify_cache, genius_cache
        if not crate_files:
            logging.info("No crate files selected or found.")
            return
        dir_path = os.path.dirname(crate_files[0]) if crate_files else ""
        os.chdir(dir_path)

        while True:
            initialize_apis_and_caches()
            if (sp_clients[0] or sp_clients[1]) or OFFLINE_MODE and genius:
                break
            result = messagebox.askretrycancel(
                "Internet/Spotify/Genius Error",
                "Could not initialize one or more required APIs (likely no internet connection).\n\n"
                "Check your connection and click Retry, or Cancel to abort."
            )
            if not result:
                logging.error("User cancelled due to API/network error.")
                return
            time.sleep(2)

        total = len(crate_files)
        self.root.after(0, self.progress.config, {'maximum': total})
        for i, crate_path in enumerate(crate_files, 1):
            if self.stop_event.is_set():
                logging.info("Processing stopped by user.")
                break
            process_crate_file(crate_path, self.pause_event, self.stop_event, pf)
            percent = int((i / total) * 100)
            self.root.after(0, self.update_progress, i, percent)
        logging.info(f"\n{'=' * 80}\nProcessing complete. Saving caches...")
        save_cache(spotify_cache, SPOTIFY_CACHE_FILE)
        save_cache(genius_cache, GENIUS_CACHE_FILE)
        logging.info("Caches saved successfully. Script finished.")

    def update_progress(self, value, percent):
        self.progress['value'] = value
        self.percent_label.config(text=f"{percent}%")
