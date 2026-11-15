#!/usr/bin/env python3
"""Builds dist/ from families/: the fonts, named after their contents, and
manifest.json, which describes them for Dropdf's Word to PDF converter.

The fonts are copied byte for byte; nothing is subset, renamed or rewritten.
Before copying, every file is checked against SOURCES.toml and every font
against the rules below, and any failure stops the build with its reason.

    python build.py [--out DIR] [--tag v1.0.0] [--commit local]

The output is deterministic: the same families/ and arguments give the same
bytes, which CI checks by building twice and against the committed dist/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent
FAMILIES_DIR = ROOT / "families"
SOURCES = ROOT / "SOURCES.toml"

# One entry per family, in the order the manifest's fields are documented.
# `standsFor` names the Office fonts a family is drawn in place of, and how
# closely: "metric" (same advance widths), "similar" (same feel, layout may
# shift) or "fallback". `lineMetrics`, when present, are the stood-for font's
# own ascent and descent in em, for a family whose line box differs.
FAMILIES: dict[str, dict] = {
    "carlito": {
        "family": "Carlito",
        "class": "sans",
        "core": True,
        "standsFor": [
            {"name": "Calibri", "match": "metric"},
            {"name": "Calibri Light", "match": "similar"},
        ],
    },
    "caladea": {
        "family": "Caladea",
        "class": "serif",
        "core": True,
        "standsFor": [
            {"name": "Cambria", "match": "metric"},
            {"name": "Cambria Math", "match": "similar"},
        ],
    },
    "liberation-sans": {
        "family": "Liberation Sans",
        "class": "sans",
        "core": True,
        "standsFor": [
            {"name": "Arial", "match": "metric"},
            {"name": "Helvetica", "match": "metric"},
            {"name": "Arial MT", "match": "metric"},
            {"name": "Aptos", "match": "similar"},
            {"name": "Aptos Display", "match": "similar"},
        ],
    },
    "liberation-serif": {
        "family": "Liberation Serif",
        "class": "serif",
        "core": True,
        "standsFor": [
            {"name": "Times New Roman", "match": "metric"},
            {"name": "Times", "match": "metric"},
        ],
    },
    "liberation-mono": {
        "family": "Liberation Mono",
        "class": "mono",
        "core": True,
        "standsFor": [
            {"name": "Courier New", "match": "metric"},
            {"name": "Courier", "match": "metric"},
        ],
    },
    "gelasio": {
        "family": "Gelasio",
        "class": "serif",
        "core": False,
        "standsFor": [
            # Georgia's win ascent and descent, 1878/2048 and 449/2048:
            # Gelasio's own (2600/800 of 2000) give a taller line.
            {
                "name": "Georgia",
                "match": "metric",
                "lineMetrics": {"ascent": 0.917, "descent": 0.219},
            },
        ],
    },
    "comic-relief": {
        "family": "Comic Relief",
        "class": "casual",
        "core": False,
        "standsFor": [{"name": "Comic Sans MS", "match": "metric"}],
    },
    "noto-sans": {
        "family": "Noto Sans",
        "class": "sans",
        "core": False,
        "standsFor": [{"name": "Segoe UI", "match": "similar"}],
    },
    "noto-serif": {
        "family": "Noto Serif",
        "class": "serif",
        "core": False,
        "standsFor": [],
    },
}

LICENCE = "OFL-1.1"
LICENCE_FILES = ("OFL.txt", "LICENSE")
CLASSES = ("sans", "serif", "mono", "casual")
MATCHES = ("metric", "similar", "fallback")

# Upstream file-name suffix -> manifest style, and the bold/italic bits that
# style must carry in OS/2 fsSelection (bit 5, bit 0) and head macStyle
# (bit 0, bit 1).
STYLES = {
    "Regular": ("regular", False, False),
    "Bold": ("bold", True, False),
    "Italic": ("italic", False, True),
    "BoldItalic": ("bolditalic", True, True),
}

# No Microsoft font may be served from here, under its own name or inside
# another. Compared case-insensitively with everything but letters and
# digits removed, as a substring of the name-table names and the file name.
MICROSOFT_NAMES = (
    "Calibri", "Cambria", "Aptos", "Arial", "Times New Roman", "Courier New",
    "Georgia", "Segoe", "Verdana", "Tahoma", "Consolas", "Candara", "Corbel",
    "Constantia", "Comic Sans", "Trebuchet", "Impact", "Selawik", "Sitka",
    "Bahnschrift", "Lucida", "Palatino Linotype", "Book Antiqua", "Garamond",
    "Century Gothic", "Franklin Gothic", "Gill Sans MT", "Webdings",
    "Wingdings", "Symbol MT", "MS Gothic", "MS Mincho", "Meiryo", "Yu Gothic",
    "Malgun", "Microsoft", "SimSun", "SimHei", "Ebrima", "Gadugi", "Leelawadee",
    "Nirmala", "Javanese Text", "Myanmar Text", "Sylfaen", "Marlett",
    "Cascadia",
)
# Name-table IDs checked: family (1), full name (4), PostScript name (6),
# typographic family (16) and WWS family (21).
CHECKED_NAME_IDS = (1, 4, 6, 16, 21)

FILE_KEYS = {"id", "path", "upstream_url", "upstream_ref", "sha256"}
ARCHIVE_KEYS = {"archive_sha256", "member"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
COMMIT = re.compile(r"^(local|[0-9a-f]{40})$")
OUTPUT_NAME = re.compile(
    r"^(manifest\.json"
    r"|[a-z0-9-]+-(regular|bold|italic|bolditalic)\.[0-9a-f]{12}\.ttf"
    r"|[a-z0-9-]+\.OFL\.[0-9a-f]{12}\.txt"
    r"|\..+\.tmp)$"
)


class BuildError(Exception):
    pass


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


MICROSOFT_SQUASHED = tuple((name, squash(name)) for name in MICROSOFT_NAMES)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def microsoft_name_in(text: str) -> str | None:
    s = squash(text)
    for name, squashed in MICROSOFT_SQUASHED:
        if squashed in s:
            return name
    return None


def check_families_table(errors: list[str]) -> None:
    for fid, fam in FAMILIES.items():
        if fam["class"] not in CLASSES:
            errors.append(f"{fid}: class {fam['class']!r} is not one of {CLASSES}")
        for entry in fam["standsFor"]:
            if entry["match"] not in MATCHES:
                errors.append(f"{fid}: match {entry['match']!r} is not one of {MATCHES}")
            extra = set(entry) - {"name", "match", "lineMetrics"}
            if extra:
                errors.append(f"{fid}: unexpected standsFor keys {sorted(extra)}")


def load_sources(errors: list[str]) -> dict[str, dict]:
    """SOURCES.toml as {path: entry}, after checking its shape."""
    with SOURCES.open("rb") as f:
        data = tomllib.load(f)
    if set(data) != {"file"}:
        errors.append(f"SOURCES.toml: expected only [[file]] tables, found {sorted(data)}")
    by_path: dict[str, dict] = {}
    for i, entry in enumerate(data.get("file", []), 1):
        where = f"SOURCES.toml [[file]] #{i}"
        keys = set(entry)
        if keys != FILE_KEYS and keys != FILE_KEYS | ARCHIVE_KEYS:
            errors.append(f"{where}: keys must be {sorted(FILE_KEYS)}, plus "
                          f"{sorted(ARCHIVE_KEYS)} for an archive; found {sorted(keys)}")
            continue
        path = entry["path"]
        if entry["id"] not in FAMILIES:
            errors.append(f"{where}: unknown family id {entry['id']!r}")
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "families" or parts[1] != entry["id"]:
            errors.append(f"{where}: path {path!r} is not families/{entry['id']}/<file>")
        for key in ("sha256", "archive_sha256"):
            if key in entry and not HEX64.match(entry[key]):
                errors.append(f"{where}: {key} is not 64 lowercase hex digits")
        if not entry["upstream_url"].startswith("https://"):
            errors.append(f"{where}: upstream_url is not https")
        if path in by_path:
            errors.append(f"{where}: {path} is listed twice")
        by_path[path] = entry
    return by_path


def read_families(sources: dict[str, dict], errors: list[str]) -> dict[str, dict[str, bytes]]:
    """Every file under families/, checked against SOURCES.toml."""
    found: dict[str, dict[str, bytes]] = {}
    on_disk: set[str] = set()
    for entry in sorted(FAMILIES_DIR.iterdir()):
        if not entry.is_dir():
            errors.append(f"families/{entry.name}: not a family directory")
            continue
        if entry.name not in FAMILIES:
            errors.append(f"families/{entry.name}: not a family build.py knows")
            continue
        files: dict[str, bytes] = {}
        for item in sorted(entry.iterdir()):
            rel = f"families/{entry.name}/{item.name}"
            if not item.is_file() or item.is_symlink():
                errors.append(f"{rel}: not a regular file")
                continue
            on_disk.add(rel)
            data = item.read_bytes()
            src = sources.get(rel)
            if src is None:
                errors.append(f"{rel}: not listed in SOURCES.toml")
                continue
            actual = sha256(data)
            if actual != src["sha256"]:
                errors.append(f"{rel}: SHA-256 {actual} does not match SOURCES.toml {src['sha256']}")
                continue
            files[item.name] = data
        found[entry.name] = files
    for rel in sorted(set(sources) - on_disk):
        errors.append(f"{rel}: listed in SOURCES.toml but missing")
    for fid in FAMILIES:
        if fid not in found:
            errors.append(f"families/{fid}: missing")
    return found


def check_licence(fid: str, files: dict[str, bytes], errors: list[str]) -> bytes | None:
    present = [n for n in LICENCE_FILES if n in files]
    if len(present) != 1:
        errors.append(f"families/{fid}: needs exactly one licence file of {LICENCE_FILES}, found {present}")
        return None
    text = files[present[0]].decode("utf-8", errors="replace")
    if "SIL OPEN FONT LICENSE" not in text.upper() or "Version 1.1" not in text:
        errors.append(f"families/{fid}/{present[0]}: is not the SIL Open Font License 1.1")
        return None
    return files[present[0]]


def style_of(fid: str, name: str, errors: list[str]) -> tuple[str, bool, bool] | None:
    m = re.match(r"^[A-Za-z0-9]+-([A-Za-z]+)\.ttf$", name)
    if not m or m.group(1) not in STYLES:
        errors.append(f"families/{fid}/{name}: file name does not end in -{{{','.join(STYLES)}}}.ttf")
        return None
    return STYLES[m.group(1)]


def ranges_of(codepoints: list[int]) -> str:
    out: list[str] = []
    start = prev = None
    for cp in codepoints:
        if prev is not None and cp == prev + 1:
            prev = cp
            continue
        if start is not None:
            out.append(f"{start:x}" if start == prev else f"{start:x}-{prev:x}")
        start = prev = cp
    if start is not None:
        out.append(f"{start:x}" if start == prev else f"{start:x}-{prev:x}")
    return ",".join(out)


def check_font(fid: str, name: str, data: bytes, style: tuple[str, bool, bool],
               errors: list[str]) -> str | None:
    """Checks one font; returns its `ranges` string, or None on failure."""
    where = f"families/{fid}/{name}"
    before = len(errors)
    if data[:4] != b"\x00\x01\x00\x00":
        errors.append(f"{where}: not a TrueType (glyf) sfnt")
        return None
    try:
        font = TTFont(BytesIO(data), lazy=True)
    except Exception as e:  # noqa: BLE001 - any parse failure stops the build
        errors.append(f"{where}: cannot be read: {e}")
        return None
    tables = set(font.keys())
    if "glyf" not in tables:
        errors.append(f"{where}: has no glyf table")
    for tag in ("fvar", "CFF ", "CFF2"):
        if tag in tables:
            errors.append(f"{where}: has a {tag.strip()} table; only static glyf fonts are served")

    os2 = font["OS/2"]
    if os2.fsType & 0x000F == 0x0002:
        errors.append(f"{where}: OS/2 fsType {os2.fsType:#06x} is Restricted License embedding")

    stem_hit = microsoft_name_in(name)
    if stem_hit:
        errors.append(f"{where}: file name contains the Microsoft font name {stem_hit!r}")
    names = font["name"]
    for rec in names.names:
        if rec.nameID in CHECKED_NAME_IDS:
            text = rec.toUnicode(errors="replace")
            hit = microsoft_name_in(text)
            if hit:
                errors.append(f"{where}: name ID {rec.nameID} {text!r} contains the "
                              f"Microsoft font name {hit!r}")

    family = FAMILIES[fid]["family"]
    typographic = names.getDebugName(16) or names.getDebugName(1)
    if typographic != family:
        errors.append(f"{where}: name-table family {typographic!r} is not {family!r}")

    _, bold, italic = style
    sel_bold, sel_italic = bool(os2.fsSelection & 0x20), bool(os2.fsSelection & 0x01)
    mac = font["head"].macStyle
    mac_bold, mac_italic = bool(mac & 0x01), bool(mac & 0x02)
    if (sel_bold, sel_italic) != (bold, italic) or (mac_bold, mac_italic) != (bold, italic):
        errors.append(f"{where}: fsSelection {os2.fsSelection:#x} / macStyle {mac:#x} "
                      f"do not say {style[0]}")

    cmap = font.getBestCmap()
    if not cmap:
        errors.append(f"{where}: has no Unicode cmap")
        return None
    if len(errors) != before:
        return None
    return ranges_of(sorted(cmap))


def build(out: Path, tag: str, commit: str) -> dict:
    errors: list[str] = []
    if not TAG.match(tag):
        errors.append(f"--tag {tag!r} is not vMAJOR.MINOR.PATCH")
    if not COMMIT.match(commit):
        errors.append(f"--commit {commit!r} is not 'local' or 40 lowercase hex digits")
    check_families_table(errors)
    sources = load_sources(errors)
    families = read_families(sources, errors)

    outputs: dict[str, bytes] = {}
    entries: list[dict] = []
    for fid in sorted(families):
        files = families[fid]
        licence = check_licence(fid, files, errors)
        styles_seen: set[str] = set()
        fonts = [n for n in sorted(files) if n.endswith(".ttf")]
        if not fonts:
            errors.append(f"families/{fid}: has no fonts")
        for name in sorted(files):
            if name not in LICENCE_FILES and not name.endswith(".ttf"):
                errors.append(f"families/{fid}/{name}: neither a font nor a licence")
        if licence is None:
            continue
        licence_name = f"{fid}.OFL.{sha256(licence)[:12]}.txt"
        outputs[licence_name] = licence
        for name in fonts:
            style = style_of(fid, name, errors)
            if style is None:
                continue
            if style[0] in styles_seen:
                errors.append(f"families/{fid}: two files are {style[0]}")
                continue
            styles_seen.add(style[0])
            data = files[name]
            ranges = check_font(fid, name, data, style, errors)
            if ranges is None:
                continue
            digest = sha256(data)
            path = f"{fid}-{style[0]}.{digest[:12]}.ttf"
            fam = FAMILIES[fid]
            outputs[path] = data
            entries.append({
                "path": path,
                "id": fid,
                "family": fam["family"],
                "style": style[0],
                "class": fam["class"],
                "size": len(data),
                "sha256": digest,
                "licence": LICENCE,
                "licenceFile": licence_name,
                "standsFor": [dict(e) for e in fam["standsFor"]],
                "ranges": ranges,
                "core": fam["core"],
            })
        if "regular" not in styles_seen and fonts:
            errors.append(f"families/{fid}: has no Regular")

    if errors:
        raise BuildError("\n".join(errors))

    entries.sort(key=lambda e: e["path"])
    manifest = {
        "schema": 1,
        "source": {"repo": "dropdf-fonts", "tag": tag, "commit": commit},
        "files": entries,
    }
    text = json.dumps(manifest, indent=1, sort_keys=False, ensure_ascii=False) + "\n"
    outputs["manifest.json"] = text.encode("utf-8")
    write_out(out, outputs)
    return {"files": len(outputs), "manifest_sha256": sha256(outputs["manifest.json"])}


def write_out(out: Path, outputs: dict[str, bytes]) -> None:
    """Writes the outputs into `out`, deleting any stale output there. Refuses
    to delete anything that does not look like an output of this script."""
    out.mkdir(parents=True, exist_ok=True)
    stale = []
    for item in sorted(out.iterdir()):
        if item.name in outputs:
            continue
        if not item.is_file() or item.is_symlink() or not OUTPUT_NAME.match(item.name):
            raise BuildError(f"{item}: not an output of build.py; not deleting it")
        stale.append(item)
    for item in stale:
        item.unlink()
    for name in sorted(outputs):
        target = out / name
        if target.exists() and target.read_bytes() == outputs[name]:
            continue
        tmp = out / f".{name}.tmp"
        tmp.write_bytes(outputs[name])
        os.replace(tmp, target)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist",
                        help="output directory (default: dist/ beside this script)")
    parser.add_argument("--tag", default="v1.0.0", help="source.tag in the manifest")
    parser.add_argument("--commit", default="local", help="source.commit in the manifest")
    args = parser.parse_args(argv)
    try:
        result = build(args.out.resolve(), args.tag, args.commit)
    except BuildError as e:
        print(f"build.py: failed\n{e}", file=sys.stderr)
        return 1
    print(f"build.py: wrote {result['files']} files to {args.out}; "
          f"manifest.json sha256 {result['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
