import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import random
import re

import openai
from playwright.sync_api import sync_playwright, Page, Browser
from dotenv import load_dotenv
import httpx
import brotli

from media_utils import download_video, extract_audio, cleanup_temp_files
from keywords import get_default_keywords

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

    def __init__(self, start_input: str, num_reels: int, output_dir: Path, is_search: bool = False):
        """Initialize the Instagram reel extractor."""
        self.start_input = start_input
        self.is_search = is_search
        self.num_reels = num_reels
        self.output_dir = output_dir
        self.browser = None
        self.page = None
        
        # Only enable keyword checking if we're not in search mode
        self.enable_keyword_check = (not is_search) and os.getenv('ENABLE_KEYWORD_CHECK', 'false').lower() == 'true'
        
        if self.enable_keyword_check:
            # Always use default keywords from the shared module
            self.keywords = get_default_keywords()
            
            # Optionally override with env vars if OVERRIDE_DEFAULT_KEYWORDS is set
            if os.getenv('OVERRIDE_DEFAULT_KEYWORDS', 'false').lower() == 'true':
                keywords_str = os.getenv('INSTAGRAM_KEYWORDS', '').strip()
                if keywords_str:
                    self.keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
                    print("Using custom keywords from environment variables")
            
            print(f"Filtering reels for keywords: {self.keywords}")
        else:
            self.keywords = []
            if is_search:
                print("Keyword filtering disabled (using search mode)")
            else:
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

    def check_keywords(self, text: str, source: str) -> bool:
        """Check if any keywords are present in the text."""
        if not self.enable_keyword_check or not self.keywords:
            return True
            
        if not text:
            return False
            
        text_lower = text.lower()
        found_keywords = [k for k in self.keywords if k.lower() in text_lower]
        if found_keywords:
            print(f"Found keywords in {source}: {found_keywords}")
            return True
        return False

    def extract_reel_data(self, reel_url: str) -> Dict:
        """Extract data from a single reel."""
        original_url = reel_url
        original_reel_id = original_url.split('/')[-2]
        caption = ""
        
        try:
            # Navigate to the reel with longer timeout
            print(f"Navigating to reel: {original_url}")
            self.page.goto(original_url, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            
            # Get the current URL and log if there's a redirect
            current_url = self.page.url
            current_reel_id = current_url.split('/')[-2]
            
            if current_reel_id != original_reel_id:
                print(f"Note: Instagram redirected from reel {original_reel_id} to {current_reel_id}")
            
            # Wait for the page content to load
            self.page.wait_for_selector('video', timeout=45000)
            time.sleep(1)  # Short pause to ensure page is stable
            
            # Try to get the caption using multiple methods
            try:
                # Try API methods first
                api_data = self.get_reel_caption(current_url)
                if api_data and api_data.get('caption'):
                    caption = api_data['caption']
                
                # If API methods fail, try page scraping
                if not caption:
                    # Try multiple selector patterns that Instagram uses
                    selectors = [
                        'span[class*="caption"]',
                        'span[class*="Caption"]',
                        'div[class*="caption"]',
                        'div[class*="Caption"]'
                    ]
                    
                    for selector in selectors:
                        try:
                            caption_element = self.page.locator(selector).first
                            if caption_element:
                                caption = caption_element.inner_text()
                                if caption:
                                    break
                        except Exception:
                            continue
                
                if caption:
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Successfully fetched caption")
                    print(f"Caption: {caption}\n")
                else:
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Warning: Could not find caption\n")
                    
            except Exception as e:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Warning: Error fetching caption: {str(e)}")
            
            # Download video and extract audio
            video_path, _ = download_video(current_url, self.output_dir)
            audio_path = extract_audio(video_path, self.output_dir)
            
            # Get transcription
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
            
            # Check keywords in caption first
            if caption and not self.check_keywords(caption, "caption"):
                if not transcription or not self.check_keywords(transcription, "transcription"):
                    raise KeywordNotFoundError(f"Reel does not contain any specified keywords (checked caption and transcription)")
            
            return {
                "reel_id": current_reel_id,
                "original_url": original_url,
                "final_url": current_url,
                "timestamp": datetime.now().isoformat(),
                "transcription": transcription,
                "caption": caption,
            }
            
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel {original_url}: {str(e)}")
            return {
                "reel_id": current_reel_id if 'current_reel_id' in locals() else original_reel_id,
                "original_url": original_url,
                "final_url": current_url if 'current_url' in locals() else original_url,
                "timestamp": datetime.now().isoformat(),
                "transcription": transcription if 'transcription' in locals() else "",
                "caption": caption,
                "error": str(e)
            }

    def get_reel_caption(self, reel_url: str) -> Dict:
        """Get reel caption using Instagram's API."""
        client = httpx.Client(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",  # Explicitly handle compression
                "Referer": "https://www.instagram.com/",
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
                "X-ASBD-ID": "198387",
                "Cookie": f"sessionid={os.getenv('INSTAGRAM_SESSION_ID')}",
            },
            timeout=30.0,
            follow_redirects=True
        )

        try:
            # First get the media ID from the page
            media_id = self.get_media_id(reel_url)
            if not media_id:
                print("Could not find media ID")
                return {"caption": ""}

            # Try different API endpoints
            endpoints = [
                f"https://www.instagram.com/api/v1/media/{media_id}/info/",
                f"https://i.instagram.com/api/v1/media/{media_id}/info/"
            ]

            for api_url in endpoints:
                try:
                    print(f"Trying API endpoint: {api_url}")
                    response = client.get(api_url)
                    print(f"Response Status: {response.status_code}")

                    if response.status_code == 200:
                        # Handle potential compression
                        content_encoding = response.headers.get('content-encoding', '').lower()
                        if content_encoding == 'br':
                            decompressed = brotli.decompress(response.content)
                            data = json.loads(decompressed)
                        else:
                            data = response.json()
                        
                        if 'items' in data and data['items']:
                            caption_data = data['items'][0].get('caption', {})
                            if isinstance(caption_data, dict):
                                return {"caption": caption_data.get('text', '')}
                            return {"caption": caption_data or ''}
                except Exception as e:
                    print(f"Error with endpoint {api_url}: {str(e)}")
                    continue

            return {"caption": ""}
            
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error fetching caption: {str(e)}")
            return {"caption": ""}

    def get_media_id(self, reel_url: str) -> Optional[str]:
        """Get the internal media ID from the page source."""
        try:
            # Look for the media ID in the page source
            page_content = self.page.content()
            
            patterns = [
                r'"media_id":"(\d+)"',
                r'instagram://media\?id=(\d+)',
                r'"id":"(\d+)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, page_content)
                if match:
                    media_id = match.group(1)
                    print(f"Found media ID: {media_id}")
                    return media_id
            
            return None
        except Exception as e:
            print(f"Error getting media ID: {str(e)}")
            return None

    def scroll_to_next_reel(self) -> str:
        """Smooth scroll to next reel."""
        time.sleep(random.uniform(0.5, 1))
        
        # Store current URL before scrolling
        current_url = self.page.url
        current_reel_id = current_url.split('/')[-2]
        
        # Press Down Arrow to move to next reel
        self.page.keyboard.press('ArrowDown')
        
        # Wait for URL to change and stabilize
        time.sleep(2)
        
        # Get the new URL after scrolling
        new_url = self.page.url
        new_reel_id = new_url.split('/')[-2]
        
        # Make sure we actually moved to a different reel
        max_attempts = 3
        attempts = 0
        while new_reel_id == current_reel_id and attempts < max_attempts:
            print(f"Reel didn't change, trying scroll again...")
            self.page.keyboard.press('ArrowDown')
            time.sleep(2)
            new_url = self.page.url
            new_reel_id = new_url.split('/')[-2]
            attempts += 1
        
        if new_reel_id == current_reel_id:
            raise ValueError(f"Failed to scroll to new reel after {max_attempts} attempts")
        
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

    def search_reels(self) -> str:
        """Search for reels using the given keyword and return the first reel URL."""
        print(f"Searching for reels with keyword: {self.start_input}")
        
        # Navigate to Instagram search page
        search_url = f"https://www.instagram.com/explore/tags/{self.start_input}/"
        self.page.goto(search_url, wait_until="networkidle")
        time.sleep(random.uniform(2, 3))

        try:
            # Look for the Reels tab and click it
            reels_tab = self.page.get_by_text("Reels")
            reels_tab.click()
            time.sleep(random.uniform(1, 2))

            # Find the first reel link
            reel_link = self.page.locator('a[href*="/reel/"]').first
            if not reel_link:
                raise ValueError("No reels found for the given keyword")

            reel_url = reel_link.get_attribute('href')
            if not reel_url.startswith('http'):
                reel_url = f"https://www.instagram.com{reel_url}"

            print(f"Found first reel: {reel_url}")
            return reel_url

        except Exception as e:
            print(f"Error during search: {str(e)}")
            raise

    def process_reels(self) -> None:
        """Process reels with natural behavior."""
        try:
            self.setup_browser()
            self.login_to_instagram()
            time.sleep(0.5)

            if self.is_search:
                # Search mode: Get the starting URL from search
                start_url = self.search_reels()
                self.page.goto(start_url, wait_until="networkidle")
                current_url = self.page.url
                processed_count = 0
                skipped_count = 0

                # Process reels similar to single URL mode
                while processed_count < self.num_reels:
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {processed_count + 1}/{self.num_reels}")
                    
                    if processed_count > 0:
                        time.sleep(0.5)
                    
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
                    
                    time.sleep(0.3)
                    current_url = self.scroll_to_next_reel()

            elif self.start_input.endswith('.txt'):
                # File mode processing
                with open(self.start_input, 'r') as f:
                    urls = [line.strip() for line in f if line.strip()]
                total_urls = len(urls)
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Found {total_urls} URLs in file")
                
                processed_count = 0
                skipped_count = 0
                
                for idx, url in enumerate(urls, 1):  # Changed to enumerate starting from 1
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {idx}/{total_urls}")
                    
                    if idx > 1:  # Changed from processed_count to idx
                        time.sleep(0.5)
                    
                    reel_id = url.split('/')[-2]
                    output_file = self.output_dir / f"{reel_id}.json"
                    
                    if output_file.exists():
                        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Reel {reel_id} already exists in {output_file}, skipping.")
                        skipped_count += 1
                        processed_count += 1
                    else:
                        try:
                            reel_data = self.extract_reel_data(url)
                            with open(output_file, 'w') as f:
                                json.dump(reel_data, f, indent=4)
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Saved new reel data to {output_file}")
                            processed_count += 1
                        except Exception as e:
                            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel {reel_id}: {str(e)}")
            
            else:
                # Single URL mode processing
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting to process {self.num_reels} reels")
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Navigating to starting reel: {self.start_input}")
                
                self.page.goto(self.start_input, wait_until="networkidle")
                time.sleep(0.5)
                
                current_url = self.page.url
                processed_count = 0
                skipped_count = 0
                
                while processed_count < self.num_reels:
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {processed_count + 1}/{self.num_reels}")
                    
                    if processed_count > 0:
                        time.sleep(0.5)
                    
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
                    
                    time.sleep(0.3)
                    current_url = self.scroll_to_next_reel()
        
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel: {str(e)}")
        
        finally:
            if self.browser:
                time.sleep(0.5)
                self.browser.close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract and transcribe Instagram Reels')
    
    # Create a mutually exclusive group for input type
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--url', help='Starting Instagram Reel URL or text file containing reel URLs')
    input_group.add_argument('--search', help='Keyword to search for reels')
    
    parser.add_argument('--num-reels', type=int, default=5, 
                      help='Number of reels to process')
    
    args = parser.parse_args()
    
    start_input = args.search if args.search else args.url
    is_search = bool(args.search)
    
    extractor = InstagramReelExtractor(
        start_input,
        args.num_reels,
        Path(os.getenv('OUTPUT_DIR', 'output')),
        is_search=is_search
    )
    extractor.process_reels()

if __name__ == "__main__":
    main() 