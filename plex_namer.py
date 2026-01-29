#!/usr/bin/env python3
"""
Plex Media Namer - Automatically rename media files to Plex conventions.

Usage:
    plex-namer [path]              Launch TUI (with optional starting path)
    plex-namer path --dry-run      Preview changes without TUI
    plex-namer path --no-tui       Simple CLI mode

Optional: TMDb API key for online verification (set TMDB_API_KEY environment variable)
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field

# Check for optional libraries
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Check for TUI library
try:
    from textual.app import App, ComposeResult
    from textual.widgets import (
        Header, Footer, Static, Button, DataTable, Label,
        DirectoryTree, Tree, ProgressBar, ListView, ListItem
    )
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.screen import Screen
    from textual.binding import Binding
    from textual import work
    from rich.text import Text
    HAS_TUI = True
except ImportError:
    HAS_TUI = False

# Check for Rich (fallback for non-TUI mode)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

# TMDb API configuration
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')
TMDB_SEARCH_MOVIE = 'https://api.themoviedb.org/3/search/movie'
TMDB_SEARCH_TV = 'https://api.themoviedb.org/3/search/tv'

# Common video extensions
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.webm', '.iso'}

# Common media folder locations
COMMON_PATHS = [
    Path("/Volumes"),
    Path.home() / "Movies",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
]

# Release/quality terms to strip from filenames (with word boundaries)
RELEASE_TERMS = [
    r'\b2160p\b', r'\b1080p\b', r'\b720p\b', r'\b480p\b', r'\b4k\b', r'\buhd\b',
    r'\bblu-?ray\b', r'\bbluray\b', r'\bbdrip\b', r'\bbrrip\b', r'\bdvdrip\b', r'\bhdtv\b', r'\bweb-?dl\b',
    r'\bwebrip\b', r'\bhdrip\b', r'\bhdcam\b', r'\bdvdscr\b', r'\bremux\b', r'\bbdremux\b',
    r'\bx264\b', r'\bx265\b', r'\bh\.?264\b', r'\bh\.?265\b', r'\bhevc\b', r'\bavc\b', r'\bxvid\b', r'\bdivx\b', r'\bmpeg\b',
    r'\bdts-?hd\b', r'\bdts\b', r'\btruehd\b', r'\batmos\b', r'\bdd5\.?1\b', r'\bddp?5\.?1\b', r'\bac3\b', r'\baac\b',
    r'\bflac\b', r'\beac3\b', r'\blpcm\b', r'\bma\.?5\.?1\b', r'\bma\.?7\.?1\b',
    r'\bhdr10\+?\b', r'\bhdr\b', r'\bdolby vision\b', r'\bdolby\b',
    r'\b3d\b', r'\bsbs\b', r'\bhsbs\b',
    r'-[a-z0-9]+$',
    r'\bproper\b', r'\brepack\b', r'\brerip\b', r'\binternal\b', r'\blimited\b', r'\bunrated\b', r'\bextended\b',
    r'\btheatrical\b', r'\bdirectors?\.?cut\b', r'\bfinal\.?cut\b', r'\bimax\b', r'\bremastered\b',
    r'\bmulti\b', r'\bdual\b', r'\bdubbed\b', r'\bsubbed\b', r'\b\d+bit\b', r'\b10bit\b', r'\b8bit\b',
    r'\bcriterion\b', r'\bcriterion\.?collection\b',
    r'\benglish\b', r'\bjapanese\b', r'\bfrench\b', r'\bgerman\b', r'\bspanish\b', r'\bitalian\b', r'\bkorean\b',
    r'\bchinese\b', r'\brussian\b', r'\bportuguese\b', r'\bhindi\b',
    r'\byts\b', r'\byify\b', r'\brarbg\b', r'\bsparks\b', r'\bgeckos\b', r'\btigole\b', r'\bqxr\b',
    r'www\.[a-z0-9]+\.[a-z]+', r'downloaded from.*',
]

TV_PATTERNS = [
    r'[sS](\d{1,2})[eE](\d{1,2})',
    r'[sS](\d{1,2})[\.\s]?[eE](\d{1,2})',
    r'(\d{1,2})x(\d{1,2})',
    r'[sS]eason\s*(\d{1,2}).*[eE]pisode\s*(\d{1,2})',
]

SEASON_FOLDER_PATTERNS = [
    r'[sS]eason\s*(\d{1,2})',
    r'[sS](\d{1,2})',
]


@dataclass
class MediaInfo:
    """Parsed media information"""
    original_path: Path  # For movies: the folder. For TV: the video file
    title: str
    year: Optional[int]
    is_tv: bool
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    tmdb_id: Optional[int] = None
    tmdb_verified: bool = False
    new_path: Optional[Path] = None  # For movies: new folder path. For TV: new file path
    selected: bool = True


# ============================================================================
# Core parsing functions
# ============================================================================

def clean_title(name: str) -> str:
    cleaned = re.sub(r'[._]', ' ', name)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = re.sub(r'\((?!\d{4}\))[^)]*\)', '', cleaned)
    for term in RELEASE_TERMS:
        cleaned = re.sub(term, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'[\s\-\.]+$', '', cleaned)
    return cleaned


def extract_year(name: str) -> Tuple[str, Optional[int]]:
    match = re.search(r'\((\d{4})\)', name)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2030:
            name_without = name[:match.start()].strip() + name[match.end():].strip()
            return name_without.strip(), year

    match = re.search(r'[\.\s\-](\d{4})[\.\s\-]', name)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2030:
            return name[:match.start()].strip(), year

    match = re.search(r'\s(\d{4})$', name)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2030:
            return name[:match.start()].strip(), year

    return name, None


def extract_tv_info(name: str) -> Tuple[Optional[int], Optional[int], str]:
    name_no_ext = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', name)
    for pattern in TV_PATTERNS:
        match = re.search(pattern, name_no_ext)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            remainder = name_no_ext[match.end():]
            ep_title = clean_title(remainder)
            ep_title = re.sub(r'^[\s\-\.]+', '', ep_title)
            return season, episode, ep_title if ep_title else None
    return None, None, None


def detect_media_type(path: Path) -> str:
    path_str = str(path).lower()
    if 'tv show' in path_str or 'tv series' in path_str or 'series' in path_str:
        return 'tv'
    if 'movie' in path_str or 'film' in path_str:
        return 'movies'

    try:
        for item in path.iterdir():
            if item.is_dir():
                for pattern in SEASON_FOLDER_PATTERNS:
                    if re.search(pattern, item.name, re.IGNORECASE):
                        return 'tv'

        for item in path.rglob('*'):
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                for pattern in TV_PATTERNS:
                    if re.search(pattern, item.name):
                        return 'tv'
    except PermissionError:
        pass
    return 'movies'


def search_tmdb_movie(title: str, year: Optional[int] = None) -> Optional[Dict]:
    if not TMDB_API_KEY or not HAS_REQUESTS:
        return None
    params = {'api_key': TMDB_API_KEY, 'query': title}
    if year:
        params['year'] = year
    try:
        response = requests.get(TMDB_SEARCH_MOVIE, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                return results[0]
    except Exception:
        pass
    return None


def search_tmdb_tv(title: str, year: Optional[int] = None) -> Optional[Dict]:
    if not TMDB_API_KEY or not HAS_REQUESTS:
        return None
    params = {'api_key': TMDB_API_KEY, 'query': title}
    if year:
        params['first_air_date_year'] = year
    try:
        response = requests.get(TMDB_SEARCH_TV, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                return results[0]
    except Exception:
        pass
    return None


def is_single_media_folder(path: Path) -> bool:
    """Check if folder appears to be a single movie/show folder (has video files directly)."""
    try:
        has_video_files = any(
            f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            for f in path.iterdir()
        )
        has_subfolders_with_videos = any(
            sub.is_dir() and any(
                f.suffix.lower() in VIDEO_EXTENSIONS
                for f in sub.rglob('*') if f.is_file()
            )
            for sub in path.iterdir() if sub.is_dir() and not sub.name.startswith('.')
        )
        # It's a single media folder if it has videos directly but no subfolders with videos
        return has_video_files and not has_subfolders_with_videos
    except PermissionError:
        return False


def find_existing_folder_ci(parent: Path, target_name: str) -> Optional[Path]:
    """Find existing folder with case-insensitive match."""
    target_lower = target_name.lower()
    try:
        for item in parent.iterdir():
            if item.is_dir() and item.name.lower() == target_lower:
                return item
    except PermissionError:
        pass
    return None


def is_plex_format(name: str) -> bool:
    match = re.match(r'^(.+?)\s*\((\d{4})\)\s*$', name)
    if not match:
        return False
    title = match.group(1)
    if re.search(r'\w\.\w', title):
        return False
    title_lower = title.lower()
    scene_indicators = ['1080p', '720p', '2160p', 'bluray', 'webrip', 'x264', 'x265', 'remux']
    return not any(ind in title_lower for ind in scene_indicators)


def parse_movie_folder(folder: Path) -> Optional[MediaInfo]:
    name = folder.name
    original_year = None

    # Check if already in Plex format
    plex_match = re.match(r'^(.+?)\s*\((\d{4})\)\s*(?:\[.*\])?\s*$', name.strip())
    if plex_match and is_plex_format(name.rstrip()):
        title = plex_match.group(1).strip()
        original_year = int(plex_match.group(2))
        year = original_year
    else:
        name_clean, year = extract_year(name)
        original_year = year
        title = clean_title(name_clean)

    if not title:
        return None

    try:
        video_files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]
    except PermissionError:
        return None

    if not video_files:
        return None

    main_file = max(video_files, key=lambda f: f.stat().st_size)

    # Store the FOLDER as original_path, not the file
    info = MediaInfo(original_path=folder, title=title, year=year, is_tv=False)

    # Try TMDb lookup
    tmdb_result = search_tmdb_movie(title, year)
    if tmdb_result:
        info.title = tmdb_result.get('title', title)
        release_date = tmdb_result.get('release_date', '')
        if release_date:
            tmdb_year = int(release_date[:4])
            # Only use TMDb year if we didn't have one, or it's within 1 year
            # This prevents creating duplicates due to year differences
            if original_year is None:
                info.year = tmdb_year
            elif abs(tmdb_year - original_year) <= 1:
                info.year = tmdb_year
            # Otherwise keep original year
        info.tmdb_id = tmdb_result.get('id')
        info.tmdb_verified = True

    if info.year:
        new_folder_name = f"{info.title} ({info.year})".strip()
    else:
        new_folder_name = info.title

    # Check for existing folder with same name (case-insensitive)
    existing = find_existing_folder_ci(folder.parent, new_folder_name)
    if existing and existing != folder:
        # A folder with this name already exists - don't create duplicate
        # Instead, mark as needing no change (will be filtered out)
        info.new_path = None
        return info

    new_folder = folder.parent / new_folder_name
    info.new_path = new_folder
    return info


def parse_tv_show_folder(folder: Path) -> List[MediaInfo]:
    results = []
    folder_name = folder.name.strip()

    plex_match = re.match(r'^(.+?)\s*\((\d{4})\)\s*$', folder_name)
    if plex_match and is_plex_format(folder_name):
        show_name = plex_match.group(1).strip()
        show_year = int(plex_match.group(2))
    else:
        show_name, show_year = extract_year(folder_name)
        show_name = clean_title(show_name)

    tmdb_result = search_tmdb_tv(show_name, show_year)
    if tmdb_result:
        show_name = tmdb_result.get('name', show_name)
        first_air = tmdb_result.get('first_air_date', '')
        if first_air:
            show_year = int(first_air[:4])

    try:
        for video_file in folder.rglob('*'):
            if not video_file.is_file() or video_file.suffix.lower() not in VIDEO_EXTENSIONS:
                continue

            season, episode, ep_title = extract_tv_info(video_file.name)
            if season is None:
                parent_name = video_file.parent.name
                for pattern in SEASON_FOLDER_PATTERNS:
                    match = re.search(pattern, parent_name, re.IGNORECASE)
                    if match:
                        season = int(match.group(1))
                        break

            if season is None or episode is None:
                continue

            info = MediaInfo(
                original_path=video_file, title=show_name, year=show_year, is_tv=True,
                season=season, episode=episode, episode_title=ep_title,
                tmdb_verified=tmdb_result is not None,
            )

            if show_year:
                show_folder_name = f"{show_name} ({show_year})"
            else:
                show_folder_name = show_name

            season_folder_name = f"Season {season:02d}"
            ep_code = f"S{season:02d}E{episode:02d}"
            if ep_title:
                new_file_name = f"{show_name} ({show_year}) - {ep_code} - {ep_title}{video_file.suffix}" if show_year else f"{show_name} - {ep_code} - {ep_title}{video_file.suffix}"
            else:
                new_file_name = f"{show_name} ({show_year}) - {ep_code}{video_file.suffix}" if show_year else f"{show_name} - {ep_code}{video_file.suffix}"

            new_folder = folder.parent / show_folder_name / season_folder_name
            info.new_path = new_folder / new_file_name
            results.append(info)
    except PermissionError:
        pass

    return results


def needs_rename(info: MediaInfo) -> bool:
    if info.new_path is None:
        return False
    return info.original_path != info.new_path


def collect_changes(path: Path, media_type: str) -> List[MediaInfo]:
    all_changes = []
    try:
        if media_type == 'movies':
            for item in path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    info = parse_movie_folder(item)
                    if info and needs_rename(info):
                        all_changes.append(info)
        else:
            for item in path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    episodes = parse_tv_show_folder(item)
                    for ep in episodes:
                        if needs_rename(ep):
                            all_changes.append(ep)
    except PermissionError:
        pass
    return all_changes


def apply_changes(changes: List[MediaInfo]) -> int:
    count = 0
    for info in changes:
        if not info.selected or info.new_path is None:
            continue
        try:
            if info.is_tv:
                # TV: original_path is video file, new_path is new file location
                info.new_path.parent.mkdir(parents=True, exist_ok=True)
                info.original_path.rename(info.new_path)
            else:
                # Movie: original_path is folder, new_path is new folder name
                # Simply rename the entire folder
                if info.original_path.is_dir() and info.original_path != info.new_path:
                    # Check if target doesn't exist (case-insensitive check already done in parse)
                    if not info.new_path.exists():
                        info.original_path.rename(info.new_path)
                        # Now rename the main video file inside to match folder name
                        for f in info.new_path.iterdir():
                            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                                # Find the largest video file (main movie)
                                video_files = [vf for vf in info.new_path.iterdir()
                                              if vf.is_file() and vf.suffix.lower() in VIDEO_EXTENSIONS]
                                if video_files:
                                    main_video = max(video_files, key=lambda x: x.stat().st_size)
                                    new_video_name = f"{info.new_path.name}{main_video.suffix}"
                                    new_video_path = info.new_path / new_video_name
                                    if main_video != new_video_path:
                                        main_video.rename(new_video_path)
                                break
            count += 1
        except (PermissionError, OSError):
            pass
    return count


def cleanup_empty_folders(folder: Path) -> None:
    if not folder.exists() or not folder.is_dir():
        return
    try:
        for subfolder in list(folder.iterdir()):
            if subfolder.is_dir():
                cleanup_empty_folders(subfolder)
        contents = [f for f in folder.iterdir() if not f.name.startswith('.')]
        if not contents:
            for hidden in folder.iterdir():
                if hidden.is_file():
                    hidden.unlink()
            folder.rmdir()
    except (PermissionError, OSError):
        pass


# ============================================================================
# TUI Application
# ============================================================================

if HAS_TUI:

    CSS = """
    Screen {
        background: $surface;
    }

    /* ===== Main Menu Screen ===== */
    #menu-container {
        align: center middle;
        height: 100%;
    }

    #menu-box {
        width: 60;
        height: auto;
        border: solid $primary;
        padding: 1 2;
    }

    #menu-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1;
    }

    #menu-subtitle {
        text-align: center;
        color: $text-muted;
        padding: 0 0 1 0;
    }

    .menu-button {
        width: 100%;
        margin: 1 0;
    }

    #tmdb-status {
        text-align: center;
        padding: 1;
        color: $text-muted;
    }

    #menu-instruction {
        text-align: center;
        padding: 1;
        color: $text;
    }

    #menu-spacer {
        height: 1;
    }

    /* ===== Browser Screen ===== */
    #current-path {
        padding: 1;
        color: $text;
        background: $primary-background;
    }

    #quick-paths-buttons {
        height: auto;
        padding: 0 1 1 1;
    }

    #dir-tree {
        height: 1fr;
        border: solid $primary;
        margin: 0 1;
    }

    #selected-path {
        color: $success;
        padding: 1;
    }

    #browser-buttons {
        height: auto;
        align: center middle;
        padding: 0 0 1 0;
    }

    #browser-buttons Button {
        margin: 0 1;
    }

    /* ===== Rename Screen ===== */
    #rename-container {
        height: 100%;
        padding: 1;
    }

    #status-bar {
        dock: top;
        height: 3;
        padding: 0 1;
        background: $primary-background;
        color: $text;
    }

    #file-list {
        height: 1fr;
        border: solid $primary;
        margin: 1 0;
    }

    #button-bar {
        dock: bottom;
        height: 3;
        align: center middle;
    }

    #button-bar Button {
        margin: 0 1;
    }

    .status-label {
        padding: 0 1;
    }

    DataTable {
        height: 100%;
    }

    DataTable > .datatable--cursor {
        background: $accent;
    }

    #progress-container {
        height: 3;
        padding: 0 1;
        display: none;
    }

    #progress-container.visible {
        display: block;
    }

    #success-message {
        text-align: center;
        color: $success;
        text-style: bold;
        padding: 1;
        display: none;
    }

    #success-message.visible {
        display: block;
    }

    /* ===== Quick Paths ===== */
    #quick-paths {
        height: auto;
        padding: 1;
        background: $surface-darken-1;
    }

    #quick-paths-label {
        color: $text-muted;
        padding: 0 0 1 0;
    }

    #quick-paths-buttons {
        layout: horizontal;
    }

    .quick-path-btn {
        margin: 0 1 0 0;
    }
    """

    class MainMenuScreen(Screen):
        """Main menu - Step 1: Select your Plex Media folder."""

        BINDINGS = [
            Binding("enter", "browse", "Browse"),
            Binding("q", "quit", "Quit"),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            with Container(id="menu-container"):
                with Vertical(id="menu-box"):
                    yield Label("🎬 Plex Namer", id="menu-title")
                    yield Label("Rename media files to Plex conventions", id="menu-subtitle")
                    yield Label("", id="menu-spacer")
                    yield Label("Step 1: Select your Plex Media folder", id="menu-instruction")

                    yield Button("📁 Select Plex Media Folder", id="btn-browse", classes="menu-button", variant="primary")
                    yield Button("❌ Quit", id="btn-quit", classes="menu-button", variant="error")

                    tmdb_text = "✓ TMDb Connected" if TMDB_API_KEY and HAS_REQUESTS else "⚠ TMDb not configured"
                    yield Label(tmdb_text, id="tmdb-status")
            yield Footer()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-browse":
                self.app.push_screen(BrowserScreen())
            elif event.button.id == "btn-quit":
                self.app.exit()

        def action_browse(self) -> None:
            self.app.push_screen(BrowserScreen())

        def action_quit(self) -> None:
            self.app.exit()


    class MediaTypeScreen(Screen):
        """Step 2: Choose Movies or TV Shows."""

        BINDINGS = [
            Binding("m", "select_movies", "Movies"),
            Binding("t", "select_tv", "TV Shows"),
            Binding("escape", "go_back", "Back"),
            Binding("q", "go_back", "Back"),
        ]

        def __init__(self, plex_folder: Path):
            super().__init__()
            self.plex_folder = plex_folder

        def compose(self) -> ComposeResult:
            yield Header()
            with Container(id="menu-container"):
                with Vertical(id="menu-box"):
                    yield Label("🎬 Plex Namer", id="menu-title")
                    yield Label(f"📁 {self.plex_folder}", id="menu-subtitle")
                    yield Label("", id="menu-spacer")
                    yield Label("Step 2: What do you want to rename?", id="menu-instruction")

                    yield Button("🎥 Movies", id="btn-movies", classes="menu-button", variant="primary")
                    yield Button("📺 TV Shows", id="btn-tv", classes="menu-button", variant="primary")
                    yield Button("← Back", id="btn-back", classes="menu-button")
            yield Footer()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-movies":
                self.action_select_movies()
            elif event.button.id == "btn-tv":
                self.action_select_tv()
            elif event.button.id == "btn-back":
                self.app.pop_screen()

        def action_select_movies(self) -> None:
            # Check for Movies subfolder
            movies_path = self.plex_folder / "Movies"
            if movies_path.exists():
                self.app.push_screen(RenameScreen(movies_path, "movies"))
            else:
                # Use the selected folder directly
                self.app.push_screen(RenameScreen(self.plex_folder, "movies"))

        def action_select_tv(self) -> None:
            # Check for TV Shows subfolder
            tv_path = self.plex_folder / "TV Shows"
            if tv_path.exists():
                self.app.push_screen(RenameScreen(tv_path, "tv"))
            else:
                # Use the selected folder directly
                self.app.push_screen(RenameScreen(self.plex_folder, "tv"))

        def action_go_back(self) -> None:
            self.app.pop_screen()


    class BrowserScreen(Screen):
        """File browser to select a folder."""

        BINDINGS = [
            Binding("escape", "go_back", "Back"),
            Binding("enter", "select_folder", "Select"),
            Binding("q", "go_back", "Back"),
        ]

        def __init__(self, start_path: Path = None):
            super().__init__()
            self.start_path = start_path or Path.home()
            self.selected_path = self.start_path

        def compose(self) -> ComposeResult:
            yield Header()
            yield Label("📁 Select a folder containing media files", id="current-path")
            with Horizontal(id="quick-paths-buttons"):
                yield Button("🏠 Home", id="qp-home", classes="quick-path-btn")
                yield Button("💾 Volumes", id="qp-volumes", classes="quick-path-btn")
                yield Button("📥 Downloads", id="qp-downloads", classes="quick-path-btn")
                yield Button("🎬 Movies", id="qp-movies", classes="quick-path-btn")
            yield DirectoryTree(str(self.start_path), id="dir-tree")
            yield Label(f"Selected: {self.selected_path}", id="selected-path")
            with Horizontal(id="browser-buttons"):
                yield Button("✓ Select This Folder", id="btn-select", variant="primary")
                yield Button("← Back", id="btn-back", variant="default")
            yield Footer()

        def on_mount(self) -> None:
            tree = self.query_one("#dir-tree", DirectoryTree)
            tree.show_root = True
            tree.show_guides = True

        def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
            self.selected_path = Path(event.path)
            label = self.query_one("#selected-path", Label)
            label.update(f"Selected: {self.selected_path}")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-select":
                self.action_select_folder()
            elif event.button.id == "btn-back":
                self.action_go_back()
            elif event.button.id == "qp-home":
                self._change_root(Path.home())
            elif event.button.id == "qp-volumes":
                self._change_root(Path("/Volumes"))
            elif event.button.id == "qp-downloads":
                self._change_root(Path.home() / "Downloads")
            elif event.button.id == "qp-movies":
                self._change_root(Path.home() / "Movies")

        def _change_root(self, path: Path) -> None:
            if path.exists():
                self.selected_path = path
                tree = self.query_one("#dir-tree", DirectoryTree)
                tree.path = path
                label = self.query_one("#selected-path", Label)
                label.update(f"Selected: {self.selected_path}")
            else:
                self.notify(f"Path not found: {path}", severity="error")

        def action_select_folder(self) -> None:
            if self.selected_path.exists() and self.selected_path.is_dir():
                # Check if this looks like a single movie folder instead of a library
                if is_single_media_folder(self.selected_path):
                    self.notify(
                        "This looks like a single movie folder. Select the parent folder (e.g., 'Plex Media' or 'Movies').",
                        severity="warning",
                        timeout=5
                    )
                    return
                # Go to media type selection
                self.app.push_screen(MediaTypeScreen(self.selected_path))
            else:
                self.notify("Please select a valid folder", severity="error")

        def action_go_back(self) -> None:
            self.app.pop_screen()


    class RenameScreen(Screen):
        """Screen for renaming files."""

        BINDINGS = [
            Binding("escape", "go_back", "Back"),
            Binding("a", "select_all", "Select All"),
            Binding("n", "select_none", "Select None"),
            Binding("space", "toggle_selected", "Toggle"),
            Binding("enter", "apply", "Apply"),
            Binding("r", "refresh", "Refresh"),
            Binding("q", "go_back", "Back"),
        ]

        def __init__(self, path: Path, media_type: str):
            super().__init__()
            self.media_path = path
            self.media_type = media_type if media_type != "auto" else detect_media_type(path)
            self.changes: List[MediaInfo] = []

        def compose(self) -> ComposeResult:
            yield Header()
            with Container(id="rename-container"):
                with Horizontal(id="status-bar"):
                    yield Label(f"📁 {self.media_path.name}", id="path-label", classes="status-label")
                    yield Label(f"🎬 {self.media_type}", id="type-label", classes="status-label")
                    tmdb_status = "✓ TMDb" if TMDB_API_KEY and HAS_REQUESTS else "No TMDb"
                    yield Label(tmdb_status, id="tmdb-label", classes="status-label")
                    yield Label("Scanning...", id="count-label", classes="status-label")

                with ScrollableContainer(id="file-list"):
                    yield DataTable(id="changes-table")

                with Container(id="progress-container"):
                    yield Label("Scanning...", id="progress-label")
                    yield ProgressBar(id="progress-bar", show_eta=False)

                yield Label("", id="success-message")

                with Horizontal(id="button-bar"):
                    yield Button("Select All [A]", id="btn-all", variant="default")
                    yield Button("Select None [N]", id="btn-none", variant="default")
                    yield Button("Apply Changes [Enter]", id="btn-apply", variant="primary")
                    yield Button("← Back [Q]", id="btn-back", variant="default")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#changes-table", DataTable)
            table.add_columns("✓", "Title", "Year", "TMDb", "Original", "New Name")
            table.cursor_type = "row"
            self.scan_files()

        @work(exclusive=True, thread=True)
        def scan_files(self) -> None:
            progress_container = self.query_one("#progress-container")
            self.app.call_from_thread(progress_container.add_class, "visible")

            self.changes = collect_changes(self.media_path, self.media_type)

            self.app.call_from_thread(self.populate_table)
            self.app.call_from_thread(progress_container.remove_class, "visible")

            # Show success message if we just renamed something
            if hasattr(self, '_last_rename_count') and self._last_rename_count > 0:
                count = self._last_rename_count
                self._last_rename_count = 0
                def show_success():
                    success_msg = self.query_one("#success-message", Label)
                    success_msg.update(f"✓ Successfully renamed {count} item(s)!")
                    success_msg.add_class("visible")
                self.app.call_from_thread(show_success)

        def populate_table(self) -> None:
            table = self.query_one("#changes-table", DataTable)
            table.clear()

            for i, info in enumerate(self.changes):
                checkbox = "☑" if info.selected else "☐"
                tmdb = "✓" if info.tmdb_verified else "-"
                year = str(info.year) if info.year else "?"

                original = info.original_path.name
                if len(original) > 35:
                    original = original[:32] + "..."

                new_name = info.new_path.name if info.new_path else ""
                if len(new_name) > 35:
                    new_name = new_name[:32] + "..."

                table.add_row(checkbox, info.title, year, tmdb, original, new_name, key=str(i))

            # Update buttons and show message based on whether there are changes
            btn_apply = self.query_one("#btn-apply", Button)
            btn_all = self.query_one("#btn-all", Button)
            btn_none = self.query_one("#btn-none", Button)
            success_msg = self.query_one("#success-message", Label)

            if not self.changes:
                btn_apply.disabled = True
                btn_all.disabled = True
                btn_none.disabled = True
                # Show "all good" message if we didn't just rename something
                if not (hasattr(self, '_last_rename_count') and self._last_rename_count > 0):
                    success_msg.update("✓ All files are already correctly named!")
                    success_msg.add_class("visible")
            else:
                btn_apply.disabled = False
                btn_all.disabled = False
                btn_none.disabled = False
                success_msg.remove_class("visible")

            selected = sum(1 for c in self.changes if c.selected)
            count_label = self.query_one("#count-label", Label)
            if not self.changes:
                count_label.update("✓ All files OK!")
            else:
                count_label.update(f"{selected}/{len(self.changes)} selected")

        def action_toggle_selected(self) -> None:
            table = self.query_one("#changes-table", DataTable)
            if table.cursor_row is not None and table.cursor_row < len(self.changes):
                info = self.changes[table.cursor_row]
                info.selected = not info.selected
                self.populate_table()
                table.cursor_coordinate = (table.cursor_row, 0)

        def action_select_all(self) -> None:
            for info in self.changes:
                info.selected = True
            self.populate_table()

        def action_select_none(self) -> None:
            for info in self.changes:
                info.selected = False
            self.populate_table()

        def action_apply(self) -> None:
            selected = [c for c in self.changes if c.selected]
            if not selected:
                self.notify("No files selected!", severity="warning")
                return

            count = apply_changes(selected)

            # Only clean up empty folders for TV shows (where we moved individual files)
            # For movies, we renamed the whole folder so nothing to clean up
            for info in selected:
                if info.is_tv:
                    cleanup_empty_folders(info.original_path.parent)

            # Show notification immediately
            self.notify(f"Renamed {count} item(s)!", severity="information")

            # Store count for after rescan completes
            self._last_rename_count = count

            # Rescan to update the list
            self.scan_files()

        def action_refresh(self) -> None:
            success_msg = self.query_one("#success-message", Label)
            success_msg.remove_class("visible")
            self.scan_files()

        def action_go_back(self) -> None:
            self.app.pop_screen()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-all":
                self.action_select_all()
            elif event.button.id == "btn-none":
                self.action_select_none()
            elif event.button.id == "btn-apply":
                self.action_apply()
            elif event.button.id == "btn-back":
                self.action_go_back()

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.row_key and int(event.row_key.value) < len(self.changes):
                info = self.changes[int(event.row_key.value)]
                info.selected = not info.selected
                self.populate_table()


    class PlexNamerApp(App):
        """Main TUI application."""

        TITLE = "Plex Namer"
        CSS = CSS

        def __init__(self, start_path: Path = None):
            super().__init__()
            self.start_path = start_path

        def on_mount(self) -> None:
            if self.start_path:
                # Go directly to rename screen if path provided
                media_type = detect_media_type(self.start_path)
                self.push_screen(RenameScreen(self.start_path, media_type))
            else:
                # Show main menu
                self.push_screen(MainMenuScreen())


# ============================================================================
# CLI fallback (non-TUI mode)
# ============================================================================

def run_cli(path: Path, media_type: str, dry_run: bool, no_confirm: bool):
    """Run in CLI mode (no TUI)."""
    if HAS_RICH:
        console.print(Panel("[bold cyan]Plex Namer[/bold cyan]"))
        console.print(f"[dim]Path:[/dim] {path}")
        console.print(f"[dim]Type:[/dim] {media_type}")
        tmdb_status = "[green]Connected[/green]" if TMDB_API_KEY and HAS_REQUESTS else "[yellow]Disabled[/yellow]"
        console.print(f"[dim]TMDb:[/dim] {tmdb_status}")
    else:
        print(f"\nPlex Namer")
        print("=" * 40)
        print(f"Path: {path}")
        print(f"Type: {media_type}")

    changes = collect_changes(path, media_type)

    if not changes:
        if HAS_RICH:
            console.print("[green]✓[/green] All files are already correctly named!")
        else:
            print("✓ All files are already correctly named!")
        return

    if HAS_RICH:
        table = Table(title=f"Preview: {len(changes)} file(s) to rename", box=box.ROUNDED)
        table.add_column("#", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Year", style="yellow")
        table.add_column("TMDb")
        table.add_column("From → To")

        for i, info in enumerate(changes, 1):
            tmdb = "[green]✓[/green]" if info.tmdb_verified else "-"
            year = str(info.year) if info.year else "?"
            from_name = info.original_path.name[:40] + "..." if len(info.original_path.name) > 40 else info.original_path.name
            to_name = info.new_path.name[:40] + "..." if info.new_path and len(info.new_path.name) > 40 else (info.new_path.name if info.new_path else "")
            table.add_row(str(i), info.title, year, tmdb, f"{from_name}\n[green]→ {to_name}[/green]")

        console.print(table)
    else:
        print(f"\nPREVIEW: {len(changes)} file(s) to rename\n")
        for i, info in enumerate(changes, 1):
            print(f"{i}. {info.title} ({info.year or '?'})")
            print(f"   FROM: {info.original_path.name}")
            print(f"   TO:   {info.new_path.name if info.new_path else ''}\n")

    if dry_run:
        if HAS_RICH:
            console.print("[yellow][DRY RUN][/yellow] No changes made.")
        else:
            print("[DRY RUN] No changes made.")
        return

    if not no_confirm:
        if HAS_RICH:
            if not Confirm.ask("Apply these changes?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return
        else:
            response = input("Apply these changes? [y/N] ").strip().lower()
            if response != 'y':
                print("Cancelled.")
                return

    count = apply_changes(changes)
    for info in changes:
        if info.selected:
            cleanup_empty_folders(info.original_path.parent)

    if HAS_RICH:
        console.print(f"[green]✓[/green] Renamed {count} file(s)")
    else:
        print(f"✓ Renamed {count} file(s)")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Rename media files to Plex naming conventions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  plex-namer                       Launch interactive menu
  plex-namer /Volumes/Media        Open folder directly
  plex-namer /path/folder --dry-run   Preview without TUI
  plex-namer /path/folder --no-tui    Simple CLI mode

Environment:
  TMDB_API_KEY    Set for title verification (free key at themoviedb.org)
        """
    )
    parser.add_argument('path', nargs='?', help='Path to media folder (optional)')
    parser.add_argument('--type', '-t', choices=['movies', 'tv', 'auto'], default='auto',
                        help='Media type (default: auto-detect)')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Preview only, no changes')
    parser.add_argument('--no-confirm', '-y', action='store_true',
                        help='Skip confirmation')
    parser.add_argument('--no-tui', action='store_true',
                        help='Disable TUI, use simple CLI mode')

    args = parser.parse_args()

    # If path provided, validate it
    if args.path:
        path = Path(args.path).resolve()
        if not path.exists():
            print(f"Error: Path does not exist: {path}")
            sys.exit(1)
        if not path.is_dir():
            print(f"Error: Not a directory: {path}")
            sys.exit(1)
    else:
        path = None

    # Determine media type
    media_type = args.type
    if path and media_type == 'auto':
        media_type = detect_media_type(path)

    # Use TUI if available and not disabled
    if HAS_TUI and not args.no_tui and not args.dry_run:
        app = PlexNamerApp(start_path=path)
        app.run()
    elif path:
        run_cli(path, media_type, args.dry_run, args.no_confirm)
    else:
        print("Error: Path required when using --no-tui or --dry-run")
        print("Usage: plex-namer /path/to/folder --no-tui")
        sys.exit(1)


if __name__ == '__main__':
    main()
