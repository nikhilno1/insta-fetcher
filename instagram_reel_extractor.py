import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import random

import openai
from playwright.sync_api import sync_playwright, Page, Browser
from dotenv import load_dotenv

from media_utils import download_video, extract_audio, cleanup_temp_files

# Load environment variables from .env file
load_dotenv(dotenv_path=".env")  # Explicitly specify the .env file

# Setup OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY not found in .env file")

class InstagramReelExtractor:
    # Single Chrome Windows user agent
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

    def __init__(self, start_url: str, num_reels: int):
        self.start_url = start_url
        self.num_reels = num_reels
        self.output_dir = Path(os.getenv('OUTPUT_DIR', 'output'))
        self.output_dir.mkdir(exist_ok=True)
        self.browser = None
        self.page = None

    def setup_browser(self) -> None:
        """Initialize browser with randomized properties."""
        playwright = sync_playwright().start()
        
        # Random viewport size (common resolutions)
        viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1440, "height": 900},
            {"width": 1536, "height": 864}
        ]
        viewport = random.choice(viewports)
        
        use_existing_browser = os.getenv('USE_EXISTING_BROWSER', 'false').lower() == 'true'
        
        if use_existing_browser:
            windows_host = os.getenv('WINDOWS_HOST', '172.17.0.1')
            try:
                self.browser = playwright.chromium.connect_over_cdp(f'http://{windows_host}:9222')
            except Exception as e:
                print(f"Connection error: {e}")
                raise
        else:
            self.browser = playwright.chromium.launch(
                headless=os.getenv('BROWSER_HEADLESS', 'false').lower() == 'true',
                slow_mo=int(os.getenv('BROWSER_SLOWMO', '0')),
                args=['--disable-blink-features=AutomationControlled']
            )
        
        context = self.browser.new_context(
            viewport=viewport,
            user_agent=self.USER_AGENT
        )
        
        self.page = context.new_page()

    def random_mouse_movement(self) -> None:
        """Simulate natural mouse movements."""
        try:
            x = random.randint(100, 1000)
            y = random.randint(100, 700)
            self.page.mouse.move(x, y, steps=random.randint(5, 10))
        except Exception:
            pass

    def wait_for_reel_playback(self) -> None:
        """Wait for reel playback with natural behavior.
        Note: This is just for UI interaction simulation.
        The actual video download and transcription happens separately."""
        time.sleep(random.uniform(1, 2))  # Initial page load wait
        
        try:
            # Wait up to 5 seconds to find the video player element
            video = self.page.locator('video:visible').first
            video.wait_for(timeout=5000)  # This is just for finding the element
            
            # Natural mouse movement to video
            video_box = video.bounding_box()
            if video_box:
                self.page.mouse.move(
                    video_box['x'] + random.randint(10, int(video_box['width']-10)),
                    video_box['y'] + random.randint(10, int(video_box['height']-10)),
                    steps=random.randint(5, 10)
                )
            
            # This wait time is just for appearance - it doesn't affect the download
            watch_time = random.uniform(8, 15)  # Simulated watching time
            time.sleep(watch_time)
            
        except Exception as e:
            # Just log and continue, since we already have the video URL
            print(f"Note: Video element interaction skipped - {str(e)}")
            time.sleep(random.uniform(3, 5))

    def extract_reel_data(self, reel_url: str) -> Dict:
        """Extract data from a single reel."""
        # Ensure we have a valid reel URL
        if '/reels/' not in reel_url or reel_url == 'https://www.instagram.com/':
            raise ValueError(f"Invalid reel URL: {reel_url}")
        
        # Navigate and wait for page to stabilize
        self.page.goto(reel_url, wait_until="networkidle")
        time.sleep(2)
        
        # Get current URL after potential redirects
        current_url = self.page.url
        if '/reels/' not in current_url:
            raise ValueError(f"Failed to load reel: {current_url}")
        
        # Wait for the video element to be present and visible
        self.page.wait_for_selector('video:visible', timeout=10000)
        
        # Get reel metadata
        reel_id = current_url.split('/')[-2]
        timestamp = datetime.now().isoformat()
        
        # Wait for the reel to finish playing
        self.wait_for_reel_playback()
        
        try:
            # Download video and extract audio
            video_path, _ = download_video(current_url, self.output_dir)
            audio_path = extract_audio(video_path, self.output_dir)
            
            # Updated OpenAI API call for v1.0+
            client = openai.OpenAI()
            with open(str(audio_path), "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en"
                ).text
            
            # Clean up temporary files
            cleanup_temp_files(video_path)
            cleanup_temp_files(audio_path)
            
            return {
                "reel_id": reel_id,
                "url": current_url,
                "timestamp": timestamp,
                "transcription": transcription,
            }
        except Exception as e:
            print(f"Error processing reel {current_url}: {str(e)}")
            return {
                "reel_id": reel_id,
                "url": current_url,
                "timestamp": timestamp,
                "transcription": "",
                "error": str(e)
            }

    def scroll_to_next_reel(self) -> str:
        """Smooth scroll to next reel."""
        time.sleep(random.uniform(0.5, 1))
        
        # Press Down Arrow to move to next reel (more reliable than Space)
        self.page.keyboard.press('ArrowDown')
        
        # Wait for URL to change and stabilize
        time.sleep(2)
        
        # Get the new URL after scrolling
        new_url = self.page.url
        
        # Verify we have a valid reel URL
        if '/reels/' not in new_url or new_url == 'https://www.instagram.com/':
            print("Warning: Invalid reel URL detected after scroll")
            # Try to find a reel link on the page
            reel_link = self.page.locator('a[href*="/reels/"]').first
            if reel_link:
                new_url = reel_link.get_attribute('href')
                if not new_url.startswith('http'):
                    new_url = f"https://www.instagram.com{new_url}"
        
        print(f"Scrolled to new reel: {new_url}")
        return new_url

    def login_to_instagram(self) -> None:
        """Login to Instagram with credentials from env."""
        username = os.getenv('INSTAGRAM_USERNAME')
        password = os.getenv('INSTAGRAM_PASSWORD')
        
        if not username or not password:
            raise ValueError("Instagram credentials not found in .env file")
        
        print("Logging into Instagram...")
        
        try:
            # Go to Instagram login page
            self.page.goto('https://www.instagram.com/accounts/login/')
            time.sleep(random.uniform(1, 2))  # Reduced from 2-3s
            
            # Fill in username
            self.page.fill('input[name="username"]', username)
            time.sleep(random.uniform(0.3, 0.7))  # Reduced from 0.5-1s
            
            # Fill in password
            self.page.fill('input[name="password"]', password)
            time.sleep(random.uniform(0.3, 0.7))  # Reduced from 0.5-1s
            
            # Click login button
            self.page.click('button[type="submit"]')
            
            # Wait for navigation and login to complete
            self.page.wait_for_load_state('networkidle')
            time.sleep(random.uniform(2, 3))  # Reduced from 3-5s
            
            # Handle "Save Login Info" popup if it appears
            try:
                save_info_button = self.page.get_by_text('Not Now')
                if save_info_button:
                    save_info_button.click()
                    time.sleep(random.uniform(0.5, 1))  # Reduced from 1-2s
            except Exception:
                pass
            
            # Handle "Turn on Notifications" popup if it appears
            try:
                notif_button = self.page.get_by_text('Not Now')
                if notif_button:
                    notif_button.click()
                    time.sleep(random.uniform(0.5, 1))  # Reduced from 1-2s
            except Exception:
                pass
            
            # Check if login was successful by looking for common elements after login
            if 'login' in self.page.url or self.page.get_by_text('Log in').is_visible():
                raise Exception("Login failed - please check credentials")
            
            print("Successfully logged into Instagram")
            time.sleep(random.uniform(1, 2))  # Reduced from 2-3s
            
        except Exception as e:
            print(f"Login error: {str(e)}")
            raise

    def process_reels(self) -> None:
        """Process reels with natural behavior."""
        try:
            print(f"Starting to process {self.num_reels} reels")
            self.setup_browser()
            
            # Login first
            self.login_to_instagram()
            time.sleep(random.uniform(1, 2))  # Reduced wait time
            
            # Explicitly navigate to the starting reel URL
            print(f"Navigating to starting reel: {self.start_url}")
            self.page.goto(self.start_url, wait_until="networkidle")
            time.sleep(1)  # Reduced wait time
            
            current_url = self.page.url  # Get the current URL after potential redirects
            processed_count = 0
            skipped_count = 0
            
            while processed_count < self.num_reels:
                print(f"\nProcessing reel {processed_count + 1}/{self.num_reels}")
                
                if processed_count > 0:
                    time.sleep(random.uniform(1, 2))  # Reduced wait time
                
                # Extract reel ID from URL before full processing
                reel_id = current_url.split('/')[-2]
                output_file = self.output_dir / f"{reel_id}.json"
                
                if output_file.exists():
                    print(f"\nReel {reel_id} already exists in {output_file}, skipping.")
                    skipped_count += 1
                    processed_count += 1
                    
                    if processed_count >= self.num_reels:
                        break
                        
                    # Move to next reel if this one was skipped
                    current_url = self.scroll_to_next_reel()
                    continue
                
                # Process only if reel hasn't been downloaded before
                reel_data = self.extract_reel_data(current_url)
                with open(output_file, 'w') as f:
                    json.dump(reel_data, f, indent=4)
                print(f"\nSaved new reel data to {output_file}")
                
                processed_count += 1
                
                if processed_count >= self.num_reels:
                    print(f"\nCompleted processing {self.num_reels} reels")
                    print(f"New reels: {processed_count - skipped_count}")
                    print(f"Skipped reels: {skipped_count}")
                    break
                
                time.sleep(0.5)  # Reduced wait time
                current_url = self.scroll_to_next_reel()
        
        except Exception as e:
            print(f"Error processing reel: {str(e)}")
        
        finally:
            if self.browser:
                time.sleep(1)  # Reduced wait time
                self.browser.close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract and transcribe Instagram Reels')
    parser.add_argument('start_url', help='Starting Instagram Reel URL')
    parser.add_argument('--num-reels', type=int, default=5, help='Number of reels to process')
    
    args = parser.parse_args()
    
    extractor = InstagramReelExtractor(args.start_url, args.num_reels)
    extractor.process_reels()

if __name__ == "__main__":
    main() 