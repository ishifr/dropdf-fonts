# dropdf-fonts

The fonts Dropdf's Word to PDF converter draws documents with, in place of the
Microsoft fonts a `.docx` names and Dropdf may not redistribute.

**These are site assets for Dropdf only, not a public CDN.** Dropdf's site
build downloads `dist/` from a pinned tag and commit, checks every file
against the SHA-256 of `dist/manifest.json`, and serves the fonts from its
own origin; the app bundles some of them. Nothing here is meant to be
fetched from GitHub by anyone else, and nothing promises it will stay where
it is. If you want these fonts, take them from their upstream projects,
listed below.

No Microsoft font is here, under its own name or any other, and none ever
will be. `build.py` refuses any font whose name table or file name contains
one (Selawik included, since Microsoft made it).

## What is here

| id | Family | Styles | Stands in for | Upstream (pinned) | Licence |
|---|---|---|---|---|---|
| `carlito` | Carlito | R B I BI | Calibri (metric), Calibri Light (similar) | [googlefonts/carlito](https://github.com/googlefonts/carlito) @ `3a810cab` | OFL 1.1, Reserved Font Name "Carlito" |
| `caladea` | Caladea | R B I BI | Cambria (metric), Cambria Math (similar) | [googlefonts/caladea](https://github.com/googlefonts/caladea) @ `336a529c` | OFL 1.1 |
| `liberation-sans` | Liberation Sans | R B I BI | Arial, Helvetica, Arial MT (metric); Aptos, Aptos Display (similar) | [liberation-fonts](https://github.com/liberationfonts/liberation-fonts) 2.1.5 release tarball | OFL 1.1, Reserved Font Names "Liberation", "Arimo", "Tinos", "Cousine" |
| `liberation-serif` | Liberation Serif | R B I BI | Times New Roman, Times (metric) | the same tarball | the same |
| `liberation-mono` | Liberation Mono | R B I BI | Courier New, Courier (metric) | the same tarball | the same |
| `gelasio` | Gelasio | R B I BI | Georgia (metric widths, Georgia's line metrics in the manifest) | [SorkinType/Gelasio](https://github.com/SorkinType/Gelasio) @ `7ab20e7e` | OFL 1.1 |
| `comic-relief` | Comic Relief | R B | Comic Sans MS (metric) | [loudifier/Comic-Relief](https://github.com/loudifier/Comic-Relief) v1.300 release zip | OFL 1.1 |
| `noto-sans` | Noto Sans | R B I BI | Segoe UI (similar) | [notofonts/latin-greek-cyrillic](https://github.com/notofonts/latin-greek-cyrillic) `NotoSans-v2.015` release zip, `unhinted/ttf` | OFL 1.1 |
| `noto-serif` | Noto Serif | R B I BI | (nothing by name; a fallback) | the same repository, `NotoSerif-v2.015` | OFL 1.1 |

34 static TrueType (glyf) fonts, every one with OS/2 `fsType` 0. Carlito,
Caladea and the three Liberation families (20 files) are marked `core`: the
app bundles them and the site caches them once a document is chosen.

Coverage that matters for Uzbek and Russian text, read from each font's cmap:

| Family | U+02BB (ʻ) | Cyrillic U+0400–04FF |
|---|---|---|
| Carlito | yes | 254 of 256 |
| Caladea | no | none |
| Liberation Sans, Serif, Mono | yes | 256 of 256 |
| Gelasio | yes | none |
| Comic Relief | no | 94 of 256 |
| Noto Sans, Noto Serif | yes | 256 of 256 |

The converter falls back to Noto for what a family lacks; the manifest's
`ranges` field is the full cmap of each file.

## Layout

- `families/<id>/` — the upstream files, **byte for byte**, with the
  family's licence (`OFL.txt`, or `LICENSE` for Liberation). Nothing is
  subset, hinted, renamed or rewritten: Carlito and Liberation have Reserved
  Font Names, so a modified copy could not keep its name.
- `SOURCES.toml` — for every file under `families/`: its upstream URL, the
  tag or commit it was taken from, and its SHA-256; for a file taken from a
  release archive, the archive's SHA-256 and the member's path inside it.
- `build.py` — checks everything and writes `dist/`.
- `dist/` — committed: what Dropdf downloads.
  - `<id>-<style>.<sha12>.ttf`, style one of `regular`, `bold`, `italic`,
    `bolditalic`, and `sha12` the first 12 hex digits of the file's SHA-256;
  - `<id>.OFL.<sha12>.txt`, the family's licence;
  - `manifest.json`, which describes each font: family, style, class, size,
    SHA-256, licence, the Office fonts it stands in for and how closely, its
    cmap as ranges, and whether it is core.
- `requirements.in` / `requirements.txt` — fontTools, pinned with hashes.

## Building

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
.venv/bin/python build.py                 # writes dist/
.venv/bin/python build.py --out /tmp/x    # anywhere else
```

`--tag` (default `v1.0.0`) and `--commit` (default `local`) fill the
manifest's `source`. The commit is informative only — a commit cannot name
itself — and Dropdf pins the commit and the manifest's SHA-256 on its side.

`build.py` stops with every reason it found if:

1. a file under `families/` is not in `SOURCES.toml`, or does not match its
   SHA-256, or a listed file is missing;
2. a font is not static TrueType: no `glyf`, or an `fvar`, `CFF ` or `CFF2`
   table;
3. a font's OS/2 `fsType` is Restricted License embedding;
4. a font's name table (IDs 1, 4, 6, 16, 21) or file name contains a
   Microsoft font name;
5. a font's family name, or its bold and italic bits, disagree with its
   family and file name, or a family has no licence, no Regular, or two
   files of one style.

The output is deterministic — sorted, canonical JSON, files copied as they
are — and it deletes stale files from the output directory (and refuses to
delete anything that is not one of its outputs). CI
(`.github/workflows/build.yml`) builds twice, diffs the two builds, diffs
them against the committed `dist/`, checks every licence is present, and on
a tag checks that the tag is the manifest's.

## Updating

1. Change the pinned commit or release, download the new files, and check
   each archive or file against a SHA-256 published or computed from a
   second source. Never take a file from anywhere but the project's own
   repository or release.
2. Replace the files in `families/<id>/`, byte for byte, with the licence.
3. Update the family's entries in `SOURCES.toml` (URL, ref, SHA-256, and
   the archive's SHA-256 and member).
4. A new family also needs an entry in `FAMILIES` in `build.py`: its name,
   class, whether it is core, and what it stands in for.
5. Run `build.py` with the next `--tag`, look at the manifest diff
   (especially `ranges`), and commit `dist/` with the change.
6. Tag the commit with the same tag, then pin the tag, the commit and the
   SHA-256 of `dist/manifest.json` in Dropdf.

To change fontTools: edit `requirements.in`, then
`uv pip compile requirements.in --generate-hashes --python-version 3.12 -o requirements.txt`.

## Licences

Every font here is under the SIL Open Font License 1.1; each family's own
copy of it, with its copyright lines and Reserved Font Names, is in its
directory and published beside the fonts in `dist/`. The repository's own
files (`build.py`, the workflow, this README) carry no font data.
