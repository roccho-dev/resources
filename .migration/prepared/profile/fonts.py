"""Compile the shared font selection into a reusable tree.

share/fonts/truetype/<sha256>.ttf, share/licenses/<role>/ and fonts.json, from the policy fonts.nix writes.
prepare_fonts, digest and write_json are moved unchanged from windows hosts/common/pack.py
(roccho-dev/resources#25); this module does not choose families, versions or sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from fontTools.ttLib import TTFont


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def prepare_fonts(policy: list[dict], out: Path) -> None:
    target = out / "share/fonts/truetype"
    target.mkdir(parents=True)
    entries, names = [], set()
    for choice in policy:
        paths = sorted(Path(choice["directory"]).rglob("*.ttf"))
        if not paths:
            raise ValueError(f"No TTF files for role {choice['role']}")
        for path in paths:
            with TTFont(path) as font:
                name = font["name"].getDebugName(4)
                # The typographic family (name ID 16, else 1) is the name a Chromium seed or the Noctty
                # setting selects: every file of a role belongs to exactly the declared family.
                family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
            if family != choice["family"]:
                raise ValueError(f"Font family {family!r} is not {choice['family']!r}: {path.name}")
            if not name or name.casefold() in names:
                raise ValueError(f"Missing or duplicate font full name: {name!r}")
            names.add(name.casefold())
            sha = digest(path)
            filename = sha + ".ttf"
            shutil.copyfile(path, target / filename)
            entries.append({"role": choice["role"], "family": choice["family"],
                            "version": choice["version"], "fullName": name,
                            "file": filename, "sha256": sha})
        licenses = sorted(p for p in Path(choice["licenseSource"]).rglob("*")
                          if p.is_file() and p.name.casefold().startswith(("license", "ofl", "copyright")))
        if not licenses:
            raise ValueError(f"No upstream license found for role {choice['role']}")
        license_dir = out / "share/licenses" / choice["role"]
        license_dir.mkdir(parents=True)
        for path in licenses:
            shutil.copyfile(path, license_dir / (digest(path) + "-" + path.name))
    if not entries:
        raise ValueError("An empty selection cannot prove activation")
    write_json(out / "fonts.json", entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    prepare_fonts(json.loads(args.policy.read_text()), args.out)
