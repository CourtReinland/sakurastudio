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

# Refresh Tea House content from a sakura-match clone
sakura sync-tea-house --catalog catalog --source /path/to/sakura-match
```

## Related games

| Product | Repo | Catalog title |
|---------|------|----------------|
| Sakura Tea House (Three.js + otome Ch.1) | [CourtReinland/sakura-match](https://github.com/CourtReinland/sakura-match) | `title.sakura_tea_house` |
| Unity match-3 sketch | local `projects/sakura-match` | `title.sakura_match` |

## Studio · Flow, Imagine & style board

- **Flow ★** — node graph of story branches, dialogue choices, art slots/assets, and engine (rearrange + save layout). See [`docs/STUDIO-FLOW.md`](./docs/STUDIO-FLOW.md).  
- **Swaps** — drag/drop rebinds, local file import, **Grok Imagine** generate/edit.  
- **Style board** — per-title style lock in `studio.yaml` (ON/OFF).  

Set `XAI_API_KEY` in `.env`. Write-ups: [`docs/STUDIO-FLOW.md`](./docs/STUDIO-FLOW.md), [`docs/STUDIO-IMAGINE.md`](./docs/STUDIO-IMAGINE.md).

## Design

See [`catalog/SCHEMA.md`](./catalog/SCHEMA.md), [`docs/GDD-DASHBOARD-GAP.md`](./docs/GDD-DASHBOARD-GAP.md), [`docs/STUDIO-FLOW.md`](./docs/STUDIO-FLOW.md), and [`docs/STUDIO-IMAGINE.md`](./docs/STUDIO-IMAGINE.md).

## License

Private / all rights reserved unless noted otherwise.
