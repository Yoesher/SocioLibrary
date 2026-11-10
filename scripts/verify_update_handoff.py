"""Disposable CI parent: let the real updater wait for us, install, and relaunch."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from sociolit import __version__
from sociolit.desktop import installer_mutex
from sociolit.software_updates import Release
from sociolit.update_install import launch_install_helper


def main():
    parser = argparse.ArgumentParser()
    for name in ("installer", "target", "data", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise SystemExit("Updater installation verification is restricted to a disposable CI runner")
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    if not all(Path(value).resolve().is_relative_to(root) for value in (args.target, args.data, args.output)):
        raise SystemExit("Synthetic installation paths must remain under the runner temporary folder")
    if Path(args.data).exists():
        raise SystemExit("Updater smoke test requires a new synthetic data folder")
    installer = Path(args.installer).resolve()
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    release = Release(__version__, f"https://github.com/Yoesher/SocioLibrary/releases/download/v{__version__}/{installer.name}",
                      digest, installer.stat().st_size, "Synthetic local build verification")
    kernel, mutex = installer_mutex()
    result = launch_install_helper(installer, release, args.data, args.target,
                                   cache=Path(args.output).parent / "handoff-cache", test_mode=True)
    Path(args.output).write_text(json.dumps({"result_file": str(result["result_file"])}), encoding="utf-8")
    # The process must exit with its mutex still alive; the helper is responsible for waiting.
    assert kernel and mutex


if __name__ == "__main__":
    main()
