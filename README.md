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
| [`docs/`](./docs/) | Studio design notes (GDD gap analysis, Flow workstation) |
| [`integrations/unity-sakura-match/`](./integrations/unity-sakura-match/) | Unity bridge scripts + sample Resources catalog |
| `projects/` | Optional local game checkouts (gitignored; not vendored) |

## Quick start

```bash
cd tools/sakura
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# from repo root
./shared/scripts/sakura-validate.sh
./shared/scripts/sakura-studio.sh    # http://127.0.0.1:8787/
```

### CLI

```bash
sakura validate --catalog catalog
sakura bind list --title title.sakura_match
sakura bind set slot.tile.red asset.tile_red_pastel_v2 --title title.sakura_match
# Unity import needs a local Unity tree (see integrations/unity-sakura-match/README.md)
sakura import --title title.sakura_match --unity-root /path/to/UnityProject
sakura studio --catalog catalog

# Refresh Tea House content from a sakura-match clone
sakura sync-tea-house --catalog catalog --source /path/to/sakura-match
```

## Related games

| Product | Repo | Catalog title |
|---------|------|----------------|
| Sakura Tea House (Three.js + otome Ch.1) | [CourtReinland/sakura-match](https://github.com/CourtReinland/sakura-match) | `title.sakura_tea_house` |
| Midnight Par | [CourtReinland/nightmaregolf](https://github.com/CourtReinland/nightmaregolf) | `title.midnight_par` |
| Unity match-3 sketch | external checkout → `projects/sakura-match` or `SAKURA_UNITY_ROOT` | `title.sakura_match` |

## Studio · Flow, Assets, Imagine & style board

- **Flow ★** — scene-centric node graph (rubber-band connect, splash slots). [`docs/FLOW-WORKSTATION.md`](./docs/FLOW-WORKSTATION.md)  
- **Assets ✦** — Grok Build game-asset skill suite → catalog. [`docs/STUDIO-GAME-ASSETS.md`](./docs/STUDIO-GAME-ASSETS.md)  
- **Canvas** — Grok Imagine style canvas: mood-board refs, generate / iterate, shared style lock  
- **Swaps** — drag/drop rebinds, file drop, Imagine generate/edit  
- **Dialogue** — line ledger + voice assignment  
- **Style board** — per-title style lock in `studio.yaml` (ON/OFF; shared by Canvas + Swaps)  

Set `XAI_API_KEY` (and optionally `ELEVENLABS_API_KEY`) in `.env`. For Export → Game set `SAKURA_GAME_ROOT`.

## Design

See [`catalog/SCHEMA.md`](./catalog/SCHEMA.md), [`docs/GDD-DASHBOARD-GAP.md`](./docs/GDD-DASHBOARD-GAP.md),
[`docs/FLOW-WORKSTATION.md`](./docs/FLOW-WORKSTATION.md), [`docs/STUDIO-FLOW.md`](./docs/STUDIO-FLOW.md),
[`docs/STUDIO-GAME-ASSETS.md`](./docs/STUDIO-GAME-ASSETS.md),
and [`docs/STUDIO-IMAGINE.md`](./docs/STUDIO-IMAGINE.md).

## License

Private / all rights reserved unless noted otherwise.
