import serato_crate.serato_crate as srt
import re
import requests  # Import requests to catch its exceptions
from header import *


# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
GENIUS_ACCESS_TOKEN = "nwedEcNS-JLlDgTuqdaZNm-eh4-mzTJ2v3KTs1VLl65PmM8DhEep153cvECf99d8"
SPOTIPY_CLIENT_ID = '72d3c94fa5af4dba99b86b3db9c09244'
SPOTIPY_CLIENT_SECRET = 'a891a7b7ae7b4c62996223266bd19b96'
CUSTOM_BANNED_WORDS = {"fuck", "shit", "cunt", "asshole", "bitch", "dick", "pussy", "nigger", "faggot"}
SPOTIFY_CACHE_FILE = 'spotify_cache_cmd.json'
GENIUS_CACHE_FILE = 'genius_cache_cmd.json'
spotify_cache, genius_cache = {}, {}
sp, genius = None, None

def initialize_apis_and_caches():
    """Initializes all external services and loads caches."""
    global sp, genius, spotify_cache, genius_cache
    spotify_cache, genius_cache = load_cache(SPOTIFY_CACHE_FILE), load_cache(GENIUS_CACHE_FILE)
    logging.info(f"Loaded {len(spotify_cache)} items from Spotify cache and {len(genius_cache)} from Genius cache.")

    try:
        auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
        sp = spotipy.Spotify(
            auth_manager=auth_manager,
            requests_timeout=15
        )
        if sp.search(q='track:test', type='track', limit=1):
            logging.info("Successfully connected to Spotify API.")
        else:
            raise Exception("Spotify authentication failed.")
    except Exception as e:
        logging.error(f"Error initializing Spotify API client: {e}")
        sp = None

    try:
        genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN, verbose=False, remove_section_headers=True, timeout=15)
        logging.info("Successfully initialized LyricsGenius client.")
    except Exception as e:
        logging.error(f"Error initializing LyricsGenius: {e}")
        genius = None

def is_profane_custom(lyrics: str) -> bool:
    lyrics_lower = lyrics.lower()
    for word in CUSTOM_BANNED_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', lyrics_lower): return True
    return False

def get_spotify_data(title_query: str, artist_query: str | None) -> dict:
    search_key = f"{title_query}|{artist_query or ''}"
    if search_key in spotify_cache: return spotify_cache[search_key]
    if not sp: return {'title': title_query, 'artist': artist_query, 'genres': [], 'success': False}

    spotify_data = {'title': title_query, 'artist': artist_query, 'genres': [], 'success': False}
    q = f"track:{title_query}"
    if artist_query: q += f" artist:{artist_query}"

    for attempt in range(3):
        try:
            results = sp.search(q=q, type='track', limit=1)
            if results and results['tracks']['items']:
                track = results['tracks']['items'][0]
                spotify_data.update({
                    'title': track['name'],
                    'artist': track['artists'][0]['name'] if track['artists'] else artist_query,
                    'success': True
                })
                if spotify_data['artist']:
                    artist_results = sp.search(q=f"artist:{spotify_data['artist']}", type='artist', limit=1)
                    if artist_results and artist_results['artists']['items']:
                        spotify_data['genres'] = artist_results['artists']['items'][0].get('genres', [])
                spotify_cache[search_key] = spotify_data
                return spotify_data
            else:
                if attempt == 2: break
        except (spotipy.exceptions.SpotifyException, requests.exceptions.ReadTimeout) as e:
            logging.warning(f" -> Spotify API/Network error for '{q}' (Attempt {attempt + 1}): {type(e).__name__}.")
            if isinstance(e, spotipy.exceptions.SpotifyException) and e.http_status == 429:
                retry_after = int(e.headers.get('Retry-After', 3))
                logging.warning(f" -> Rate limit hit. Retrying after {retry_after} seconds.")
                time.sleep(retry_after + 1)
            else:
                time.sleep(3 * (attempt + 1))

    spotify_cache[search_key] = spotify_data
    return spotify_data

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


def process_crate_file(crate_file_path: str):
    try:
        crate_data = srt.read_crate_file(crate_file_path)
    except Exception as e:
        logging.error(f"Error reading crate file '{crate_file_path}': {e}. Skipping.")
        return

    original_header_data = [item for item in crate_data if item[0] != 'otrk']
    clean_song_paths, results_summary = [], {"CLEAN": 0, "PROFANE": 0, "NO_LYRICS": 0, "SKIPPED": 0}

    logging.info(f"\nProcessing songs in {os.path.basename(crate_file_path)}...")
    for item_type, item_data in crate_data:
        if item_type == 'otrk':
            full_path = item_data[0][1] if isinstance(item_data, list) and item_data and item_data[0][
                0] == 'ptrk' else None
            if not full_path:
                results_summary["SKIPPED"] += 1
                continue
            initial_title, initial_artist = get_initial_song_info(full_path)
            if not initial_title:
                results_summary["SKIPPED"] += 1
                continue
            spotify_data = get_spotify_data(initial_title, initial_artist)
            if not spotify_data['success']:
                #logging.warning(f" -> Could not verify '{initial_title}' on Spotify. Skipping lyrics check.")
                results_summary["SKIPPED"] += 1
                continue
            verified_title, verified_artist = spotify_data['title'], spotify_data['artist']
            logging.info(f"-> Checking: '{verified_title}' by '{verified_artist or 'Unknown'}'")
            lyrics = get_lyrics_from_genius(verified_title, verified_artist)
            if lyrics:
                if not is_profane_custom(lyrics):
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


def main():
    crates_directory = input("Please enter the path to the directory containing your Serato crates: ").strip()
    if not os.path.isdir(crates_directory):
        logging.error(f"The provided path '{crates_directory}' is not a valid directory. Exiting.")
        return

    initialize_apis_and_caches()
    if not sp or not genius:
        logging.error("Could not initialize one or more required APIs. Exiting.")
        return

    all_crate_files = find_crate_files(crates_directory)
    if not all_crate_files:
        logging.info(f"No '.crate' files found needing an update in '{crates_directory}' and its subdirectories.")
        return

    logging.info(f"Found {len(all_crate_files)} crate file(s) to process.")
    for i, crate_path in enumerate(all_crate_files, 1):
        logging.info(
            f"\n{'=' * 80}\n--- Processing Crate {i}/{len(all_crate_files)}: {os.path.basename(crate_path)} ---")
        # --- THIS IS THE CORRECTED LINE ---
        process_crate_file(crate_path)

    logging.info(f"\n{'=' * 80}\nProcessing complete. Saving caches...")
    save_cache(spotify_cache, SPOTIFY_CACHE_FILE)
    save_cache(genius_cache, GENIUS_CACHE_FILE)
    logging.info("Caches saved successfully. Script finished.")


if __name__ == "__main__":
    main()