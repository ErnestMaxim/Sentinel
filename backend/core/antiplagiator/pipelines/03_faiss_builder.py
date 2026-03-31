import json
import faiss
import pickle
import torch
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer

def main():
    jsonl_path = Path("backend/core/antiplagiator/data/processed/chunked_database.jsonl")
    index_path = Path("backend/core/antiplagiator/artifacts/faiss_document_index.bin")
    metadata_path = Path("backend/core/antiplagiator/artifacts/faiss_metadata.pkl")

    print("\n1. Booting up the AI on GPU (with FP16 Acceleration)...")
    model = SentenceTransformer(
        'all-mpnet-base-v2', 
        device='cuda',
        model_kwargs={"torch_dtype": torch.float16} 
    )

    dimension = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dimension)

    metadata = []
    
    CHUNK_BATCH_SIZE = 50000 
    current_texts_batch = []
    total_processed = 0

    print(f"\n2. Reading and encoding in batches of {CHUNK_BATCH_SIZE} (RAM Optimized)...")
    
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): 
                continue
            
            data = json.loads(line)
            current_texts_batch.append(data["text"])
            
            metadata.append({
                "arxiv_id": data["arxiv_id"],
                "title": data["title"],
                "chunk_id": data["chunk_id"]
            })

            if len(current_texts_batch) >= CHUNK_BATCH_SIZE:
                print(f"-> Encoding batch... (Total chunks processed so far: {total_processed})")
                embeddings = model.encode(
                    current_texts_batch, 
                    batch_size=512, 
                    show_progress_bar=False, 
                    convert_to_numpy=True, 
                    normalize_embeddings=True
                )
                
                index.add(embeddings) 
                
                total_processed += len(current_texts_batch)
                current_texts_batch = [] 

    if current_texts_batch:
        print(f"-> Encoding final batch of {len(current_texts_batch)} chunks...")
        embeddings = model.encode(
            current_texts_batch, 
            batch_size=512, 
            show_progress_bar=False, 
            convert_to_numpy=True, 
            normalize_embeddings=True
        )
        index.add(embeddings)
        total_processed += len(current_texts_batch)

    print(f"\n3. Saving {total_processed} vectors to disk...")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    
    faiss.write_index(index, str(index_path))
    
    with open(metadata_path, 'wb') as f:
        pickle.dump(metadata, f)

    print("\nDONE! Your high-resolution FAISS database is ready.")

if __name__ == "__main__":
    main()