import os
import json
import time
from pathlib import Path
from typing import Optional, Dict
import httpx
import brotli
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv
import re

load_dotenv()

class InstagramCaptionFetcher:
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

    def __init__(self):
        self.session_id = os.getenv('INSTAGRAM_SESSION_ID')
        if not self.session_id:
            raise ValueError("INSTAGRAM_SESSION_ID not found in .env file")

    def fetch_via_api(self, reel_id: str) -> Optional[str]:
        """Attempt to fetch caption using Instagram's API"""
        client = httpx.Client(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://www.instagram.com/",
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
                "X-ASBD-ID": "198387",
                "Cookie": f"sessionid={self.session_id}",
            },
            timeout=30.0,
            follow_redirects=True
        )

        try:
            # First get the media ID
            media_id = self.get_media_id(f"https://www.instagram.com/reels/{reel_id}/")
            if not media_id:
                print("Could not find media ID")
                return None

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
                    print(f"Response Headers: {dict(response.headers)}")

                    if response.status_code == 200:
                        # Handle potential compression
                        content_encoding = response.headers.get('content-encoding', '').lower()
                        if content_encoding == 'br':
                            decompressed = brotli.decompress(response.content)
                            data = json.loads(decompressed)
                        else:
                            data = response.json()

                        print(f"Response Data: {json.dumps(data, indent=2)}")
                        
                        if 'items' in data and data['items']:
                            caption_data = data['items'][0].get('caption', {})
                            if isinstance(caption_data, dict):
                                return caption_data.get('text', '')
                            return caption_data or ''
                except Exception as e:
                    print(f"Error with endpoint {api_url}: {str(e)}")
                    continue

            return None
        except Exception as e:
            print(f"API Error: {str(e)}")
            return None

    def fetch_via_scraping(self, reel_url: str) -> Optional[str]:
        """Attempt to fetch caption by scraping the page"""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={'width': 1280, 'height': 720}
            )

            # Add authentication cookies
            context.add_cookies([{
                "name": "sessionid",
                "value": self.session_id,
                "domain": ".instagram.com",
                "path": "/"
            }])

            page = context.new_page()

            try:
                print(f"Navigating to: {reel_url}")
                page.goto(reel_url)
                
                # Wait for the page to be fully loaded
                page.wait_for_load_state("networkidle")
                
                # Wait for specific elements that indicate the reel is loaded
                try:
                    page.wait_for_selector('video', timeout=10000)
                    print("Video element found")
                except PlaywrightTimeout:
                    print("Timeout waiting for video element")

                # Additional wait for dynamic content
                time.sleep(3)

                # Try to extract data from shared data
                print("Looking for shared data...")
                shared_data = None
                for script in page.locator('script').all():
                    try:
                        text = script.inner_text()
                        if 'window._sharedData = ' in text:
                            shared_data = json.loads(text.split('window._sharedData = ')[1].split(';</script>')[0])
                            print("Found window._sharedData")
                            break
                    except Exception:
                        continue

                if shared_data:
                    try:
                        # Navigate through shared data to find caption
                        entry_data = shared_data.get('entry_data', {})
                        if 'PostPage' in entry_data and entry_data['PostPage']:
                            media = entry_data['PostPage'][0].get('graphql', {}).get('shortcode_media', {})
                            if media:
                                caption_edges = media.get('edge_media_to_caption', {}).get('edges', [])
                                if caption_edges:
                                    caption = caption_edges[0]['node']['text']
                                    print(f"Found caption in shared data: {caption}")
                                    return caption
                    except Exception as e:
                        print(f"Error parsing shared data: {str(e)}")

                # Try different selectors with explicit waits
                selectors = [
                    'div[class*="_a9zs"]',
                    'span[class*="_a9zs"]',
                    'div[data-testid="post-comment-root"]',
                    'article div > span',  # Generic span inside article
                    'article div > div > span',  # Nested span
                ]

                for selector in selectors:
                    print(f"Trying selector: {selector}")
                    try:
                        # Wait briefly for each selector
                        elements = page.locator(selector).all()
                        for element in elements:
                            if element.is_visible():
                                text = element.inner_text()
                                if text and len(text) > 5:  # Avoid empty or too short texts
                                    print(f"Found text with selector {selector}: {text}")
                                    return text
                    except Exception as e:
                        print(f"Error with selector {selector}: {str(e)}")

                # Save debug info if nothing found
                page.screenshot(path="debug_screenshot.png")
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())

                return None
            except Exception as e:
                print(f"Scraping Error: {str(e)}")
                return None
            finally:
                browser.close()

    def get_media_id(self, reel_url: str) -> Optional[str]:
        """Get the internal media ID from the page source"""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={'width': 1280, 'height': 720}
            )

            context.add_cookies([{
                "name": "sessionid",
                "value": self.session_id,
                "domain": ".instagram.com",
                "path": "/"
            }])

            page = context.new_page()
            try:
                page.goto(reel_url, wait_until="domcontentloaded")
                time.sleep(3)

                # Look for the media ID in the page source
                page_content = page.content()
                
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
            finally:
                browser.close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test Instagram Caption Fetching')
    parser.add_argument('reel_url', help='Instagram Reel URL')
    args = parser.parse_args()

    reel_id = args.reel_url.strip('/').split('/')[-1]
    fetcher = InstagramCaptionFetcher()

    print(f"\nTesting caption fetch for reel: {reel_id}")
    print("-" * 50)

    # Try API first
    print("\n1. Trying API...")
    caption = fetcher.fetch_via_api(reel_id)
    if caption:
        print("Success via API!")
        print(f"Caption: {caption}")
    else:
        print("API method failed")

    # If API fails, try scraping
    if not caption:
        print("\n2. Trying Web Scraping...")
        caption = fetcher.fetch_via_scraping(args.reel_url)
        if caption:
            print("Success via Scraping!")
            print(f"Caption: {caption}")
        else:
            print("Scraping method failed")

if __name__ == "__main__":
    main() 