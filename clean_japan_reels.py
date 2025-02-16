import json
from pathlib import Path
import argparse

def should_keep_file(file_path: Path, keywords: list) -> tuple[bool, str, dict]:
    """
    Check if file contains Japan-related content.
    Returns (should_keep, reason, content)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Convert keywords and text to lowercase for case-insensitive matching
        keywords = [k.lower() for k in keywords]
        caption = data.get('caption', '').lower()
        transcription = data.get('transcription', '').lower()
        
        content = {
            'caption': data.get('caption', ''),
            'transcription': data.get('transcription', '')
        }
        
        # Check caption
        if any(keyword in caption for keyword in keywords):
            return True, "Matched in caption", content
            
        # Check transcription
        if any(keyword in transcription for keyword in keywords):
            return True, "Matched in transcription", content
            
        return False, "No Japan-related content found", content
        
    except Exception as e:
        return True, f"Error processing file (keeping it): {str(e)}", {'caption': '', 'transcription': ''}

def main():
    parser = argparse.ArgumentParser(description='Clean non-Japan related reels from output folder')
    parser.add_argument('--delete', action='store_true', 
                      help='Actually delete files. Without this, only shows what would be deleted')
    parser.add_argument('--output-dir', default='output',
                      help='Directory containing JSON files (default: output)')
    args = parser.parse_args()
    
    # Keywords to check for
    keywords = [
        'japan', 'japanese', 'tokyo', 'kyoto', 'osaka', 'hiroshima',
        'shinkansen', 'bullet train', 'mount fuji', 'mt fuji',
        'sushi', 'ramen', 'sakura', 'hanami', 'kimono', 'yukata',
        'onsen', 'ryokan', 'shrine', 'temple', 'jinja', 'yen',
        'shibuya', 'harajuku', 'akihabara', 'shinjuku'
    ]
    
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"Error: Directory {output_dir} does not exist")
        return
        
    files_to_delete = []
    files_to_keep = []
    
    # Process all JSON files
    for file_path in output_dir.glob('*.json'):
        should_keep, reason, content = should_keep_file(file_path, keywords)
        
        if should_keep:
            files_to_keep.append((file_path.name, reason))
        else:
            files_to_delete.append((file_path, content))
    
    # Print summary
    print(f"\nFound {len(files_to_keep) + len(files_to_delete)} total files")
    print(f"Files to keep: {len(files_to_keep)}")
    print(f"Files to delete: {len(files_to_delete)}")
    
    # Show files to be kept
    print("\nKeeping files:")
    for filename, reason in files_to_keep:
        print(f"  {filename} ({reason})")
    
    # Show files to be deleted with their content
    print("\nFiles to be deleted:")
    for file_path, content in files_to_delete:
        print(f"\n  {file_path.name}")
        print("  Caption:")
        print(f"    {content['caption']}")
        print("  Transcription:")
        print(f"    {content['transcription']}")
    
    # Delete files if --delete flag is used
    if args.delete and files_to_delete:
        print("\nDeleting files...")
        for file_path, _ in files_to_delete:
            try:
                file_path.unlink()
                print(f"  Deleted {file_path.name}")
            except Exception as e:
                print(f"  Error deleting {file_path.name}: {str(e)}")
    elif files_to_delete:
        print("\nNo files deleted (use --delete flag to actually delete files)")

if __name__ == "__main__":
    main() 