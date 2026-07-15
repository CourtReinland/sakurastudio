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
   - Assign ElevenLabs voices to `ren` / `mizu` / `akira` / `you` / `narrator`
   - Open a scene → edit line text → **Save text**
   - **Generate VO** → writes MP3 under catalog + optional game path

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
