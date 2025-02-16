import os
from pathlib import Path
import subprocess
import tempfile
from typing import Tuple
from pydub import AudioSegment

def download_video(video_url: str, output_dir: Path) -> Tuple[Path, str]:
    """
    Download video from the given URL and return the path to the downloaded file
    and the video ID.
    """
    # Create a temporary directory for downloads
    temp_dir = Path(tempfile.mkdtemp())
    
    # Use yt-dlp to download the video
    video_path = temp_dir / "video.mp4"
    command = [
        "yt-dlp",
        "-f", "best",
        "-o", str(video_path),
        video_url
    ]
    
    try:
        subprocess.run(command, check=True, capture_output=True)
        return video_path, os.path.splitext(os.path.basename(video_url))[0]
    except subprocess.CalledProcessError as e:
        print(f"Error downloading video: {e.stderr.decode()}")
        raise

def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """
    Extract audio from the video file and return the path to the audio file.
    """
    audio_path = output_dir / f"{video_path.stem}.mp3"
    
    # First extract audio using ffmpeg
    command = [
        "ffmpeg",
        "-i", str(video_path),
        "-q:a", "0",
        "-map", "a",
        str(audio_path)
    ]
    
    try:
        subprocess.run(command, check=True, capture_output=True)
        
        # Reduce bitrate for OpenAI API compatibility
        audio = AudioSegment.from_file(str(audio_path))
        reduced_audio_path = output_dir / f"{video_path.stem}_reduced.mp3"
        audio.export(str(reduced_audio_path), bitrate='128k', format='mp3')
        
        # Remove original audio file
        audio_path.unlink()
        
        return reduced_audio_path
    except subprocess.CalledProcessError as e:
        print(f"Error extracting audio: {e.stderr.decode()}")
        raise

def cleanup_temp_files(file_path: Path) -> None:
    """Clean up temporary media files but preserve the output directory."""
    try:
        if file_path.exists():
            file_path.unlink()  # Only delete the specific file
    except Exception as e:
        print(f"Error cleaning up file {file_path}: {str(e)}") 