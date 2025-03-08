import json
from pathlib import Path
import os
from datetime import datetime
import openai
from supabase import create_client
from tqdm import tqdm
import shutil

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
    print(f"Found {len(json_files)} JSON files to process")
    
    processed_dir = json_dir / 'processed'
    error_dir = json_dir / 'error'
    error_dir.mkdir(exist_ok=True)  # Create error directory if it doesn't exist
    
    for json_path in tqdm(json_files, desc="Processing content"):
        try:
            # Load JSON data
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check for keyword-related skip messages
            if 'skipped' in data and "No matching keywords found" in data['skipped']:
                print(f"Moving {json_path.name} to error directory: No matching keywords")
                new_path = error_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                continue
            
            # Skip if both caption and transcription are empty
            if not data.get('caption') and not data.get('transcription'):
                print(f"Moving {json_path.name} to error directory: No content found")
                new_path = error_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                continue
            
            # Skip if the file has other errors
            if 'error' in data:
                print(f"Moving {json_path.name} to error directory: Contains error")
                new_path = error_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                continue
            
            # Combine caption and transcription
            content = combine_content(
                data.get('caption', ''),
                data.get('transcription', '')
            )
            
            # Skip if combined content is empty or too short
            if not content.strip() or len(content.strip()) < 10:  # Minimum 10 characters
                print(f"Moving {json_path.name} to error directory: Content too short or empty")
                new_path = error_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                continue
            
            # Generate embedding for combined content
            content_embedding = get_embedding(content)
            
            # Insert into Supabase
            result = supabase.table('japan_content').insert({
                'content_id': data['reel_id'],
                'source': 'instagram',
                'url': data['url'],  # Single URL field
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
                # Move file to processed directory
                new_path = processed_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                print(f"Moved {json_path.name} to processed directory")
            else:
                print(f"Moving {json_path.name} to error directory: Database insertion failed")
                new_path = error_dir / json_path.name
                shutil.move(str(json_path), str(new_path))
                
        except Exception as e:
            print(f"Moving {json_path.name} to error directory: {str(e)}")
            new_path = error_dir / json_path.name
            shutil.move(str(json_path), str(new_path))

def main():
    json_dir = Path('output')
    load_instagram_content(json_dir)

if __name__ == "__main__":
    main() 