# ElevenLabs VO — Studio + game runtime

## Studio setup

1. Put your key in `SakuraSoft/.env`:

```bash
ELEVENLABS_API_KEY=your_key_here
```

2. Restart Studio:

```bash
./shared/scripts/sakura-studio.sh
```

3. **Dialogue** tab:
   - Assign ElevenLabs voices to speakers (use **▶ Preview** to audition)
   - Open a scene → edit line text → **Save text**
   - **Generate VO** → writes MP3 under catalog + optional game path

## Model: Eleven v3

Studio uses **`eleven_v3`** by default (set in each title’s `voices.yaml` as `model_id`, and as the client default).

v3 is the expressive model that understands **audio tags** in square brackets as *performance / style cues*, not words to speak.

### Audio tags (`[…]`)

Write stage direction in **square brackets** so v3 stylizes delivery:

```text
[whispers] We've been dating for half a year now.
[whispers] Looks like Tsukimori Greens. [concerned] This place is kinda creepy.
[sad] Then it happened.
```

| Keep | Drop / rewrite |
|------|----------------|
| `[whispers]` `[whispering]` `[concerned]` `[sad]` `[laughs]` … | Markdown bold `**…**` (stripped) |
| Multiple tags mid-line | Game notes `_(affinity: ren+2)_` (stripped) |
| Short stage parens `(softly)` → converted to `[softly]` | Affinity-style parens |

Pipeline (`prepare_tts_text`):

1. Collapse YAML line-breaks  
2. **Protect** existing `[tags]`  
3. Strip markdown / affinity notes  
4. Optionally convert short `(stage)` directions into `[stage]` tags  
5. Restore tags; ensure spacing so `]Word` → `] Word`  

Do **not** put spoken dialogue inside brackets — only style/direction.

## Where audio lives

| Location | Path |
|----------|------|
| Catalog (source of truth) | `catalog/assets/files/tea_house/audio/<scene>/<node>.mp3` |
| Voice map | `catalog/titles/sakura-tea-house/voices.yaml` |
| Game export | `$SAKURA_GAME_PUBLIC/audio/vo/<scene>/<node>.mp3` |

## Runtime pull (game app)

Studio exposes on-demand generation:

```
GET http://127.0.0.1:8787/api/tts/audio?title=title.sakura_tea_house&scene_id=a-visitor-at-dusk&node_id=arrival-3&generate=true
```

- If MP3 exists in catalog → returns it  
- If missing and `generate=true` → synthesizes with the speaker’s assigned voice, caches, exports to game root if configured  

### Example (Three.js / Capacitor)

```ts
async function ensureLineAudio(sceneId: string, nodeId: string): Promise<string> {
  const localPath = `audio/vo/${sceneId.replace(/-/g,'_')}/${nodeId.replace(/-/g,'_')}.mp3`;
  // 1) Prefer already-bundled / previously saved asset
  try {
    const head = await fetch(localPath, { method: 'HEAD' });
    if (head.ok) return localPath;
  } catch { /* continue */ }

  // 2) Ask Sakura Studio (dev machine / LAN) to generate + return bytes
  const studio = import.meta.env.VITE_SAKURA_STUDIO_URL ?? 'http://127.0.0.1:8787';
  const url =
    `${studio}/api/tts/audio?title=title.sakura_tea_house` +
    `&scene_id=${encodeURIComponent(sceneId)}` +
    `&node_id=${encodeURIComponent(nodeId)}` +
    `&generate=true`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();

  // 3) Runtime cache: object URL (web) or Capacitor Filesystem write (native)
  return URL.createObjectURL(blob);
}
```

For shipping builds, pre-generate VO in Studio (or CI) and commit/copy into `public/audio/vo/` so devices never need the API key.

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/voices` | List ElevenLabs voices on your account |
| `GET/PUT` | `/api/voice-map` | Character/speaker → voice_id |
| `PUT` | `/api/dialogue/line` | Edit line text |
| `POST` | `/api/tts/generate` | Generate + cache MP3 |
| `GET` | `/api/tts/audio?...&generate=` | Play / runtime fetch |
