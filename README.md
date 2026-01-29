# Plex Namer

A command-line tool to automatically rename media files to [Plex naming conventions](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/).

Converts messy scene release names like:
```
The.Grand.Budapest.Hotel.2014.1080p.BluRay.CEE.AVC.DTS-HD.MA.5.1-RARBG.mkv
```

Into clean Plex-compatible names:
```
The Grand Budapest Hotel (2014)/The Grand Budapest Hotel (2014).mkv
```

## Features

- Handles **Movies**, **TV Shows**, and **Music**
- Auto-detects media type or specify manually
- **TMDb integration** for accurate movie/TV titles and years (optional)
- **MusicBrainz integration** for accurate artist/album names (automatic)
- Interactive TUI with file browser
- Preview mode to see changes before applying
- Cleans up empty folders after renaming
- Preserves already-correct folder names

## Installation

```bash
# Clone the repo
git clone https://github.com/stonefruit7/plex-namer.git
cd plex-namer

# Install with all features (recommended)
pip install -e ".[all]"

# Or install with specific features
pip install -e ".[tmdb]"   # TMDb support only
pip install -e ".[rich]"   # Rich CLI only
pip install -e .           # Basic (no extras)
```

Or install directly from GitHub:

```bash
pip install "git+https://github.com/stonefruit7/plex-namer.git#egg=plex-namer[all]"
```

## Usage

### Basic Usage

```bash
# Preview changes (recommended first)
python plex_namer.py /path/to/media --dry-run

# Apply changes (will ask for confirmation)
python plex_namer.py /path/to/media

# Apply without confirmation
python plex_namer.py /path/to/media --no-confirm
```

### Options

| Flag | Description |
|------|-------------|
| `--dry-run`, `-n` | Preview changes without renaming |
| `--type`, `-t` | Force media type: `movies`, `tv`, `music`, or `auto` (default) |
| `--no-confirm`, `-y` | Skip confirmation prompt |

### Examples

```bash
# Rename movies
python plex_namer.py "/Volumes/Media/Movies"

# Rename TV shows
python plex_namer.py "/Volumes/Media/TV Shows" --type tv

# Preview only
python plex_namer.py ~/Downloads/movies --dry-run
```

## TMDb Integration

For more accurate title matching and year verification, set up a free TMDb API key:

1. Create a free account at [themoviedb.org](https://www.themoviedb.org/)
2. Go to Settings > API and request an API key
3. Set the environment variable:

```bash
# One-time use
TMDB_API_KEY="your_key" python plex_namer.py /path/to/media

# Or add to your shell profile (~/.zshrc or ~/.bashrc)
export TMDB_API_KEY="your_key_here"
```

## Naming Conventions

### Movies

```
Movies/
  Movie Name (Year)/
    Movie Name (Year).mkv
```

### TV Shows

```
TV Shows/
  Show Name (Year)/
    Season 01/
      Show Name (Year) - S01E01 - Episode Title.mkv
      Show Name (Year) - S01E02 - Episode Title.mkv
    Season 02/
      ...
```

### Music

```
Music/
  Artist Name/
    Album Name (Year)/
      01 - Track Title.mp3
      02 - Track Title.mp3
```

## License

MIT License - see [LICENSE](LICENSE) file.
