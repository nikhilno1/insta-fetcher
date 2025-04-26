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

    def normalize_reel_url(self, url: str) -> str:
        """Normalize any Instagram URL to the /reels/{id}/ format."""
        if not url:
            return url

        # Extract the unique ID after the domain and before the next slash
        match = re.search(r'instagram\.com/[^/]+/([A-Za-z0-9_-]+)', url)
        if match:
            reel_id = match.group(1)
            return f"https://www.instagram.com/reels/{reel_id}/"
        return url

    def extract_reel_data(self, reel_url: str) -> Dict:
        """Extract data from a single reel."""
        original_url = self.normalize_reel_url(reel_url)
        original_reel_id = original_url.split('/')[-2]
        caption = ""
        current_url = original_url  # <-- Initialize here
        current_reel_id = original_reel_id  # <-- Initialize here
        
        try:
            # Navigate to the reel with longer timeout
            print(f"Navigating to reel: {original_url}")
            self.page.goto(original_url, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            
            # Get the current URL and log if there's a redirect
            current_url = self.page.url
            current_reel_id = current_url.split('/')[-2]
            
            # If redirected, try to go back to the intended reel
            if current_reel_id != original_reel_id:
                print(f"Note: Instagram redirected from reel {original_reel_id} to {current_reel_id}")
                print("Attempting to navigate back to the intended reel using ArrowUp...")
                self.page.keyboard.press('ArrowUp')
                time.sleep(2)
                # Check if we are back to the original reel
                back_url = self.page.url
                back_reel_id = back_url.split('/')[-2]
                if back_reel_id == original_reel_id:
                    print(f"Successfully navigated back to the intended reel: {original_reel_id}")
                    current_url = back_url
                    current_reel_id = back_reel_id
                else:
                    print(f"Failed to navigate back to the intended reel. Continuing with redirected reel: {current_reel_id}")
            
            # Wait for the page content to load
            self.page.wait_for_selector('video', timeout=45000)
            time.sleep(1)  # Short pause to ensure page is stable
            
            # Try to get the caption using multiple methods
            try:
                # Try API methods first
                api_data = self.get_reel_caption(current_url)  # Use the redirected URL
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
            
            # Download video and extract audio for the current URL
            video_path, _ = download_video(current_url, self.output_dir)  # Use the redirected URL
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
                    print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Skipping reel {current_url}: No matching keywords found in caption or transcription")
                    return {
                        "reel_id": current_reel_id,
                        "url": current_url,
                        "timestamp": datetime.now().isoformat(),
                        "transcription": transcription,
                        "caption": caption,
                        "skipped": "No matching keywords found"
                    }
            
            return {
                "reel_id": current_reel_id,
                "url": current_url,
                "timestamp": datetime.now().isoformat(),
                "transcription": transcription,
                "caption": caption,
            }
            
        except KeywordNotFoundError as e:
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Skipping reel {current_url}: {str(e)}")
            return {
                "reel_id": current_reel_id,
                "url": current_url,
                "timestamp": datetime.now().isoformat(),
                "transcription": transcription if 'transcription' in locals() else "",
                "caption": caption,
                "skipped": str(e)
            }
        except Exception as e:
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error processing reel {current_url}: {str(e)}")
            return {
                "reel_id": current_reel_id,
                "url": current_url,
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
                # Remove brotli from accepted encodings
                "Accept-Encoding": "gzip, deflate",
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

            # Use only the endpoint that consistently works
            api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"
            
            print(f"Fetching caption from API...")
            response = client.get(api_url)
            
            if response.status_code == 200:
                data = response.json()
                if 'items' in data and data['items']:
                    caption_data = data['items'][0].get('caption', {})
                    if isinstance(caption_data, dict):
                        return {"caption": caption_data.get('text', '')}
                    return {"caption": caption_data or ''}
            
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

    def get_google_search_url(self, keyword: str, start: int = 0, filters: Dict = None) -> str:
        """Generate Google search URL with advanced filters."""
        base_query = f"site:instagram.com/reel {keyword}"
        
        # Apply advanced filters if provided
        if filters:
            if filters.get('time_range'):
                # time_range can be 'h' (hour), 'd' (day), 'w' (week), 'm' (month), 'y' (year)
                base_query += f" &tbs=qdr:{filters['time_range']}"
            
            if filters.get('min_length'):
                # Add duration filter using Google's time notation (e.g., "longer than 2 minutes")
                base_query += f" longer than {filters['min_length']} minutes"
            
            if filters.get('exact_phrase'):
                # Add exact phrase matching
                base_query = base_query.replace(keyword, f'"{keyword}"')
            
            if filters.get('exclude_terms'):
                # Add terms to exclude
                for term in filters['exclude_terms']:
                    base_query += f" -{term}"

        params = {
            "q": base_query,
            "start": start,
            "num": 10,  # Results per page
            "hl": "en",  # Language
            "safe": filters.get('safe_search', 'off')
        }
        
        return "https://www.google.com/search", params

    def search_reels(self) -> str:
        """Search for reels using Google and return the first valid reel URL."""
        try:
            # Parse advanced filters from environment variables or command line arguments
            filters = {
                'time_range': os.getenv('SEARCH_TIME_RANGE', ''),  # e.g., 'h', 'd', 'w', 'm', 'y'
                'min_length': os.getenv('SEARCH_MIN_LENGTH', ''),  # in minutes
                'exact_phrase': os.getenv('SEARCH_EXACT_MATCH', '').lower() == 'true',
                'exclude_terms': os.getenv('SEARCH_EXCLUDE', '').split(',') if os.getenv('SEARCH_EXCLUDE') else [],
                'safe_search': os.getenv('SEARCH_SAFE', 'off')
            }
            
            # Remove empty filters
            filters = {k: v for k, v in filters.items() if v}
            
            if filters:
                print("Applying search filters:", json.dumps(filters, indent=2))
            
            # Create a new browser page specifically for Google search
            print("Creating new page for Google search...")
            search_page = self.page.context.new_page()
            
            try:
                # Get reel URLs from Google search
                reel_urls = self.get_reel_urls_from_google(
                    self.start_input,
                    self.num_reels,
                    filters=filters,
                    search_page=search_page  # Pass the page to the search method
                )
            finally:
                # Clean up the search page
                search_page.close()
            
            if not reel_urls:
                raise ValueError(f"No reels found for keyword: {self.start_input}")
            
            # Store the URLs for later processing
            self.search_results = reel_urls
            print(f"Found {len(reel_urls)} reels to process")
            
            # Return the first URL to start processing
            return reel_urls[0]
            
        except Exception as e:
            print(f"Error during search: {str(e)}")
            raise

    def get_random_user_agent(self) -> str:
        """Return a random user agent from a pool of modern browsers."""
        user_agents = [
            # Chrome Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            # Firefox Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            # Edge Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
            # Safari macOS
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        ]
        return random.choice(user_agents)

    def simulate_human_behavior(self, page: Page) -> None:
        """Simulate human-like behavior on the page."""
        try:
            # Random scroll
            scroll_amount = random.randint(300, 700)
            page.mouse.wheel(0, scroll_amount)
            time.sleep(random.uniform(1, 2))
            
            # Random mouse movements
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                page.mouse.move(x, y, steps=random.randint(5, 10))
                time.sleep(random.uniform(0.5, 1))
            
            # Sometimes move mouse to a link but don't click
            links = page.query_selector_all('a')
            if links:
                random_link = random.choice(links)
                box = random_link.bounding_box()
                if box:
                    page.mouse.move(
                        box['x'] + box['width'] / 2,
                        box['y'] + box['height'] / 2,
                        steps=random.randint(5, 10)
                    )
                    time.sleep(random.uniform(0.5, 1))
        except Exception as e:
            print(f"Error during human behavior simulation: {e}")

    def wait_for_human_verification(self, page: Page) -> bool:
        """Wait for human to solve CAPTCHA."""
        print("\n=== CAPTCHA/Human Verification Detected! ===")
        print("Please solve the verification manually in the browser window.")
        print("Press Enter after you've completed the verification...")
        
        # Wait for user input
        input()
        
        # Check if we can proceed
        try:
            # Try to find common CAPTCHA elements
            captcha_selectors = [
                'iframe[src*="recaptcha"]',
                'iframe[src*="captcha"]',
                '#captcha',
                '.g-recaptcha',
            ]
            
            for selector in captcha_selectors:
                if page.query_selector(selector):
                    print("CAPTCHA still detected. Please complete the verification...")
                    return False
            
            return True
        except Exception:
            return False

    def get_reel_urls_from_google(self, keyword: str, num_results: int = 10, filters: Dict = None, search_page: Page = None) -> List[str]:
        """Get Instagram reel URLs from Google search results with pagination."""
        print(f"Searching Google for Instagram reels about: {keyword}")
        
        if not search_page:
            raise ValueError("Search page is required")
        
        reel_urls = []
        start_index = 0
        max_pages = (num_results + 9) // 10
        consecutive_empty_results = 0
        
        try:
            while len(reel_urls) < num_results:  # Keep going until we have enough reels
                # Update user agent for each page
                search_page.set_extra_http_headers({
                    'User-Agent': self.get_random_user_agent(),
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                })
                
                # Construct the Google search URL
                search_url = f"https://www.google.com/search?q=site:instagram.com/reel+{keyword}&start={start_index}&num=10&hl=en"
                if filters:
                    if filters.get('time_range'):
                        search_url += f"&tbs=qdr:{filters['time_range']}"
                
                print(f"\nFetching results page {(start_index // 10) + 1}...")
                print(f"Search URL: {search_url}")
                
                # Navigate to the search URL
                search_page.goto(search_url, wait_until="networkidle")
                time.sleep(2)  # Short wait for page stability
                
                # Check for CAPTCHA/verification
                if any(text in search_page.content().lower() 
                      for text in ['captcha', 'unusual traffic', 'verify you\'re a human']):
                    print("\nDetected potential CAPTCHA or verification...")
                    while not self.wait_for_human_verification(search_page):
                        print("Verification not completed. Please try again...")
                        time.sleep(2)
                    print("Verification completed! Continuing with search...")
                
                # Extract reel links
                new_links = search_page.query_selector_all('a[href*="instagram.com/reel"]')
                page_urls = []
                
                for link in new_links:
                    url = link.get_attribute('href')
                    if url:
                        # Clean up and normalize the URL
                        if '?' in url:
                            url = url.split('?')[0]
                        url = self.normalize_reel_url(url)
                        if url not in reel_urls and url not in page_urls and '/reels/' in url:
                            page_urls.append(url)
                            print(f"Found reel: {url}")
                
                if not page_urls:
                    consecutive_empty_results += 1
                    if consecutive_empty_results >= 2:
                        print("No more results found")
                        break
                else:
                    consecutive_empty_results = 0
                    reel_urls.extend(page_urls)
                
                # Move to next page
                if len(reel_urls) < num_results:
                    start_index += 10
                    time.sleep(2)  # Short delay between pages
                else:
                    break
            
            if not reel_urls:
                print("No reels found matching the criteria")
            else:
                print(f"\nFound {len(reel_urls)} reels in total")
                
                # Save URLs to a temporary file
                temp_file = Path('temp_reel_urls.txt')
                with open(temp_file, 'w') as f:
                    for url in reel_urls[:num_results]:
                        f.write(f"{url}\n")
                print(f"Saved reel URLs to {temp_file}")
            
            return reel_urls[:num_results]
            
        except Exception as e:
            print(f"Error during Google search: {str(e)}")
            return reel_urls[:num_results] if reel_urls else []

    def process_reels(self) -> None:
        """Process reels with natural behavior."""
        try:
            if self.is_search:
                # Create a temporary context for Google search
                with sync_playwright() as p:
                    search_browser = p.chromium.launch(
                        headless=False,
                        slow_mo=int(os.getenv('BROWSER_SLOWMO', '0'))
                    )
                    search_context = search_browser.new_context(
                        user_agent=self.get_random_user_agent()
                    )
                    search_page = search_context.new_page()
                    
                    try:
                        # Get URLs from Google search
                        reel_urls = self.get_reel_urls_from_google(
                            self.start_input,
                            self.num_reels,
                            search_page=search_page
                        )
                    finally:
                        search_context.close()
                        search_browser.close()
                
                if not reel_urls:
                    raise ValueError(f"No reels found for keyword: {self.start_input}")
                
                # Process the reels using the file-based approach
                temp_file = Path('temp_reel_urls.txt')
                if temp_file.exists():
                    # Switch to file mode processing
                    self.start_input = str(temp_file)
                    self.is_search = False  # Switch to URL mode
                    self.process_reels()  # Recursively call with file mode
                    
                    # Clean up temp file
                    temp_file.unlink()
                else:
                    raise ValueError("Failed to create temporary URL file")
            
            else:
                self.setup_browser()
                self.login_to_instagram()
                time.sleep(2)
                
                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting to process {self.num_reels} reels")
                
                if self.start_input.endswith('.txt'):
                    # File mode - process URLs from file
                    with open(self.start_input, 'r') as f:
                        urls = [self.normalize_reel_url(line.strip()) for line in f if line.strip()]
                    total_urls = len(urls)
                    print(f"Found {total_urls} URLs in file")
                    
                    processed_count = 0
                    skipped_count = 0
                    
                    # Process each URL individually
                    for idx, url in enumerate(urls[:self.num_reels], 1):
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {idx}/{min(total_urls, self.num_reels)}")
                        
                        try:
                            # Process each URL using the extract_reel_data method
                            reel_data = self.extract_reel_data(url)
                            reel_id = reel_data['reel_id']  # Use the reel_id from the processed data
                            output_file = self.output_dir / f"{reel_id}.json"
                            
                            if output_file.exists():
                                print(f"Reel {reel_id} already exists in {output_file}, skipping.")
                                skipped_count += 1
                                processed_count += 1
                                continue
                            
                            with open(output_file, 'w') as f:
                                json.dump(reel_data, f, indent=4)
                            print(f"Saved new reel data to {output_file}")
                            processed_count += 1
                            
                            # Add delay between reels
                            if processed_count < min(total_urls, self.num_reels):
                                delay = random.uniform(2, 3)
                                print(f"Waiting {delay:.1f} seconds before next reel...")
                                time.sleep(delay)
                            
                        except Exception as e:
                            print(f"Error processing reel: {str(e)}")
                            continue
                        
                        if processed_count >= self.num_reels:
                            break
                
                else:
                    # Single URL mode
                    self.start_input = self.normalize_reel_url(self.start_input)
                    processed_count = 0
                    skipped_count = 0
                    current_url = self.start_input
                    
                    while processed_count < self.num_reels:
                        print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Processing reel {processed_count + 1}/{self.num_reels}")
                        
                        reel_id = current_url.strip('/').split('/')[-1]
                        output_file = self.output_dir / f"{reel_id}.json"
                        
                        if output_file.exists():
                            print(f"Reel {reel_id} already exists in {output_file}, skipping.")
                            skipped_count += 1
                            processed_count += 1
                        else:
                            try:
                                reel_data = self.extract_reel_data(current_url)
                                with open(output_file, 'w') as f:
                                    json.dump(reel_data, f, indent=4)
                                print(f"Saved new reel data to {output_file}")
                                processed_count += 1
                            except Exception as e:
                                print(f"Error processing reel {reel_id}: {str(e)}")
                                break
                        
                        if processed_count >= self.num_reels:
                            break
                        
                        try:
                            current_url = self.scroll_to_next_reel()
                        except Exception as e:
                            print(f"Error scrolling to next reel: {str(e)}")
                            break
                
                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Completed processing {processed_count} reels")
                print(f"New reels: {processed_count - skipped_count}")
                print(f"Skipped reels: {skipped_count}")
        
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
    
    # Add advanced search arguments
    parser.add_argument('--time-range', choices=['h', 'd', 'w', 'm', 'y'],
                      help='Time range for search results (hour, day, week, month, year)')
    parser.add_argument('--min-length', type=int,
                      help='Minimum length of reels in minutes')
    parser.add_argument('--exact-match', action='store_true',
                      help='Use exact phrase matching for search')
    parser.add_argument('--exclude', type=str,
                      help='Comma-separated terms to exclude from search')
    parser.add_argument('--safe-search', choices=['off', 'moderate', 'strict'],
                      default='off', help='Safe search level')
    
    args = parser.parse_args()
    
    # Set environment variables from command line arguments
    if args.time_range:
        os.environ['SEARCH_TIME_RANGE'] = args.time_range
    if args.min_length:
        os.environ['SEARCH_MIN_LENGTH'] = str(args.min_length)
    if args.exact_match:
        os.environ['SEARCH_EXACT_MATCH'] = 'true'
    if args.exclude:
        os.environ['SEARCH_EXCLUDE'] = args.exclude
    if args.safe_search:
        os.environ['SEARCH_SAFE'] = args.safe_search
    
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