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

# Custom exception class - moved to top
class KeywordNotFoundError(Exception):
    """Raised when a reel doesn't contain any of the specified keywords."""
    pass

# Load environment variables from .env file
load_dotenv(dotenv_path=".env")  # Explicitly specify the .env file

# Setup OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("OPENAI_API_KEY not found in .env file")

class InstagramReelExtractor:
    # Single Chrome Windows user agent
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

    def __init__(self, start_url: str, num_reels: int, output_dir: Path):
        """Initialize the Instagram reel extractor."""
        self.start_url = start_url
        self.num_reels = num_reels
        self.output_dir = output_dir
        self.browser = None
        self.page = None
        
        # Get keywords from env file if keyword checking is enabled
        self.enable_keyword_check = os.getenv('ENABLE_KEYWORD_CHECK', 'false').lower() == 'true'
        if self.enable_keyword_check:
            keywords_str = os.getenv('INSTAGRAM_KEYWORDS', '').strip()
            self.keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
            if self.keywords:
                print(f"Filtering reels for keywords: {self.keywords}")
        else:
            self.keywords = []
            print("Keyword checking is disabled")

    def setup_browser(self) -> None:
        """Initialize browser with randomized properties and persistent profile."""
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
                context = self.browser.new_context(
                    viewport=viewport,
                    user_agent=self.USER_AGENT,
                    locale='en-US',
                    timezone_id='America/New_York',
                    geolocation={'latitude': 40.7128, 'longitude': -74.0060},
                    permissions=['geolocation']
                )
            except Exception as e:
                print(f"Connection error: {e}")
                raise
        else:
            # Create user data directory if it doesn't exist
            user_data_dir = Path('browser_profile').absolute()
            user_data_dir.mkdir(exist_ok=True)
            
            # Use launch_persistent_context instead of launch
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=os.getenv('BROWSER_HEADLESS', 'false').lower() == 'true',
                slow_mo=int(os.getenv('BROWSER_SLOWMO', '0')),
                viewport=viewport,
                user_agent=self.USER_AGENT,
                locale='en-US',
                timezone_id='America/New_York',
                geolocation={'latitude': 40.7128, 'longitude': -74.0060},
                permissions=['geolocation']
            )
            self.browser = context.browser
        
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
            watch_time = random.uniform(3, 5)  # Reduced from 8-15s to 3-5s
            time.sleep(watch_time)
            
        except Exception as e:
            # Just log and continue, since we already have the video URL
            print(f"Note: Video element interaction skipped - {str(e)}")
            time.sleep(random.uniform(1, 2))

    def extract_reel_data(self, reel_url: str) -> Dict:
        """Extract data from a single reel."""
        if '/reels/' not in reel_url or reel_url == 'https://www.instagram.com/':
            raise ValueError(f"Invalid reel URL: {reel_url}")
        
        self.page.goto(reel_url, wait_until="networkidle")
        time.sleep(1)  # Reduced from 2s
        
        current_url = self.page.url
        if '/reels/' not in current_url:
            raise ValueError(f"Failed to load reel: {current_url}")
        
        # Extract text content
        text_content = ''
        try:
            # Updated selectors specifically for reel captions
            selectors = [
                'div._a9zs',
                'div._a9zr div._a9zs',
                'div._a9zr ._a9zs',
                'div[class*="_a9zs"]',
                'div._aacl._aaco._aacu._aacx._aad7._aade',
                'div[data-e2e="post-caption"]',
                'h1._aacl._aaco._aacu._aacx._aad7._aade',
                'div._ae5q._ae5r._ae5s'
            ]
            
            for selector in selectors:
                elements = self.page.locator(selector).all()
                if elements:
                    texts = [elem.inner_text() for elem in elements if elem.is_visible()]
                    if texts:
                        text_content = ' '.join(texts)
                        break
        
            # Try XPath if no text found
            if not text_content:
                xpath_selectors = [
                    '//div[contains(@class, "_a9zs")]//span[string-length(text()) > 0]',
                    '//div[contains(@class, "_a9zr")]//div[contains(@class, "_a9zs")]//span',
                    '//article//div[contains(@class, "_a9zs")]'
                ]
                
                for xpath in xpath_selectors:
                    elements = self.page.locator(xpath).all()
                    if elements:
                        texts = [elem.inner_text() for elem in elements if elem.is_visible()]
                        if texts:
                            text_content = ' '.join(texts)
                            break
                        
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Warning: Could not extract text content: {str(e)}")
        
        # Only check keywords if enabled
        if self.enable_keyword_check and self.keywords:
            text_lower = text_content.lower()
            if not any(keyword in text_lower for keyword in self.keywords):
                raise KeywordNotFoundError("Reel does not contain any specified keywords")
        
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
            
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Transcription: {transcription}\n")
            
            # Clean up temporary files
            cleanup_temp_files(video_path)
            cleanup_temp_files(audio_path)
            
            return {
                "reel_id": reel_id,
                "url": current_url,
                "timestamp": timestamp,
                "transcription": transcription,
                "text_content": text_content,
            }
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel {current_url}: {str(e)}")
            return {
                "reel_id": reel_id,
                "url": current_url,
                "timestamp": timestamp,
                "transcription": "",
                "text_content": text_content,
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
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Warning: Invalid reel URL detected after scroll")
            # Try to find a reel link on the page
            reel_link = self.page.locator('a[href*="/reels/"]').first
            if reel_link:
                new_url = reel_link.get_attribute('href')
                if not new_url.startswith('http'):
                    new_url = f"https://www.instagram.com{new_url}"
        
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Scrolled to new reel: {new_url}")
        return new_url

    def login_to_instagram(self) -> None:
        """Login to Instagram with credentials from env."""
        try:
            print("Checking login status...")
            # Go to Instagram homepage
            self.page.goto('https://www.instagram.com/', timeout=60000)
            time.sleep(random.uniform(1, 2))
            
            # Check if we're already logged in by looking for typical logged-in elements
            try:
                # Look for elements that indicate we're logged in
                is_logged_in = (
                    not self.page.get_by_text('Log in').is_visible() and 
                    not 'accounts/login' in self.page.url
                )
                
                if is_logged_in:
                    print("Already logged in to Instagram")
                    return
            except Exception:
                pass
            
            # If we reach here, we need to log in
            print("Not logged in. Starting login process...")
            username = os.getenv('INSTAGRAM_USERNAME')
            password = os.getenv('INSTAGRAM_PASSWORD')
            
            if not username or not password:
                raise ValueError("Instagram credentials not found in .env file")
            
            # Go to login page
            self.page.goto('https://www.instagram.com/accounts/login/', timeout=60000)
            time.sleep(random.uniform(1, 2))
            
            print("Waiting for login form...")
            self.page.wait_for_selector('input[name="username"]', timeout=60000)
            
            # Fill in username
            print("Filling username...")
            self.page.fill('input[name="username"]', username)
            time.sleep(random.uniform(0.3, 0.7))
            
            # Fill in password
            print("Filling password...")
            self.page.fill('input[name="password"]', password)
            time.sleep(random.uniform(0.3, 0.7))
            
            # Click login button
            print("Clicking login button...")
            self.page.click('button[type="submit"]')
            
            # Wait for navigation and login to complete
            print("Waiting for login to complete...")
            self.page.wait_for_load_state('networkidle', timeout=60000)
            time.sleep(random.uniform(2, 3))
            
            # Handle "Save Login Info" popup if it appears
            try:
                print("Checking for 'Save Login Info' popup...")
                save_info_button = self.page.get_by_text('Not Now', timeout=10000)
                if save_info_button:
                    save_info_button.click()
                    time.sleep(random.uniform(0.5, 1))
            except Exception:
                print("No 'Save Login Info' popup found")
                pass
            
            # Handle "Turn on Notifications" popup if it appears
            try:
                print("Checking for notifications popup...")
                notif_button = self.page.get_by_text('Not Now', timeout=10000)
                if notif_button:
                    notif_button.click()
                    time.sleep(random.uniform(0.5, 1))
            except Exception:
                print("No notifications popup found")
                pass
            
            print("Successfully logged into Instagram")
            time.sleep(random.uniform(1, 2))
            
        except Exception as e:
            print(f"Login error: {str(e)}")
            print("Current URL:", self.page.url)
            print("Taking screenshot of error state...")
            self.page.screenshot(path="login_error.png")
            raise

    def process_reels(self) -> None:
        """Process reels with natural behavior."""
        try:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting to process {self.num_reels} reels")
            self.setup_browser()
            
            self.login_to_instagram()
            time.sleep(0.5)  # Reduced from 1-2s
            
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Navigating to starting reel: {self.start_url}")
            self.page.goto(self.start_url, wait_until="networkidle")
            time.sleep(0.5)  # Reduced from 1s
            
            current_url = self.page.url
            processed_count = 0
            skipped_count = 0
            
            while processed_count < self.num_reels:
                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {processed_count + 1}/{self.num_reels}")
                
                if processed_count > 0:
                    time.sleep(0.5)  # Reduced from 1-2s
                
                reel_id = current_url.split('/')[-2]
                output_file = self.output_dir / f"{reel_id}.json"
                
                if output_file.exists():
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Reel {reel_id} already exists in {output_file}, skipping.")
                    skipped_count += 1
                    processed_count += 1
                else:
                    try:
                        reel_data = self.extract_reel_data(current_url)
                        with open(output_file, 'w') as f:
                            json.dump(reel_data, f, indent=4)
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Saved new reel data to {output_file}")
                        processed_count += 1
                    except Exception as e:
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel {reel_id}: {str(e)}")
                
                if processed_count >= self.num_reels:
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Completed processing {self.num_reels} reels")
                    print(f"New reels: {processed_count - skipped_count}")
                    print(f"Skipped reels: {skipped_count}")
                    break
                
                time.sleep(0.3)  # Reduced from 0.5s
                current_url = self.scroll_to_next_reel()
        
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel: {str(e)}")
        
        finally:
            if self.browser:
                time.sleep(0.5)  # Reduced from 1s
                self.browser.close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract and transcribe Instagram Reels')
    parser.add_argument('start_url', help='Starting Instagram Reel URL')
    parser.add_argument('--num-reels', type=int, default=5, help='Number of reels to process')
    
    args = parser.parse_args()
    
    extractor = InstagramReelExtractor(args.start_url, args.num_reels, Path(os.getenv('OUTPUT_DIR', 'output')))
    extractor.process_reels()

if __name__ == "__main__":
    main() 