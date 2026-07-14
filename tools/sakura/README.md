# sakura CLI

Catalog tools for Sakura Soft.

## Install (dev)

```bash
cd tools/sakura
uv pip install -e .
# or: pip install -e .
```

## Validate

```bash
# From SakuraSoft root (auto-detects ./catalog)
sakura validate

# Explicit catalog path
sakura validate --catalog /path/to/catalog

# One title only
sakura validate --title title.sakura_match

# Treat missing binary files as errors; enforce release gates
sakura validate --strict --release

# Include example titles under titles/_examples/
sakura validate --examples
```

Exit code `0` = pass, `1` = findings, `2` = usage/load error.

## Bind

Replace “swap image 8 with 201” with stable IDs:

```bash
# List slots + current assets
sakura bind list --title title.sakura_match

# Rebind a slot (default status: review); validates afterward
sakura bind set slot.tile.red asset.tile_red_pastel_v2 --title title.sakura_match

# Same as set
sakura bind rebind slot.tile.red asset.tile_red_pastel_v2 --title title.sakura_match

# Dry-run / force kind-mismatch / skip validate
sakura bind set slot.tile.red asset.tile_red_pastel_v1 --dry-run
sakura bind set slot.tile.red asset.other --force
sakura bind set slot.tile.red asset.tile_red_pastel_v1 --no-validate

# Approve for release
sakura bind status slot.tile.red approved --title title.sakura_match

# Remove binding
sakura bind unbind slot.ui.logo_title --title title.sakura_match
```

Wrappers from SakuraSoft root:

```bash
./shared/scripts/sakura-validate.sh
./shared/scripts/sakura-bind.sh list --title title.sakura_match
./shared/scripts/sakura-import.sh --title title.sakura_match
./shared/scripts/sakura-studio.sh   # http://127.0.0.1:8787/
```

## Import (Unity)

Copies bound masters into the title’s Unity project and writes a Resources manifest:

```bash
sakura import --title title.sakura_match
# → projects/sakura-match/Assets/Resources/Catalog/sakura_match/bindings.json
# → …/slots/slot_tile_*.png
```

Missing catalog PNGs are synthesized (pastel solids) unless `--no-generate`.

## Studio GUI

```bash
sakura studio --catalog /path/to/catalog
# open http://127.0.0.1:8787/
```

Card UI: preview assets, bind / approve / unbind, validate, import to Unity.
