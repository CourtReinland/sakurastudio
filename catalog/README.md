# Sakura Soft Catalog

Structured product truth for every title: brands, characters, assets, slots, bindings, GGD, and agent jobs.

| Start here | |
|------------|--|
| Design | [`SCHEMA.md`](./SCHEMA.md) |
| Machine contracts | [`schemas/`](./schemas/) |
| Live title | [`titles/sakura-match/`](./titles/sakura-match/) |
| Otome template | [`titles/_examples/otome-skeleton/`](./titles/_examples/otome-skeleton/) |

## Mental model

```text
Library asset  →  Binding  →  Slot  →  GGD node / runtime
   (file)         (wire)     (hole)     (meaning)
```

**Never** tell agents “swap image 8.”  
**Always** rebind: `slot.*` → `asset.*`.

## Quick rebind example

```yaml
# titles/sakura-match/bindings.yaml
- slot_id: slot.tile.red
  asset_id: asset.tile_red_pastel_v2   # new library entry, not overwrite in place
  status: review
```

## Schema version

See `_meta/catalog.yaml` → `schema_version` (currently `1.0.0`).

## Validate

```bash
# From SakuraSoft root (after one-time install)
./shared/scripts/sakura-validate.sh

# Or:
tools/sakura/.venv/bin/sakura validate --catalog catalog

# Flags: --title title.sakura_match  --examples  --strict  --release
```

## Bind

```bash
./shared/scripts/sakura-bind.sh list --title title.sakura_match
./shared/scripts/sakura-bind.sh set slot.tile.red asset.tile_red_pastel_v1 \
  --title title.sakura_match --status review --by human.brian
./shared/scripts/sakura-bind.sh status slot.tile.red approved --title title.sakura_match
```

## Import + Studio

```bash
./shared/scripts/sakura-import.sh --title title.sakura_match
./shared/scripts/sakura-studio.sh
# → http://127.0.0.1:8787/
```

Unity runtime loads `Resources/Catalog/sakura_match/bindings.json` via `CatalogBindings`.

Install once:

```bash
cd tools/sakura && uv venv && uv pip install -e .
```
