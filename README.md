# Serato Crate Profanity Filter

A GUI tool for DJs to scan Serato crate files for profane songs using Spotify and Genius APIs, and create a new "clean" crate.

---

## Features

- **GUI**: Easy-to-use interface (Tkinter)
- **Profanity detection**: Uses [profanityfilter](https://pypi.org/project/profanityfilter/) (supports custom words and multiple languages)
- **Spotify API**: Looks up song/artist info (uses two accounts, switches if rate-limited)
- **Genius API**: Fetches lyrics for profanity check
- **Serato crate support**: Reads/writes `.crate` files (requires `serato_crate` Python package)
- **Caching**: Avoids duplicate API calls for faster processing

---

## Requirements

- Python 3.8+
- The following Python packages:
    - `tkinter` (comes with Python)
    - `spotipy`
    - `lyricsgenius`
    - `profanityfilter`
    - `mutagen`
    - `Pillow`
    - `serato_crate` (your local folder or pip package)

Install all dependencies with:
```sh
pip install spotipy lyricsgenius profanityfilter mutagen pillow


Usage
As a Python script
Place sort_profanity_windows_gui.py, dj_gadget_logo.png, and the serato_crate folder in the same directory.
Edit the script to set your Spotify and Genius tokens (see below).
Run:
Shell

python sort_profanity_windows_gui.py
As a Windows EXE
Build with PyInstaller:
Shell

pyinstaller --noconfirm --onefile --windowed --add-data "dj_gadget_logo.png;." --add-data "serato_crate;serato_crate/" sort_profanity_windows_gui.py
Run the generated dist/sort_profanity_windows_gui.exe.
How to Change API Tokens
Genius Token:
Edit the line:

Python

GENIUS_ACCESS_TOKEN = "YOUR_GENIUS_TOKEN"
Get a token at https://genius.com/api-clients

Spotify Tokens:
Edit the SPOTIPY_CLIENTS list:

Python

SPOTIPY_CLIENTS = [
    {'client_id': 'YOUR_FIRST_CLIENT_ID', 'client_secret': 'YOUR_FIRST_CLIENT_SECRET'},
    {'client_id': 'YOUR_SECOND_CLIENT_ID', 'client_secret': 'YOUR_SECOND_CLIENT_SECRET'}
]
Get tokens at https://developer.spotify.com/dashboard/applications

Tip: You can use just one Spotify account if you want, but two helps avoid rate limits.

What’s Left for the User
Set your own Genius and Spotify API credentials (see above).
Make sure dj_gadget_logo.png and the serato_crate folder are present.
If you want to use your own banned words, use the "Custom" option in the GUI.
If you want to add more language support, see the profanityfilter docs.
Notes
If you get rate-limited by Spotify, the app will automatically switch accounts or wait as needed.
All API results are cached for speed and to avoid hitting rate limits.
The app works on Windows and Mac (build on each OS for native executables).
If you update the code, rebuild the .exe with PyInstaller.
Credits
Created by DJ. Gadget
Instagram: @d.j_gadget | @dejay_gajet

