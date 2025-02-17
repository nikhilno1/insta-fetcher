import os
import openai
from supabase import create_client
from typing import List, Dict
import argparse

# Initialize clients
openai.api_key = os.getenv("OPENAI_API_KEY")
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

def search_content(query: str, threshold: float = 0.7, limit: int = 5) -> List[Dict]:
    """Search japan_content by similarity to query"""
    # Get query embedding
    query_embedding = openai.embeddings.create(
        model="text-embedding-ada-002",
        input=query
    ).data[0].embedding
    
    # Search using the match_japan_content function
    results = supabase.rpc(
        'match_japan_content',
        {
            'query_embedding': query_embedding,
            'match_threshold': threshold,
            'match_count': limit
        }
    ).execute()
    
    return results.data

def main():
    parser = argparse.ArgumentParser(description='Search Japan-related content')
    parser.add_argument('--query', default="Tell me about Japanese temples",
                      help='Search query (default: "Tell me about Japanese temples")')
    args = parser.parse_args()
    
    results = search_content(args.query)
    
    print(f"\nSearch results for: {args.query}")
    for r in results:
        print(f"\nContent ID: {r['content_id']}")
        print(f"Source: {r['source']}")
        print(f"URL: {r['url']}")
        print(f"Similarity: {r['similarity']:.3f}")
        print(f"Content:\n{r['content']}")
        print("-" * 80)

if __name__ == "__main__":
    main() 