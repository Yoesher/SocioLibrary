"""Optional local E5 embeddings; no hosted embedding requests, no silent fallback."""
import json
import math
import os
from hashlib import sha256
from heapq import heappush, heappushpop
from pathlib import Path

from filelock import FileLock

MODEL_ID = "intfloat/multilingual-e5-small"


class LocalEmbedder:
    def __init__(self, model_path: str | Path):
        location = Path(model_path).expanduser().resolve()
        if not location.is_dir():
            raise RuntimeError("Local model missing. Run sociolit prepare-model first; see README.")
        manifest = location / "sociolit-model.json"
        if not manifest.exists():
            raise RuntimeError("Use prepare-model to create a versioned local E5 model directory")
        info = json.loads(manifest.read_text(encoding="utf-8"))
        if info.get("model") != MODEL_ID:
            raise RuntimeError("Only the configured multilingual E5 model is supported in this MVP")
        # Keep the researcher's computer responsive; callers can explicitly
        # choose different thread limits in their own process environment.
        os.environ.setdefault("OMP_NUM_THREADS", "2")
        os.environ.setdefault("MKL_NUM_THREADS", "2")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError('Install optional dependencies: pip install -e ".[semantic]"') from exc
        # Only local trusted model files; loading cannot upload text or fetch remote model code.
        self.model = SentenceTransformer(str(location), local_files_only=True, trust_remote_code=False)
        self.key = sha256(manifest.read_bytes()).hexdigest()

    def encode(self, texts, *, query=False):
        prefix = "query: " if query else "passage: "
        return self.model.encode([prefix + text for text in texts], normalize_embeddings=True,
                                 show_progress_bar=False).tolist()


def prepare_model(directory: str | Path):
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError('Install optional dependencies: pip install -e ".[semantic]"') from exc
    target = Path(directory).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("Model directory is not empty; use a new model_path to prepare or upgrade safely")
    target.mkdir(parents=True, exist_ok=True)
    # Download only safetensors model/config assets; never upload corpus or use custom code.
    cached = Path(snapshot_download(MODEL_ID, allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors"],
                                    ignore_patterns=["onnx/*"]))
    import shutil
    for path in cached.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt", ".model", ".safetensors"}:
            destination = target / path.relative_to(cached)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    manifest = {"model": MODEL_ID, "revision": cached.name, "prefix": "e5", "chunking": "page-400-overlap80-v1"}
    (target / "sociolit-model.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest


def _scope_table(db, item_ids):
    if item_ids is None:
        return ""
    if not item_ids:
        raise ValueError("语义试点没有可索引的文献。")
    db.execute("CREATE TEMP TABLE selected_items(id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO selected_items VALUES(?)", [(item,) for item in item_ids])
    return " JOIN selected_items selected ON selected.id=c.item_id "


def build_vectors(store, embedder, batch_size=32, *, item_ids=None, progress=None):
    if not 1 <= batch_size <= 1024:
        raise ValueError("Embedding batch size must be between 1 and 1024")
    total = 0
    last_id = 0
    progress = progress or (lambda count: None)
    with FileLock(str(store.directory / "library.lock"), timeout=1), store.connect() as db:
        scope_join = _scope_table(db, item_ids)
        while True:
            query = "SELECT c.id,c.text FROM chunks c " + scope_join + """ LEFT JOIN vectors v
              ON v.chunk_id=c.id AND v.model=? WHERE c.id>? AND v.chunk_id IS NULL
              ORDER BY c.id LIMIT ?"""
            batch = db.execute(query, (embedder.key, last_id, batch_size)).fetchall()
            if not batch:
                break
            vectors = embedder.encode([r["text"] for r in batch])
            if len(vectors) != len(batch):
                raise ValueError("Embedding batch size mismatch")
            values = []
            for row, vector in zip(batch, vectors, strict=True):
                if not vector or not all(math.isfinite(float(x)) for x in vector):
                    raise ValueError("Invalid embedding")
                values.append((row["id"], embedder.key, json.dumps(vector)))
            db.executemany("INSERT INTO vectors VALUES(?,?,?)", values)
            db.commit()
            total += len(values)
            last_id = batch[-1]["id"]
            progress(total)
    return total


def search_vectors(store, embedder, query, limit=20, *, item_ids=None):
    vector = embedder.encode([query], query=True)[0]
    with store.connect() as db:
        scope_join = _scope_table(db, item_ids)
        missing_query = "SELECT count(*) FROM chunks c " + scope_join + """ WHERE NOT EXISTS
          (SELECT 1 FROM vectors v WHERE v.chunk_id=c.id AND v.model=?)"""
        missing = db.execute(missing_query, (embedder.key,)).fetchone()[0]
        if missing:
            raise RuntimeError(f"语义索引尚未完成（还有 {missing} 个片段），请等待或继续构建。")
        query = """SELECT c.*,i.title,i.item_key,i.source,v.embedding FROM vectors v
          JOIN chunks c ON c.id=v.chunk_id JOIN items i ON i.id=c.item_id """ + scope_join + " WHERE v.model=?"
        rows = db.execute(query, (embedder.key,))
        heap = []
        for row in rows:
            result = dict(row)
            candidate = json.loads(result.pop("embedding"))
            if len(candidate) != len(vector):
                raise RuntimeError("Embedding dimension changed; rebuild index")
            denominator = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in candidate))
            result["score"] = sum(a*b for a, b in zip(vector, candidate, strict=True)) / denominator if denominator else 0.0
            entry = (result["score"], result["id"], result)
            if len(heap) < max(1, limit):
                heappush(heap, entry)
            else:
                heappushpop(heap, entry)
    return [entry[2] for entry in sorted(heap, key=lambda x: (x[0], x[1]), reverse=True)]
