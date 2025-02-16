import json
import httpx
from typing import Dict
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_reel_data(reel_url: str) -> Dict:
    """Extract data from a single Instagram reel using internal API."""
    # Extract shortcode from URL
    shortcode = reel_url.strip('/').split('/')[-1]
    
    # Get session ID and other auth tokens from environment variables
    session_id = os.getenv('INSTAGRAM_SESSION_ID')
    csrf_token = os.getenv('INSTAGRAM_CSRF_TOKEN')
    ds_user_id = os.getenv('INSTAGRAM_DS_USER_ID')
    
    if not session_id:
        raise ValueError("INSTAGRAM_SESSION_ID not found in .env file")
    
    # Setup client with required headers
    client = httpx.Client(
        headers={
            "x-ig-app-id": "936619743392459",
            "x-asbd-id": "129477",
            "x-ig-www-claim": "0",
            "x-requested-with": "XMLHttpRequest",
            "x-csrftoken": csrf_token or "",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "*/*",
            "Cookie": f"sessionid={session_id}; csrftoken={csrf_token}; ds_user_id={ds_user_id}",
            "Origin": "https://www.instagram.com",
            "Referer": f"https://www.instagram.com/reel/{shortcode}/",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        },
        timeout=30.0,
        follow_redirects=True
    )

    try:
        print(f"\nFetching data for shortcode: {shortcode}")
        
        # Use the public API endpoint
        api_url = f"https://www.instagram.com/api/v1/web/get_ruling_for_content/?content_type=MEDIA&surface=POST&content_id={shortcode}"
        
        print("Sending request...")
        response = client.get(api_url)
        
        print(f"Status Code: {response.status_code}")
        
        # Try alternative endpoint if first one fails
        if response.status_code != 200:
            print("Trying alternative endpoint...")
            alt_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
            response = client.get(alt_url)
            print(f"Alternative Status Code: {response.status_code}")
            
        try:
            data = response.json()
            
            # Try to extract data from either response format
            if 'items' in data:
                item = data['items'][0]
                reel_data = {
                    "shortcode": shortcode,
                    "caption": item.get('caption', {}).get('text', ''),
                    "type": item.get('media_type', ''),
                    "view_count": item.get('view_count', 0),
                    "play_count": item.get('play_count', 0),
                    "like_count": item.get('like_count', 0),
                }
            else:
                # Alternative response format
                media = data.get('graphql', {}).get('shortcode_media', {})
                reel_data = {
                    "shortcode": shortcode,
                    "caption": media.get('edge_media_to_caption', {}).get('edges', [{}])[0].get('node', {}).get('text', ''),
                    "type": media.get('__typename', ''),
                    "view_count": media.get('video_view_count', 0),
                    "play_count": media.get('video_play_count', 0),
                    "like_count": media.get('edge_media_preview_like', {}).get('count', 0),
                }
            
            print("\nExtracted Reel Data:")
            print(json.dumps(reel_data, indent=2))
            return reel_data
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {str(e)}")
            return None

    except Exception as e:
        print(f"Error fetching reel data: {str(e)}")
        return None

def test_multiple_reels():
    """Test function with multiple reel URLs"""
    test_urls = [
        "https://www.instagram.com/reel/DAAX2EwpqfL/",
    ]
    
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        result = get_reel_data(url)
        if result:
            print("Success!")
        else:
            print(f"Failed to fetch data for {url}")

if __name__ == "__main__":
    test_multiple_reels() 