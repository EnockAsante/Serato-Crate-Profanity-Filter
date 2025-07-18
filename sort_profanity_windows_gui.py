import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import logging
import os
import re
import unicodedata
import json
import time
import serato_crate.serato_crate as srt
import lyricsgenius
from profanityfilter import ProfanityFilter
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import requests
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from PIL import Image, ImageTk

# --- Logging setup ---
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        self.log_queue.put(self.format(record))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- API Credentials ---
GENIUS_ACCESS_TOKEN = "eqzmComDvRqrsRFxh1caK40pEdbiWLQi2ddO5BU6_sNYiR-eQpyReFlAice5dbCX"
SPOTIPY_CLIENTS = [
    {
        'client_id': '9bbece559c344a4385aab976d35793c4',
        'client_secret': 'c7b219d11048464aa896da9b9096127b'
    },
    {
        'client_id': '72d3c94fa5af4dba99b86b3db9c09244',
        'client_secret': 'a891a7b7ae7b4c62996223266bd19b96'
    }
]

DEFAULT_BANNED_WORDS = {"fuck", "shit", "cunt", "asshole", "bitch", "dick", "pussy", "nigger", "faggot"}
SPOTIFY_CACHE_FILE = 'spotify_cache.json'
GENIUS_CACHE_FILE = 'genius_cache.json'

# --- Globals ---
spotify_cache, genius_cache = {}, {}
sp_clients = [None, None]
sp_current = 0
genius = None
OFFLINE_MODE = False

# --- Cache helpers ---
def load_cache(cache_file):
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_cache(cache_data, cache_file):
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)

# --- Spotify/Genius Initialization ---
def try_spotify_client(creds, idx, result_dict, event):
    try:
        auth_manager = SpotifyClientCredentials(client_id=creds['client_id'], client_secret=creds['client_secret'])
        sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15)
        if sp.search(q='track:test', type='track', limit=1):
            logging.info(f"Successfully connected to Spotify API (account {idx+1}).")
            result_dict['client'] = sp
            result_dict['index'] = idx
            event.set()
        else:
            raise Exception("Spotify authentication failed.")
    except Exception as e:
        logging.error(f"Error initializing Spotify API client {idx+1}: {e}")

def initialize_apis_and_caches():
    global sp_clients, sp_current, genius, spotify_cache, genius_cache, OFFLINE_MODE
    spotify_cache, genius_cache = load_cache(SPOTIFY_CACHE_FILE), load_cache(GENIUS_CACHE_FILE)
    logging.info(f"Loaded {len(spotify_cache)} items from Spotify cache and {len(genius_cache)} from Genius cache.")

    # Try to initialize one Spotify client at a time, but don't wait forever
    result = {}
    event = threading.Event()
    threads = []
    for i, creds in enumerate(SPOTIPY_CLIENTS):
        t = threading.Thread(target=try_spotify_client, args=(creds, i, result, event))
        threads.append(t)
        t.start()
        if event.wait(timeout=10):
            break

    for t in threads:
        t.join(timeout=1)

    sp_clients[:] = [None, None]
    if 'client' in result:
        sp_clients[result['index']] = result['client']
        sp_current = result['index']
        for i, creds in enumerate(SPOTIPY_CLIENTS):
            if i != result['index']:
                try:
                    auth_manager = SpotifyClientCredentials(client_id=creds['client_id'], client_secret=creds['client_secret'])
                    sp_clients[i] = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15)
                    if sp_clients[i].search(q='track:test', type='track', limit=1):
                        logging.info(f"Background: Successfully connected to Spotify API (account {i+1}).")
                except Exception as e:
                    logging.error(f"Background: Error initializing Spotify API client {i+1}: {e}")
        OFFLINE_MODE = False
    else:
        logging.error("Could not initialize any Spotify API client.")
        OFFLINE_MODE = True
        try:
            messagebox.showwarning(
                "Spotify API Unavailable",
                "Spotify API unavailable. Switching to offline mode.\n"
                "Only file names will be used for lyric search."
            )
        except Exception:
            print("Spotify API unavailable. Switching to offline mode. Only file names will be used for lyric search.")

    try:
        genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN, verbose=False, remove_section_headers=True, timeout=15)
        logging.info("Successfully initialized LyricsGenius client.")
    except Exception as e:
        logging.error(f"Error initializing LyricsGenius: {e}")
        genius = None

