"""Download only the official public model, with a verified resumable transfer."""
import argparse
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha1, sha256
from pathlib import Path, PurePosixPath

import httpx
from huggingface_hub import HfApi

from sociolit.config import default_data_dir

MODEL = "intfloat/multilingual-e5-small"
NAMES = {"1_Pooling/config.json", "config.json", "model.safetensors", "modules.json",
         "sentence_bert_config.json", "sentencepiece.bpe.model", "special_tokens_map.json",
         "tokenizer.json", "tokenizer_config.json"}
parser = argparse.ArgumentParser(description="Resume and verify public multilingual E5 model downloads")
parser.add_argument("--target", type=Path, default=default_data_dir() / "models/e5-small")
target = parser.parse_args().target.expanduser().resolve()
if target.exists() and (not target.is_dir() or any(target.iterdir())):
    raise SystemExit("Model destination is not empty; preserve and inspect it.")
BASE = target.parent / ("." + target.name + "-verified-transfer")
BASE.mkdir(parents=True, exist_ok=True)
info = HfApi(endpoint="https://huggingface.co").model_info(MODEL, files_metadata=True)
files = {s.rfilename: s for s in info.siblings if s.rfilename in NAMES}
if set(files) != NAMES:
    raise SystemExit("Official model manifest differs from expected files.")
revision = info.sha
print("Official revision confirmed; downloading verified model files.", flush=True)


def digest_file(path, info):
    lfs_hash = getattr(info.lfs, "sha256", None) if info.lfs else None
    digest = sha256() if lfs_hash else sha1()
    if not lfs_hash:
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == (lfs_hash or info.blob_id)


def fetch_part(name, start, end, size, parts_dir):
    part = parts_dir / f"{start:012d}.part"
    expected = end - start + 1
    if part.exists() and part.stat().st_size == expected:
        return part
    if name == "model.safetensors":
        # ModelScope is only a transport; the completed file must match the
        # authoritative SHA-256 obtained from Hugging Face above.
        url = "https://modelscope.cn/api/v1/models/intfloat/multilingual-e5-small/repo?Revision=master&FilePath=model.safetensors"
    else:
        url = f"https://huggingface.co/{MODEL}/resolve/{revision}/{name}"
    for attempt in range(4):
        try:
            with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as client:
                with client.stream("GET", url, headers={"Range": f"bytes={start}-{end}"}) as response:
                    content_range = response.headers.get("content-range", "")
                    if response.status_code != 206 or content_range != f"bytes {start}-{end}/{size}":
                        raise ValueError("Server did not honor the requested range")
                    temporary = part.with_suffix(".tmp")
                    with temporary.open("wb") as stream:
                        count = 0
                        for block in response.iter_bytes():
                            stream.write(block)
                            count += len(block)
                    if count != expected:
                        raise ValueError("Incomplete range")
                    os.replace(temporary, part)
                    return part
        except (httpx.HTTPError, OSError, ValueError):
            if attempt == 3:
                raise RuntimeError("Official model transfer failed after retries") from None
            time.sleep(2 ** attempt)


for name in sorted(NAMES, key=lambda x: files[x].size or 0):
    item = files[name]
    size = item.size
    if not isinstance(size, int) or size <= 0:
        raise SystemExit("Official model manifest lacks a valid size.")
    destination = BASE.joinpath(*PurePosixPath(name).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == size and digest_file(destination, item):
        continue
    parts = BASE / ("parts-" + sha256(name.encode()).hexdigest()[:16])
    parts.mkdir(exist_ok=True)
    chunk_size = 4 * 1024 * 1024
    ranges = [(start, min(start + chunk_size, size) - 1) for start in range(0, size, chunk_size)]
    print(f"Downloading {name}: {round(size / 1024 / 1024, 1)} MiB in {len(ranges)} pieces", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_part, name, start, end, size, parts) for start, end in ranges]
        for n, future in enumerate(as_completed(futures), 1):
            future.result()
            if n % 10 == 0 or n == len(futures):
                print(f"  verified transfer pieces: {n}/{len(futures)}", flush=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    with tmp.open("wb") as output:
        for start, _end in ranges:
            with (parts / f"{start:012d}.part").open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    if tmp.stat().st_size != size or not digest_file(tmp, item):
        raise SystemExit("Official model checksum verification failed; model not installed.")
    os.replace(tmp, destination)
    print("  official checksum verified", flush=True)

if target.exists() and any(target.iterdir()):
    raise SystemExit("Model destination is not empty; preserve and inspect it.")
target.mkdir(parents=True, exist_ok=True)
for name in NAMES:
    destination = target.joinpath(*PurePosixPath(name).parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BASE.joinpath(*PurePosixPath(name).parts), destination)
manifest = {"model": MODEL, "revision": revision, "prefix": "e5", "chunking": "page-400-overlap80-v1"}
(target / "sociolit-model.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
print("Verified model installed locally.", flush=True)
