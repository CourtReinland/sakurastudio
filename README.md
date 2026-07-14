# Sakura Studio

**Company OS for Sakura Soft** — structured game catalog, agent-safe rebinding, Unity import, and a thin control-surface GUI.

Solo founder + AI agents: stop swapping “image 8 for 201.” Use stable IDs.

```text
Library asset  →  Binding  →  Slot  →  GGD / runtime
```

## Repo layout

| Path | Purpose |
|------|---------|
| [`catalog/`](./catalog/) | Source of truth: brands, characters, assets, titles, GGD, slots, bindings |
| [`tools/sakura/`](./tools/sakura/) | CLI: `validate`, `bind`, `import`, `studio` |
| [`shared/scripts/`](./shared/scripts/) | Shell wrappers |
| [`docs/`](./docs/) | Studio design notes (GDD gap analysis, roadmap) |
| [`projects/`](./projects/) | Optional game runtimes (e.g. Unity match prototype) |

## Quick start

```bash
cd tools/sakura
uv venv && uv pip install -e .

# from repo root
./shared/scripts/sakura-validate.sh
./shared/scripts/sakura-studio.sh    # http://127.0.0.1:8787/
```

### CLI

```bash
sakura validate --catalog catalog
sakura bind list --title title.sakura_match
sakura bind set slot.tile.red asset.tile_red_pastel_v2 --title title.sakura_match
sakura import --title title.sakura_match
sakura studio --catalog catalog
```

## Related games

| Product | Repo | Catalog title |
|---------|------|----------------|
| Sakura Tea House (Three.js + otome Ch.1) | [CourtReinland/sakura-match](https://github.com/CourtReinland/sakura-match) | `title.sakura_tea_house` |
| Unity match-3 sketch | local `projects/sakura-match` | `title.sakura_match` |

## Design

See [`catalog/SCHEMA.md`](./catalog/SCHEMA.md) and [`docs/GDD-DASHBOARD-GAP.md`](./docs/GDD-DASHBOARD-GAP.md).

## License

Private / all rights reserved unless noted otherwise.
