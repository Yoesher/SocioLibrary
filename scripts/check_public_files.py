"""Check tracked files before publishing; this complements manual review."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {".pdf", ".epub", ".sqlite", ".sqlite3", ".db", ".safetensors", ".pem", ".key", ".ris", ".bib", ".jpg", ".png"}
BLOCKED_PARTS = {".venv", "storage", "data", "models", "exports", "reports", "work", "logs"}
TOKEN = re.compile(r"(?:gh[pousr]_" + r"[A-Za-z0-9]{20,}|github_pat_" + r"[A-Za-z0-9_]{30,}|sk-proj-" + r"[A-Za-z0-9_-]{20,}|-----BEGIN " + r"(?:RSA |OPENSSH )?PRIVATE KEY-----)")
USER_PATH = re.compile(r"(?:[A-Za-z]:[\\/]Users[\\/](?!YOUR_NAME(?:[\\/]))[^\\/\s\"']+)", re.I)


def violations(paths):
    errors = []
    for relative in paths:
        path = ROOT / relative
        parts = Path(relative).parts
        if (path.is_symlink() or path.suffix.lower() in BLOCKED_SUFFIXES
                or any(part in BLOCKED_PARTS for part in parts)
                or path.name == "config.local.toml" or path.name.endswith(".local.toml")
                or (path.name.startswith(".env") and path.name != ".env.example")):
            errors.append(f"Excluded file: {relative}")
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            errors.append(f"Not reviewable as UTF-8 text: {relative}")
            continue
        if TOKEN.search(content) or USER_PATH.search(content):
            errors.append(f"Possible secret or personal path: {relative}")
    return errors


def main():
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [p for p in raw.decode("utf-8").split("\0") if p]
    if not paths:
        print("No tracked files; stage reviewed files first.", file=sys.stderr)
        return 1
    errors = violations(paths)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Public-file check passed: {len(paths)} tracked text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
