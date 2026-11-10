import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path

from .config import data_dir, read_config
from .store import Store


def parser():
    root = argparse.ArgumentParser(description="SocioLibrary: 本地社会学文献知识库")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("serve", "import-zotero", "search", "embed", "prepare-model", "discover", "status"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path)
        command.add_argument("--data-dir", type=Path)
        if name == "serve":
            command.add_argument("--port", type=int, default=8765)
            command.add_argument("--open-browser", action="store_true")
        elif name == "import-zotero":
            command.add_argument("--export", type=Path)
        elif name == "search":
            command.add_argument("query")
            command.add_argument("--semantic", action="store_true")
        elif name == "discover":
            command.add_argument("--output", type=Path)
            command.add_argument("--due", action="store_true", help="Only run sources not successful this calendar month")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = read_config(args.config)
        store = Store(data_dir(config, args.data_dir))
        model_path = config.get("semantic", {}).get("model_path") or store.directory / "models" / "e5-small"
        result = None
        if args.command == "serve":
            import uvicorn

            from .server import create_app
            if config.get("discovery", {}).get("auto_on_start", False):
                from .scheduler import discover_due
                def update():
                    try:
                        discover_due(store, config)
                    except Exception:
                        store.set_state("last_discovery", {"complete": False, "errors": ["Startup update failed; run discover to retry"]})
                threading.Thread(target=update, daemon=True).start()
            if args.open_browser:
                threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
            uvicorn.run(create_app(store, config), host="127.0.0.1", port=args.port, access_log=False)
        elif args.command == "import-zotero":
            from .service import sync_zotero
            result = sync_zotero(store, config, args.export)
        elif args.command == "search":
            if args.semantic:
                from .scope import active_scope
                from .semantic import LocalEmbedder, search_vectors
                scope = active_scope(store, config)
                result = search_vectors(store, LocalEmbedder(model_path), args.query,
                                        item_ids=scope["item_ids"] if scope else None)
            else:
                result = store.search(args.query)
        elif args.command == "embed":
            from .semantic import LocalEmbedder
            from .service import build_configured_embeddings
            result = build_configured_embeddings(store, config, LocalEmbedder(model_path))
        elif args.command == "prepare-model":
            from .semantic import prepare_model
            result = prepare_model(model_path)
        elif args.command == "discover":
            from .scheduler import discover_due
            result = discover_due(store, config, force=not args.due, output_dir=args.output)
        elif args.command == "status":
            result = store.stats()
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if isinstance(result, dict) and result.get("complete") is False:
                return 2
        return 0
    except Exception as exc:
        # Do not print request URLs or environment secrets through tracebacks.
        print(f"{type(exc).__name__}: operation failed. Check local configuration and source availability.", file=sys.stderr)
        return 1
