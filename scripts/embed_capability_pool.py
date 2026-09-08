#!/usr/bin/env python3
"""Embed a capability pool once for per-Edit semantic retrieval."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from hashlib import sha256
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from instruction_augmentation.doc_api import DocApiClient
from instruction_augmentation.dynamic_capability_retrieval import capability_embedding_text
from instruction_augmentation.linear_edit_queries import append_jsonl, read_jsonl


def load_saved_vectors(path: Path) -> list[list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    vectors = payload.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        raise ValueError(f"saved embedding response has no vectors: {path}")
    return vectors


def embed_pool(*, pool_path: Path, run_dir: Path, client: DocApiClient,
               batch_size: int = 10, dimensions: int = 1024,
               max_cards: int = 200, max_requests: int = 20) -> list[dict[str, Any]]:
    """Materialize an immutable, provider-bound vector view without changing the source pool."""
    from scripts.run_linear_edit_query_augmentation import write_json_once

    pool = list(read_jsonl(pool_path))
    if not 1 <= batch_size <= 10 or not 1 <= len(pool) <= max_cards:
        raise ValueError("pool or batch size exceeds the configured bound")
    if len({row['capability_id'] for row in pool}) != len(pool):
        raise ValueError("duplicate capability IDs in pool")
    if (len(pool) + batch_size - 1) // batch_size > max_requests:
        raise ValueError("embedding request bound is too small for pool")
    identity = dict(pool_sha256=sha256(pool_path.read_bytes()).hexdigest(),
                    embedding_model=client.embedding_model, base_url=client.base_url,
                    dimensions=dimensions, batch_size=batch_size)
    write_json_once(run_dir / 'embedding_identity.json', identity)
    output = run_dir / 'embedded_capability_pool.jsonl'
    completed = {row['capability_id']: row for row in read_jsonl(output)} if output.exists() else {}
    for offset in range(0, len(pool), batch_size):
        batch = pool[offset:offset + batch_size]
        missing = [row for row in batch if row['capability_id'] not in completed]
        if not missing:
            continue
        request_id = f'embed_pool__{offset // batch_size + 1:04d}'
        saved = client.log_dir / 'responses' / f'{request_id}.json'
        if saved.exists():
            vectors = load_saved_vectors(saved)
        else:
            vectors, _ = client.embeddings(request_id=request_id,
                inputs=[capability_embedding_text(row) for row in batch], dimensions=dimensions)
        if len(vectors) != len(batch) or any(len(vector) != dimensions for vector in vectors):
            raise ValueError('embedding response shape mismatch')
        for row, vector in zip(batch, vectors):
            if row['capability_id'] not in completed:
                embedded = {**row, 'embedding': vector}
                append_jsonl(output, embedded)
                completed[row['capability_id']] = embedded
        print(f'embedded {min(offset + batch_size, len(pool))}/{len(pool)}', flush=True)
    rows = list(read_jsonl(output))
    if len(rows) != len(pool) or {row['capability_id'] for row in rows} != {row['capability_id'] for row in pool}:
        raise ValueError('embedded pool incomplete or duplicated')
    originals = {row['capability_id']: row for row in pool}
    for row in rows:
        vector = row.get('embedding', [])
        if len(vector) != dimensions or not all(isinstance(x, (int,float)) and math.isfinite(x) for x in vector):
            raise ValueError('invalid cached embedding vector')
        if {k:v for k,v in row.items() if k != 'embedding'} != {k:v for k,v in originals[row['capability_id']].items() if k != 'embedding'}:
            raise ValueError('cached embedding card content differs from source pool')
    write_json_once(run_dir / 'embedded_pool_manifest.json', {
        **identity, 'embedding_status': 'ok', 'embedded_capability_count': len(rows),
        'output_sha256': sha256(output.read_bytes()).hexdigest(),
    })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dimensions", type=int, default=1024)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 10:
        raise ValueError("embedding batch-size must be 1 to 10")
    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise ValueError("DOC_API_KEY is required")
    pool = list(read_jsonl(args.run_dir / "capability_pool.jsonl"))
    output = args.run_dir / "embedded_capability_pool.jsonl"
    completed = {
        str(row["capability_id"]): row for row in read_jsonl(output)
    } if output.exists() else {}
    with DocApiClient(api_key=key, log_dir=args.run_dir / "provider_embeddings") as client:
        for offset in range(0, len(pool), args.batch_size):
            batch = pool[offset : offset + args.batch_size]
            batch_index = offset // args.batch_size + 1
            missing_ids = {
                row["capability_id"]
                for row in batch
                if row["capability_id"] not in completed
            }
            if not missing_ids:
                continue
            request_id = f"embed_pool__{batch_index:04d}"
            saved = (
                args.run_dir
                / "provider_embeddings"
                / "responses"
                / f"{request_id}.json"
            )
            if saved.exists():
                vectors = load_saved_vectors(saved)
            else:
                if len(missing_ids) != len(batch):
                    raise ValueError(
                        "partially completed embedding batch lacks its saved provider response"
                    )
                vectors, _ = client.embeddings(
                    request_id=request_id,
                    inputs=[capability_embedding_text(row) for row in batch],
                    dimensions=args.dimensions,
                )
            if len(vectors) != len(batch):
                raise ValueError("embedding vector count does not match the batch")
            for row, vector in zip(batch, vectors):
                if row["capability_id"] in missing_ids:
                    append_jsonl(output, {**row, "embedding": vector})
            print(
                f"embedded batch {batch_index}; new_cards={len(missing_ids)}",
                flush=True,
            )
    rows = list(read_jsonl(output))
    if len(rows) != len(pool) or len({row["capability_id"] for row in rows}) != len(pool):
        raise ValueError("embedded pool is incomplete or duplicated")
    manifest: dict[str, Any] = json.loads(
        (args.run_dir / "pool_manifest.json").read_text(encoding="utf-8")
    )
    embedded_manifest = {
        **manifest,
        "embedding_status": "ok",
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": args.dimensions,
        "embedded_capability_count": len(rows),
    }
    path = args.run_dir / "embedded_pool_manifest.json"
    rendered = json.dumps(embedded_manifest, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"immutable output differs: {path}")
    if not path.exists():
        path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
