#!/usr/bin/env python3
"""Write the editor's read-only data into web/data/, for the GitHub Pages copy.

The Pages site has no Python server, so the editor loads these files when /api/ is missing.
Saving, the reachability check and "Run in emulator" still need the local server.
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from editor_server import Project  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    project = Project(ROOT)
    out = ROOT / "web" / "data"
    (out / "level").mkdir(parents=True, exist_ok=True)
    files = {
        "tiles.json": project.tiles_api(),
        "levels.json": project.levels(),
        "sprites.json": project.sprites_api(),
        "palette.json": project.palette_api(),
    }
    for level in files["levels.json"]:
        files[f"level/{level['name']}.json"] = {"name": level["name"], "text": project.read_level(level["name"])}
    for name, obj in files.items():
        (out / name).write_text(json.dumps(obj), encoding="utf-8")
        print(name)
    # GitHub Pages serves /docs, and this account's token cannot push a workflow, so the site is a copy of web/.
    docs = ROOT / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    shutil.copytree(ROOT / "web", docs)
    print("docs/")


if __name__ == "__main__":
    main()
