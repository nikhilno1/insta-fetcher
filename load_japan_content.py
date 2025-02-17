import json
from pathlib import Path
import os
from datetime import datetime
import openai
from supabase import create_client
from tqdm import tqdm

# Initialize OpenAI and Supabase clients
openai.api_key = os.getenv("OPENAI_API_KEY")
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

def get_embedding(text: str) -> list[float]:
    """Get embedding for text using OpenAI's API"""
    if not text.strip():
        return [0] * 1536  # Return zero vector for empty text
        
    response = openai.embeddings.create(
        model="text-embedding-ada-002",
        input=text
    )
    return response.data[0].embedding

def combine_content(caption: str, transcription: str) -> str:
    """Combine caption and transcription into a single content field"""
    parts = []
    if caption:
        parts.append(f"Caption: {caption}")
    if transcription:
        parts.append(f"Transcription: {transcription}")
    return "\n\n".join(parts)

def load_instagram_content(json_dir: Path):
    """Load Instagram content from JSON files into Supabase"""
    json_files = list(json_dir.glob("*.json"))
    print(f"Found {len(json_files)} JSON files")
    
    for json_path in tqdm(json_files, desc="Processing content"):
        try:
            # Load JSON data
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Combine caption and transcription
            content = combine_content(
                data.get('caption', ''),
                data.get('transcription', '')
            )
            
            # Generate embedding for combined content
            content_embedding = get_embedding(content)
            
            # Insert into Supabase
            result = supabase.table('japan_content').insert({
                'content_id': data['reel_id'],
                'source': 'instagram',
                'url': data['url'],
                'timestamp': data['timestamp'],
                'content': content,
                'content_embedding': content_embedding,
                'metadata': {
                    'platform': 'instagram',
                    'content_type': 'reel',
                    'original_caption': data.get('caption', ''),
                    'original_transcription': data.get('transcription', '')
                }
            }).execute()
            
            if result.data:
                print(f"Inserted content {data['reel_id']}")
            else:
                print(f"Failed to insert content {data['reel_id']}")
                
        except Exception as e:
            print(f"Error processing {json_path.name}: {str(e)}")

def main():
    json_dir = Path('output')  # Change this to your JSON directory
    load_instagram_content(json_dir)

if __name__ == "__main__":
    main() 