from gui_setup import *
from header import *
import re
import requests
import serato_crate.serato_crate as srt
from profanityfilter import ProfanityFilter

# --- Globals ---
genius = None


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
                    auth_manager = SpotifyClientCredentials(client_id=creds['client_id'],
                                                            client_secret=creds['client_secret'])
                    sp_clients[i] = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15)
                    if sp_clients[i].search(q='track:test', type='track', limit=1):
                        logging.info(f"Background: Successfully connected to Spotify API (account {i + 1}).")
                except Exception as e:
                    logging.error(f"Background: Error initializing Spotify API client {i + 1}: {e}")
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


# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- ProfanityFilter setup ---
def get_profanity_filter(custom_words=None):
    pf = ProfanityFilter()
    if custom_words:
        pf.define_words(list(custom_words))
    return pf


def is_profane(lyrics: str, pf: ProfanityFilter) -> bool:
    return pf.is_profane(lyrics)


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
                    logging.warning(
                        f"Spotify API {client_idx + 1} rate limit hit. Retrying after {retry_after} seconds.")
                    if client_idx == attempts[-1]:
                        time.sleep(retry_after + 1)
                    else:
                        break
                else:
                    logging.error(f"Spotify API error for '{q}' (Attempt {attempt + 1}): {se}")
                    break
            except Exception as e:
                logging.error(f"Spotify API error for '{q}' (Attempt {attempt + 1}): {e}")
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
def get_lyrics_from_genius(title: str, artist: str | None, genius) -> str | None:
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
            full_path = item_data[0][1] if isinstance(item_data, list) and item_data and item_data[0][
                0] == 'ptrk' else None
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
            logging.info(
                f"Processing: '{verified_title}' by '{display_artist}' (Original: '{os.path.basename(full_path)}')")
            if artist_genres:
                logging.info(f" -> Genres: {', '.join(artist_genres)}")

            lyrics = get_lyrics_from_genius(verified_title, verified_artist, genius)

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


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
