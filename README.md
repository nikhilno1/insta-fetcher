# Instagram Reel Data Extractor

This application extracts data from Instagram Reels, including the audio and its transcription using OpenAI's Whisper model.

## Features

- Automated browser interaction using Playwright
- Downloads reel videos and extracts audio
- Transcribes audio using OpenAI Whisper
- Saves data in JSON format with timestamps
- Configurable number of reels to process
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
- `WHISPER_MODEL`: Whisper model size to use (default: 'base')
  - Options: tiny, base, small, medium, large
- `BROWSER_HEADLESS`: Run browser in headless mode (default: false)
- `BROWSER_SLOWMO`: Milliseconds to wait between actions (default: 0)
- `OUTPUT_DIR`: Directory to store output files (default: output)

## Usage

Run the script with a starting Instagram Reel URL:

```bash
python instagram_reel_extractor.py <reel-url> --num-reels <number-of-reels>
```

Example:
```bash
python instagram_reel_extractor.py "https://www.instagram.com/reels/xyz123" --num-reels 5
```

The script will:
1. Open the specified reel in a browser
2. Wait for the reel to finish playing
3. Download the video and extract audio
4. Transcribe the audio using Whisper
5. Save the data to a JSON file in the `output` directory
6. Scroll to the next reel and repeat the process

## Output

The script creates JSON files in the `output` directory with the following format:
```json
{
    "reel_id": "xyz123",
    "url": "https://www.instagram.com/reels/xyz123",
    "timestamp": "2024-03-14T12:34:56.789",
    "transcription": "Transcribed text from the reel audio"
}
```

## Error Handling

If an error occurs during processing, the JSON file will include an error field:
```json
{
    "reel_id": "xyz123",
    "url": "https://www.instagram.com/reels/xyz123",
    "timestamp": "2024-03-14T12:34:56.789",
    "transcription": "",
    "error": "Error message"
}
```

## Notes

- The browser will run in non-headless mode to ensure proper reel playback
- Make sure you have a stable internet connection
- Instagram may require login for some reels
- Processing time depends on the length of reels and your system's capabilities
