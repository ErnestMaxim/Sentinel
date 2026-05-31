# Sentinel FAISS Microservice — Modal.com

Hosts the full 40GB IVFFLAT FAISS index on a 64GB RAM Modal container, 
exposing a simple HTTP search endpoint your FastAPI backend calls.

---

## Setup (one-time)

### 1. Install Modal
```bash
pip install modal
modal setup   # opens browser to authenticate
```

### 2. (Optional) Add your HuggingFace token as a Modal Secret
Only needed if `EXANU/antiplagiator-artifacts` is a private dataset.
```bash
modal secret create hf-token HF_TOKEN=hf_xxxxxxxxxxxx
```

### 3. Download the index into the Modal Volume
This runs once and caches the 40GB index in Modal's persistent storage.
Subsequent deploys skip the download entirely.
```bash
modal run app.py::download_index
```

### 4. Deploy the microservice
```bash
modal deploy app.py
```

Modal will print a URL like:
```
https://your-workspace--sentinel-faiss-microservice-faisssearchservice-search.modal.run
```

---

## Usage from your FastAPI backend

Replace the local `load_global_index` call with an HTTP call to Modal.

```python
import httpx, os

MODAL_SEARCH_URL = os.environ["MODAL_SEARCH_URL"]  # set this in your .env

async def remote_faiss_search(chunks, top_k=5, threshold=0.85, self_arxiv_id=None):
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(MODAL_SEARCH_URL, json={
            "chunks": chunks,
            "top_k": top_k,
            "threshold": threshold,
            "self_arxiv_id": self_arxiv_id,
        })
        resp.raise_for_status()
        return resp.json()["results"]
```

---

## Endpoints

| Method | Path      | Description                          |
|--------|-----------|--------------------------------------|
| GET    | /health   | Returns index stats and status       |
| POST   | /search   | Search the FAISS index               |

### POST /search — Request body
```json
{
    "chunks": ["text chunk 1", "text chunk 2"],
    "top_k": 5,
    "threshold": 0.85,
    "self_arxiv_id": "2301.12345"
}
```

### POST /search — Response
```json
{
    "results": [
        {
            "chunk_idx": 0,
            "hits": [
                {
                    "db_idx": 123,
                    "similarity": 0.912,
                    "arxiv_id": "2212.09251",
                    "chunk_id": 4,
                    "title": "Attention Is All You Need",
                    "source_type": "arxiv",
                    "top_category": "cs"
                }
            ]
        }
    ],
    "timing_s": 1.23
}
```

---

## Cost estimate

Modal charges only for actual compute time.

| Scenario | Cost |
|---|---|
| 100 requests/day × 3s each | ~$0.07/day |
| 1,000 requests/day × 3s each | ~$0.70/day |
| Idle (min_containers=1, just RAM) | ~$2–4/day |

For a low-traffic academic project, set `min_containers=0` to pay only 
when requests come in (cold start ~30–60s on first request after idle).
Change it back to `1` when you need consistent response times.