# --- Crate file finder ---
def find_crate_files(directory_path: str) -> list[str]:
    crate_files_to_process = []
    for root, _, files in os.walk(directory_path):
        for file in files:
            if not file.lower().endswith('.crate') or file.lower().endswith('_clean.crate'): continue
            original_path = os.path.join(root, file)
            clean_crate_path = os.path.join(root, f"{os.path.splitext(file)[0]}_CLEAN.crate")
            if not os.path.exists(clean_crate_path) or (
                    os.path.getmtime(original_path) > os.path.getmtime(clean_crate_path)):
                if os.path.exists(clean_crate_path): logging.info(
                    f"'{os.path.basename(original_path)}' has been modified. Queued for reprocessing.")
                crate_files_to_process.append(original_path)
            else:
                logging.info(f"Skipping '{os.path.basename(original_path)}' as up-to-date '_CLEAN.crate' exists.")
    return crate_files_to_process

# --- ProfanityFilter setup ---
def get_profanity_filter(custom_words=None):
    pf = ProfanityFilter()
    if custom_words:
        pf.define_words(list(custom_words))
    return pf

def is_profane(lyrics: str, pf: ProfanityFilter) -> bool:
    return pf.is_profane(lyrics)

# --- Song info extraction ---
def get_initial_song_info(file_path: str) -> tuple[str, str | None]:
    try:
        audio = EasyID3(file_path)
        title = audio.get('title', [None])[0]
        artist = audio.get('artist', [None])[0]
        if title: return title, artist
    except (ID3NoHeaderError, KeyError, Exception):
        pass
    filename = os.path.splitext(os.path.basename(file_path))[0]
    name_normalized = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('utf-8')
    junk_patterns = [r'\(.*?\)', r'\[.*?\]', r'[\-_]', 'Official', 'Audio', 'Video', 'HD', 'HQ', '4K']
    cleaned_name = re.sub('|'.join(junk_patterns), ' ', name_normalized, flags=re.IGNORECASE)
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
    match_artist_title = re.search(r'(.+?)\s-\s(.+)$', cleaned_name)
    if match_artist_title: return match_artist_title.group(2).strip(), match_artist_title.group(1).strip()
    return cleaned_name, None

# --- Spotify lookup (with offline mode) ---
def get_spotify_data(title_query: str, artist_query: str | None) -> dict:
    global sp_clients, sp_current, OFFLINE_MODE
    search_key = f"{title_query}|{artist_query or ''}"
    if search_key in spotify_cache: return spotify_cache[search_key]

    if OFFLINE_MODE:
        return {'title': title_query, 'artist': artist_query, 'genres': [], 'success': False, 'offline': True}

    attempts = [sp_current, 1 - sp_current]
    spotify_data = {'title': title_query, 'artist': artist_query, 'genres': [], 'success': False}
    q = f"track:{title_query}"
    if artist_query: q += f" artist:{artist_query}"

    retry_times = []
    for client_idx in attempts:
        sp = sp_clients[client_idx]
        if not sp:
            continue
        for attempt in range(3):
            try:
                results = sp.search(q=q, type='track', limit=1)
                time.sleep(1.5)
                if results and results['tracks']['items']:
                    track = results['tracks']['items'][0]
                    spotify_data.update({
                        'title': track['name'],
                        'artist': track['artists'][0]['name'] if track['artists'] else artist_query,
                        'success': True
                    })
                    if spotify_data['artist']:
                        artist_results = sp.search(q=f"artist:{spotify_data['artist']}", type='artist', limit=1)
                        time.sleep(1.5)
                        if artist_results and artist_results['artists']['items']:
                            spotify_data['genres'] = artist_results['artists']['items'][0].get('genres', [])
                    spotify_cache[search_key] = spotify_data
                    save_cache(spotify_cache, SPOTIFY_CACHE_FILE)
                    sp_current = client_idx
                    return spotify_data
                else:
                    if attempt == 2: break
            except spotipy.exceptions.SpotifyException as se:
                if se.http_status == 429:
                    retry_after = int(se.headers.get('Retry-After', 1))
                    retry_times.append(retry_after)
                    logging.warning(f"Spotify API {client_idx+1} rate limit hit. Retrying after {retry_after} seconds.")
                    if client_idx == attempts[-1]:
                        time.sleep(retry_after + 1)
                    else:
                        break
                else:
                    logging.error(f"Spotify API error for '{q}' (Attempt {attempt+1}): {se}")
                    break
            except Exception as e:
                logging.error(f"Spotify API error for '{q}' (Attempt {attempt+1}): {e}")
                break
            time.sleep(1.5)
    if retry_times:
        max_retry = max(retry_times)
        logging.warning(f"Both Spotify accounts rate-limited. Waiting for {max_retry} seconds before continuing.")
        time.sleep(max_retry + 1)
    spotify_cache[search_key] = spotify_data
    save_cache(spotify_cache, SPOTIFY_CACHE_FILE)
    return spotify_data

