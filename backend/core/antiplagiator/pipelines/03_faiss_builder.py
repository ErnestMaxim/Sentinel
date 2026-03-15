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

    texts = []
    metadata = []

    print("1. Loading 320k+ chunks into memory...")
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            texts.append(data["text"])
            # Keep track of where this chunk came from
            metadata.append({
                "arxiv_id": data["arxiv_id"],
                "title": data["title"],
                "chunk_id": data["chunk_id"]
            })
            
    print(f"Loaded {len(texts)} chunks successfully.")

    print("\n2. Booting up the AI on GPU (with FP16 Acceleration)...")
    # We tell it to load the model in 16-bit precision to save massive amounts of memory and time
    model = SentenceTransformer(
        'all-mpnet-base-v2', 
        device='cuda',
        model_kwargs={"torch_dtype": torch.float16} 
    )

    print("\n3. Converting text to vectors (Accelerated)...")
    # Because we saved memory with FP16, we can crank the batch_size up to 512
    embeddings = model.encode(
        texts, 
        batch_size=512, 
        show_progress_bar=True, 
        convert_to_numpy=True, 
        normalize_embeddings=True
    )

    print("\n4. Building the FAISS Vector Database...")
    dimension = embeddings.shape[1]  # 768 for MPNet
    index = faiss.IndexFlatIP(dimension) # Inner Product = Cosine Similarity
    index.add(embeddings)
    
    print(f"Database built with {index.ntotal} vectors.")

    print("\n5. Saving everything to disk...")
    # Save the math index
    faiss.write_index(index, str(index_path))
    
    # Save the metadata mapping
    with open(metadata_path, 'wb') as f:
        pickle.dump(metadata, f)

    print("\n🎉 DONE! Your Antiplagiator Engine is fully trained and saved.")

if __name__ == "__main__":
    main()