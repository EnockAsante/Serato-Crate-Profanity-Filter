import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import logging
import json
import os
import re
import unicodedata
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
import lyricsgenius
import threading
from tkinter import ttk, filedialog, messagebox
import time


spotify_cache, genius_cache = {}, {}
sp_clients = [None, None]
sp_current = 0

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
OFFLINE_MODE = False


# --- Cache helpers ---
def load_cache(cache_file):
    """
    Load cached data from a JSON file.

    Args:
        cache_file (str): Path to the cache file.

    Returns:
        dict: Cached data if file exists and is valid, otherwise an empty dict.
    """
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache_data, cache_file):
    """
    Save data to a JSON cache file.

    Args:
        cache_data (dict): Data to be cached.
        cache_file (str): Path to the cache file.
    """
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)


# API SETUP

# --- Spotify/Genius Initialization ---
def try_spotify_client(creds, idx, result_dict, event):
    """
    Attempt to initialize a Spotify API client with provided credentials.

    Args:
        creds (dict): Spotify API credentials (client_id, client_secret).
        idx (int): Index of the credential set (for logging).
        result_dict (dict): Dictionary to store the initialized client and index.
        event (threading.Event): Event to signal successful initialization.

    Logs:
        Success or failure of the Spotify API connection.
    """
    try:
        auth_manager = SpotifyClientCredentials(client_id=creds['client_id'], client_secret=creds['client_secret'])
        sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15)
        if sp.search(q='track:test', type='track', limit=1):
            logging.info(f"Successfully connected to Spotify API (account {idx + 1}).")
            result_dict['client'] = sp
            result_dict['index'] = idx
            event.set()
        else:
            raise Exception("Spotify authentication failed.")
    except Exception as e:
        logging.error(f"Error initializing Spotify API client {idx + 1}: {e}")


# ------------------common dependencies------------------

# --- Crate file finder ---
def find_crate_files(directory_path: str) -> list[str]:
    """
    Find .crate files in a directory that need processing.

    Args:
        directory_path (str): Path to the directory to search.

    Returns:
        list[str]: List of .crate file paths that require processing.
    """
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


# --- Song info extraction ---
def get_initial_song_info(file_path: str) -> tuple[str, str | None]:
    """
    Extract initial song title and artist from an audio file or its filename.

    Args:
        file_path (str): Path to the audio file.

    Returns:
        tuple: (title, artist) if found, otherwise (cleaned filename, None).
    """
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
