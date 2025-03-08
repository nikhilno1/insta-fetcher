# Instagram Reel Data Extractor

This application extracts data from Instagram Reels, including the audio and its transcription using OpenAI's Whisper model. It supports both direct URL processing and keyword-based search using Google.

## Features

- Multiple input methods:
  - Direct Instagram Reel URLs
  - Keyword-based search via Google
  - Batch processing from text file
- Advanced search filters:
  - Time range filtering
  - Minimum video length
  - Exact phrase matching
  - Term exclusion
  - Safe search options
- Automated browser interaction using Playwright
- Downloads reel videos and extracts audio
- Transcribes audio using OpenAI Whisper
- Saves data in JSON format with timestamps
- Optional Instagram login for private reels

## Prerequisites

- Python 3.8 or higher
- FFmpeg (for audio extraction)
- yt-dlp (for video downloading)

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd instagram-reel-extractor
```

2. Install the required Python packages:
```bash
pip install -r requirements.txt
```

3. Install system dependencies:

For Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
pip install yt-dlp
```

For macOS:
```bash
brew install ffmpeg
pip install yt-dlp
```

4. Install Playwright browsers:
```bash
playwright install
```

5. Configure environment variables:
   - Copy `.env.example` to `.env`
   - Edit `.env` with your settings
```bash
cp .env.example .env
```

## Environment Variables

The following environment variables can be configured in your `.env` file:

- `INSTAGRAM_USERNAME`: Your Instagram username (optional)
- `INSTAGRAM_PASSWORD`: Your Instagram password (optional)
- `INSTAGRAM_SESSION_ID`: Your Instagram session ID (required)
- `OPENAI_API_KEY`: Your OpenAI API key (required for transcription)
- `WHISPER_MODEL`: Whisper model size to use (default: 'base')
- `BROWSER_HEADLESS`: Run browser in headless mode (default: false)
- `BROWSER_SLOWMO`: Milliseconds to wait between actions (default: 0)
- `OUTPUT_DIR`: Directory to store output files (default: output)
- `ENABLE_KEYWORD_CHECK`: Enable keyword filtering (default: false)
- `OVERRIDE_DEFAULT_KEYWORDS`: Use custom keywords instead of defaults (default: false)
- `INSTAGRAM_KEYWORDS`: Comma-separated custom keywords (when override is enabled)

## Usage

### Direct URL Mode

Process a single reel or multiple reels starting from a URL:

```bash
python instagram_reel_extractor.py --url "https://www.instagram.com/reels/xyz123" --num-reels 5
```

### Search Mode

Search for reels using keywords with various filters:

```bash
# Basic search
python instagram_reel_extractor.py --search "japan travel" --num-reels 10

# Search with time range filter
python instagram_reel_extractor.py --search "japan travel" --time-range w --num-reels 10

# Search for longer reels with exact phrase
python instagram_reel_extractor.py --search "tokyo street food" --min-length 2 --exact-match --num-reels 5

# Search with excluded terms
python instagram_reel_extractor.py --search "kyoto temples" --exclude "tourist,crowds" --num-reels 10

# Combined filters
python instagram_reel_extractor.py --search "japanese culture" \
    --time-range m \
    --min-length 3 \
    --exact-match \
    --exclude "anime,manga" \
    --num-reels 15
```

### Search Filters

- `--time-range`: Filter results by time
  - `h`: Last hour
  - `d`: Last 24 hours
  - `w`: Last week
  - `m`: Last month
  - `y`: Last year

- `--min-length`: Minimum video length in minutes
- `--exact-match`: Use exact phrase matching
- `--exclude`: Comma-separated terms to exclude
- `--safe-search`: Safe search level (off/moderate/strict)

### Batch Processing

Process multiple reels from a text file:

```bash
python instagram_reel_extractor.py --url "urls.txt" --num-reels 10
```

The text file should contain one reel URL per line.

## Output

The script creates JSON files in the `output` directory with the following format:
```json
{
    "reel_id": "xyz123",
    "original_url": "https://www.instagram.com/reels/xyz123",
    "final_url": "https://www.instagram.com/reels/xyz123",
    "timestamp": "2024-03-14T12:34:56.789",
    "transcription": "Transcribed text from the reel audio",
    "caption": "Original reel caption"
}
```

## Error Handling

If an error occurs during processing, the JSON file will include an error field:
```json
{
    "reel_id": "xyz123",
    "original_url": "https://www.instagram.com/reels/xyz123",
    "final_url": "https://www.instagram.com/reels/xyz123",
    "timestamp": "2024-03-14T12:34:56.789",
    "transcription": "",
    "caption": "",
    "error": "Error message"
}
```

## Notes

- The browser will run in non-headless mode to ensure proper reel playback
- Google search results may be rate-limited; the script includes automatic delays
- Instagram may require login for some reels
- Processing time depends on the length of reels and your system's capabilities
- Some reels may redirect to different URLs; the script handles this automatically
