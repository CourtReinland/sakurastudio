# Flow workstation (v0.9)

Flow is the **main surface** of Sakura Studio: one node = one player-facing **scene** (screen / level / cinematic / ending). Assets live **inside** the node.

## Model

```
[Title / Splash] ──Play──► [Level 1] ──then──► [Cinematic scene] ──choices──► …
                                  │
                                  └ assets: graphics · dialogue · cast · code refs
```

| Concept | On canvas | Inside node (+) |
|---------|-----------|-----------------|
| Scene / level / menu / ending | Node | — |
| Background, CG, gems, UI art | — | Graphics |
| On-screen / goal text | — | Text |
| Spoken lines | — | Dialogue (editable) |
| Cast present | — | Characters |
| Choices | — | Choices list |
| Shared engine code | Listed once in engine bar | Code refs (not duplicated) |

**Engine** is shown once above the canvas (Three.js / Unity pack). Per-node code only points at scene-specific controllers + shared engine note.

## Controls

| Action | How |
|--------|-----|
| Expand / collapse assets | **+ / −** on node |
| Move node | Drag body |
| Pan / zoom | Drag empty canvas · scroll |
| Connect A → B | **Drag from out →** onto target node (rubber-band), or **C** then out/in |
| Disconnect | × on outbound link in detail panel |
| Add scene | **+ Scene** or **N** |
| Splash slots | **Ensure splash slots** (bg, logo, buttons) auto-created |
| Save positions | **Save layout** → `studio.yaml` |
| Edit line | Expand → Save line |
| Open Unity / Blender / IDE | Expand → Code section → **Open** / **Unity** / **Blender** |

### Deep links (`title.yaml` → `exports`)

```yaml
exports:
  game_repo: ../sakura-match          # IDE / folder
  unity_project: projects/sakura-match
  blender_file: art/tea_house.blend
  unreal_project: /abs/path/MyGame
  code_paths:
    vn: ../sakura-match/src/ui
    title_ui: ../sakura-match/src/app
```

`POST /api/open` with `{ title_id, app: "unity"|"blender"|"ide"|"folder", key?, path? }`.

## APIs

- `GET /api/flow?title=…` — scene graph + nested assets  
- `POST /api/flow/scene` — create scene in `ggd.yaml`  
- `POST /api/flow/connect` / `disconnect` — progression edges  
- `POST /api/flow/layout` — positions  

## Compile pass

New scenes and edges write to catalog `ggd.yaml`. Next game export / agent compile reads that graph as source of truth for order and links.