# --- Genius lyrics lookup ---
def get_lyrics_from_genius(title: str, artist: str | None) -> str | None:
    search_key = f"{title}|{artist or ''}"
    if search_key in genius_cache: return genius_cache[search_key]
    if not genius: return None

    lyrics = None
    for attempt in range(3):
        try:
            song_obj = genius.search_song(title, artist=artist)
            if song_obj:
                lyrics = re.sub(r'\d+(Embed|Translations)$', '', song_obj.lyrics).strip()
                break
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            logging.warning(
                f" -> Genius API/Network error for '{title}' (Attempt {attempt + 1}): {type(e).__name__}. Retrying...")
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            logging.error(f" -> An unexpected error occurred with Genius client for '{title}': {e}")
            break

    genius_cache[search_key] = lyrics
    return lyrics

# --- Crate processing ---
def process_crate_file(crate_file_path: str, pause_event, stop_event, pf: ProfanityFilter):
    try:
        crate_data = srt.read_crate_file(crate_file_path)
    except Exception as e:
        logging.error(f"Error reading crate file '{crate_file_path}': {e}. Skipping.")
        return

    original_header_data = [item for item in crate_data if item[0] != 'otrk']
    clean_song_paths, results_summary = [], {"CLEAN": 0, "PROFANE": 0, "NO_LYRICS": 0, "SKIPPED": 0}

    logging.info(f"\nProcessing songs in {os.path.basename(crate_file_path)}...")
    for item_type, item_data in crate_data:
        if stop_event.is_set():
            logging.info("Processing stopped by user.")
            return
        while pause_event.is_set():
            time.sleep(0.2)
        if item_type == 'otrk':
            full_path = item_data[0][1] if isinstance(item_data, list) and item_data and item_data[0][0] == 'ptrk' else None
            if not full_path:
                results_summary["SKIPPED"] += 1
                continue
            initial_title, initial_artist = get_initial_song_info(full_path)
            if OFFLINE_MODE:
                verified_title, verified_artist = initial_title, initial_artist
                artist_genres = []
            else:
                spotify_data = get_spotify_data(initial_title, initial_artist)
                verified_title = spotify_data['title']
                verified_artist = spotify_data['artist']
                artist_genres = spotify_data['genres']

            display_artist = verified_artist if verified_artist else 'Unknown'
            logging.info(f"Processing: '{verified_title}' by '{display_artist}' (Original: '{os.path.basename(full_path)}')")
            if artist_genres:
                logging.info(f" -> Genres: {', '.join(artist_genres)}")

            lyrics = get_lyrics_from_genius(verified_title, verified_artist)

            if lyrics:
                if not is_profane(lyrics, pf):
                    results_summary["CLEAN"] += 1
                    clean_song_paths.append(full_path)
                else:
                    results_summary["PROFANE"] += 1
            else:
                results_summary["NO_LYRICS"] += 1

    logging.info(f"--- Summary for {os.path.basename(crate_file_path)} ---")
    logging.info(
        f"Clean: {results_summary['CLEAN']}, Profane: {results_summary['PROFANE']}, No Lyrics: {results_summary['NO_LYRICS']}, Skipped: {results_summary['SKIPPED']}")

    if clean_song_paths:
        dir_name, base_name = os.path.split(crate_file_path)
        new_path = os.path.join(dir_name, f"{os.path.splitext(base_name)[0]}_CLEAN.crate")
        try:
            srt.write_crate_file(new_path, original_header_data + [('otrk', [('ptrk', p)]) for p in clean_song_paths])
            logging.info(f"Successfully created/updated clean crate: '{new_path}'")
        except Exception as e:
            logging.error(f"Error creating new crate file '{new_path}': {e}")
    else:
        logging.info("No clean songs found, so no new crate was created.")

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

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()