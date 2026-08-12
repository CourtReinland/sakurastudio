# Unity bridge (sakura-match sketch)

Copy these into a Unity project's `Assets/Scripts/` (and Resources) after `sakura import`.

The live Unity tree is **not vendored** in this repo. Conventionally check it out at
`projects/sakura-match` (gitignored), or point import at any Unity root:

```bash
export SAKURA_UNITY_ROOT=/path/to/your/UnityProject
sakura import --title title.sakura_match
# or: sakura import --title title.sakura_match --unity-root /path/to/UnityProject
```

| File | Place in Unity |
|------|----------------|
| `CatalogBindings.cs` | `Assets/Scripts/Data/` |
| `Tile.cs` | `Assets/Scripts/Core/` (or merge changes) |
| `ResourcesCatalog/` | Sample output of `Assets/Resources/Catalog/` after import |
