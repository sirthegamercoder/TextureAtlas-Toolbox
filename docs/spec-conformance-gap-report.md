# Spec-Conformance Gap Report

> **Date:** April 21, 2026
> **Scope:** All parsers (`src/parsers/`) and exporters (`src/exporters/`) audited against their official format specifications.
> **Mode:** Audit only — no code changes were made while producing this report.
> **Caveat:** Line numbers are approximate (taken from a research pass) and will be re-verified before any implementation work.

---

## Summary

| Format | Parser | Exporter | Highest Severity |
| --- | --- | --- | --- |
| Aseprite (JSON sheet) | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ DONE |
| TexturePacker plist (Cocos2D) | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ resolved |
| UIKit plist | n/a | ✓ resolved (v3.0.0) | ✓ resolved |
| Godot `.tpsheet` | n/a | ✓ resolved (v3.0.0) | ✓ resolved |
| Spine `.atlas` | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ resolved |
| Phaser 3 (JSON) | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ resolved |
| Adobe Animate Spritemap | ✓ resolved (v3.0.0) | n/a | ✓ resolved |
| CSS (legacy) | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ resolved |
| Egret2D | gaps | ✓ resolved (v3.0.0) | 🔴 HIGH |
| TXT (TexturePacker) | gaps | ✓ resolved (v3.0.0) | 🔴 HIGH |
| Starling / Sparrow XML | ✓ resolved | ✓ resolved | ✓ |
| libGDX `.atlas` | ✓ resolved (v3.0.0) | ✓ resolved (v3.0.0) | ✓ resolved |
| JSON Hash / JSON Array | ✓ resolved | ✓ resolved | ✓ |
| Unity `.tpsheet` | ✓ resolved | ✓ resolved | ✓ |
| TexturePacker generic XML | minor | minor | 🟢 LOW |
| Paper2D `.paper2dsprites` | ok | minor | 🟢 LOW |

---

## 🔴 HIGH priority — data loss or spec violations

### ✓ Aseprite — [aseprite_parser.py](../src/parsers/aseprite_parser.py) + [aseprite_exporter.py](../src/exporters/aseprite_exporter.py) — RESOLVED in v3.0.0

Verified directly against `aseprite/src/app/doc_exporter.cpp` (`DocExporter::createDataFile`). All findings below were resolved; one was a misreading of the upstream spec.

- ✓ **`meta.slices[]`** — full round-trip: `name`, `color`, `data`, `properties`, and `keys[]` with `bounds`, optional `center`, optional integer `pivot{x,y}`.
- ✓ **`meta.layers[]`** — full round-trip via explicit `AsepriteExportOptions.layers`: `name`, `group`, `opacity`, `blendMode`, user data, and `cels[]` (with `frame`, `opacity`, `zIndex`, user data).
- ✓ **`frameTags[].repeat`** — emitted as a JSON string when > 0, omitted when 0 (matches `<< "\"repeat\": \"" << tag->repeat() << "\""`).
- ✓ **`frameTags[].direction`** — normalized to one of `forward`, `reverse`, `pingpong`, `pingpong_reverse`. Hyphenated and mixed-case spellings accepted on parse; unknown values warn and fall back to `forward`.
- 🟢 **`meta.scale` is a JSON string** — confirmed correct per upstream (`os << "  \"scale\": \"1\""`). The audit finding was wrong; default is now an explicit `scale_string="1"`.
- 🟢 **Frame `pivot`** — Aseprite never emits `pivot` on a frame entry; `pivot` is only on slice keys, with **integer** `{x, y}` (not normalized 0–1). Handled.
- ✓ **Per-sprite `duration`** — sprites carry their own duration; default fills missing values.
- ✓ **`rotated` field** — Aseprite's packer never rotates samples and always emits `rotated: false`. New `strict_aseprite=True` mode forces this for byte-compatibility; default preserves our rotation extension.
- ✓ **`json-array` output** — `AsepriteExportOptions.json_array=True` emits `frames` as a list with `filename` per entry.
- ✓ Frame-tag user data (`color`, `data`, `properties`) round-trips via per-sprite `animation_color`/`animation_data` fields.

Tests: [tests/test_aseprite_spec.py](../tests/test_aseprite_spec.py) (11 tests — parser, exporter, full round-trip).

### TexturePacker plist (Cocos2D) — [plist_xml_parser.py](../src/parsers/plist_xml_parser.py) + [plist_exporter.py](../src/exporters/plist_exporter.py)

**✓ Resolved in v3.0.0.** Parser and exporter rewritten against `cocos2d-x/cocos/2d/CCSpriteFrameCache.cpp` and TexturePacker's plist exporter docs. All four documented format versions (`format: 0`, `1`, `2`, `3`) round-trip; the parser auto-detects the version via `metadata.format` and dispatches to the correct decode path (Zwoptex scalars / TexturePacker v2 string-rects / TexturePacker v3 `textureRect`+`textureRotated`). Frame `aliases` and polygon-mesh data (`triangles`, `vertices`, `verticesUV`, `anchor`) are preserved verbatim. Page metadata (`pixelFormat`, `premultiplyAlpha`, `smartupdate`, `target`, `realTextureFileName`) is captured into `ParseResult.metadata["plist"]` and re-emitted on export. The exporter defaults to format 3 with `target: cocos2d`; new `PlistExportOptions` fields (`pixel_format`, `premultiply_alpha`, `smartupdate_hash`, `target_name`, `strict_spec`, `append_png_extension`) cover the rest of the TexturePacker schema. Frame-key `.png` doubling is fixed (extension append now only happens for v2 and only when no image extension is already present). Covered by [test_plist_spec.py](../tests/test_plist_spec.py) (14 tests).

### UIKit plist + Godot `.tpsheet` (rotation impossible)

**✓ Resolved in v3.0.0.** Both [uikit_plist_exporter.py](../src/exporters/uikit_plist_exporter.py) and [godot_exporter.py](../src/exporters/godot_exporter.py) now raise `FormatError(UNSUPPORTED_FORMAT, ...)` from `build_metadata` when a rotated sprite arrives, instead of silently swapping `w`/`h` and producing metadata that no longer matches the atlas image. The dimension-swap branches were removed, so unrotated sprites always emit their natural `w`/`h`. The capability classification now lives in `exporters.exporter_types.FORMATS_SUPPORTING_ROTATION` and is reachable from the GUI (which already disables the rotation checkbox for these formats) and the new `BaseExporter.supports_rotation()` classmethod.

### Spine `.atlas` — [spine_parser.py](../src/parsers/spine_parser.py) + [spine_exporter.py](../src/exporters/spine_exporter.py)

**✓ Resolved in v3.0.0.** [SpineAtlasParser](../src/parsers/spine_parser.py) is now a thin alias around [GdxAtlasParser](../src/parsers/gdx_parser.py) (the Spine runtime atlas reader is a direct port of libGDX's `TextureAtlasData`, so they share one implementation). The exporter rewrite emits the modern `bounds:` / `offsets:` layout by default with `SpineExportOptions.modern_format=False` falling back to the legacy quadruple. Numeric `rotate:` degrees, page metadata (`size`, `format`, `filter`, `repeat`, `pma`), `split:` / `pad:` ninepatch arrays, and arbitrary integer custom name/value fields all round-trip. Covered by [test_spine_spec.py](../tests/test_spine_spec.py) (16 tests).

**Refined 2026-04-23.** Compared against the Spine 4.2 reference atlas, the modern emit now omits `offsets:`, `rotate:`, and `index:` lines whenever they would carry their default values (untrimmed sprite, unrotated, ungrouped region with `index = -1`). This matches official Spine output byte-for-byte and avoids polluting hand-written atlases on round-trip. Parser still accepts the verbose form.

### Phaser 3 — [phaser3_parser.py](../src/parsers/phaser3_parser.py) + [phaser3_exporter.py](../src/exporters/phaser3_exporter.py)

**✓ Resolved in v3.0.0.** Parser and exporter rewritten against `Phaser.Loader.FileTypes.MultiAtlasFile`, `Phaser.Textures.Parsers.JSONArray`, and `Phaser.Textures.Parsers.JSONHash`. All three documented schema variants are now first-class: the multi-atlas wrapper (`textures[]` with per-page `image`/`format`/`size`/`scale`/`frames`), the JSONArray single-atlas form (`frames: [...]`), and the JSONHash form (`frames: {...}` keyed by filename). The parser auto-detects the variant, walks every page in `textures[]`, and tags each sprite with its source `page` so multi-page atlases survive a load/save cycle. Per-frame `pivot` and `anchor` keys are decoded into `pivotX`/`pivotY`. Top-level `meta` (`app`, `version`, `smartupdate`, `related_multi_packs`) is captured into `ParseResult.metadata["phaser3"]`. The exporter defaults to the multi-atlas form; new `Phaser3ExportOptions` fields (`multiatlas`, `frames_as_array`, `related_multi_packs`, `smartupdate_hash`, `include_pivot`, `strict_spec`) cover the remaining schema knobs. Covered by [test_phaser3_spec.py](../tests/test_phaser3_spec.py) (16 tests).

**Refined 2026-04-23.** Watermark now mirrors the JSON Hash / JSON Array convention: `meta.app = "TextureAtlas Toolbox (<version>)"` carries the toolbox identifier and `meta.version = "1.0"` keeps the TexturePacker schema indicator that some Phaser/PixiJS loaders inspect. Previously the toolbox version was being written into `meta.version` directly, which broke the schema field's documented semantics.

### Adobe Animate Spritemap — [spritemap_parser.py](../src/parsers/spritemap_parser.py)

**✓ Resolved in v3.0.0.** Targets both Adobe Animate's stock "Texture Atlas" exporter and the [Better Texture Atlas](https://github.com/Dot-Stuff/BetterTextureAtlas) (BTA) extension by Dot-Stuff in one pass. `parse_file` now discovers every sibling `spritemap*.json` (the stock single `spritemap.json` and BTA's contiguous `spritemap1.json` ... `spritemapN.json` overflow pages), reads each page's `ATLAS.SPRITES` (both `SPRITE`-wrapped and unwrapped shapes), tags each sprite with its 1-indexed `page` so multi-sheet exports survive a load/save, and exposes the per-page `meta` block (with `meta.scale` and BTA's `meta.resolution` both surfaced). Variant detection runs off `meta.app` (BTA appends `(Better TA Extension)`), the presence of a sibling `metadata.json`, or the presence of a `LIBRARY/` external-symbol directory. Cross-links every `ASI` / `ATLAS_SPRITE_instance` reference in `Animation.json` against the page index and records unresolved names without failing the parse. The legacy `extract_names` path and `SpriteAtlas` extractor are unchanged. Covered by [test_spritemap_spec.py](../tests/test_spritemap_spec.py) (15 tests).

### CSS (legacy) — [css_legacy_parser.py](../src/parsers/css_legacy_parser.py)

**✓ Resolved in v3.0.0** (parser side). The parser now reads `transform: rotate(<deg>)` markers (any 90 degree multiple of ±90 / ±270 sets `rotated = True` and the recorded `width` / `height` are swapped back to the source orientation) and the `margin-left` / `margin-top` trim offsets emitted by SpriteSmith / Glue / sprity (surfaced as `frameX` / `frameY`, with `frameWidth` / `frameHeight` reconstructed from the trim). The CSS exporter already emits both, so the format now round-trips. Also accepts the long form `background-image: url(...); background-position: ...` in addition to the `background:` shorthand.

### Egret2D — [egret2d_exporter.py](../src/exporters/egret2d_exporter.py)

**✓ Resolved in v3.0.0** (exporter side). Exporter now raises `FormatError(UNSUPPORTED_FORMAT, ...)` when given a rotated sprite, so the silent dim-swap data-loss bug is gone. Parser-side trim metadata (`offX`, `offY`, `sourceW`, `sourceH`) remains a separate gap.

### TXT — [txt_exporter.py](../src/exporters/txt_exporter.py)

**✓ Resolved in v3.0.0** (plain TXT exporter). Now raises `FormatError(UNSUPPORTED_FORMAT, ...)` when given a rotated sprite. Reading the FNF community extended TXT (extra columns for trim/rotation) remains a separate parser gap.

---

## 🟡 MEDIUM priority — missing standard fields / round-trip loss

### Starling / Sparrow XML — [starling_xml_parser.py](../src/parsers/starling_xml_parser.py) + [starling_xml_exporter.py](../src/exporters/starling_xml_exporter.py)

**✓ Resolved in v3.0.0.** Parser surfaces every documented attribute on each SubTexture (`pivotX`, `pivotY`, plus the HaxeFlixel `flipX` / `flipY` extension) and exposes the root-level `imagePath`, Sparrow v1 `format`, and Starling 2.x `scale` values through `ParseResult.metadata["starling"]`. Exporter gains `StarlingExportOptions.always_include_frame_data` (force-emit `frameX/Y/Width/Height` on every region) and `propagate_pivot_to_sequence` (back-fill the first declared pivot across an animation strip). Sparrow-compatible mode continues to drop Starling-only attributes for maximum cross-engine portability.

### libGDX `.atlas` — [gdx_parser.py](../src/parsers/gdx_parser.py) + [spine_exporter.py](../src/exporters/spine_exporter.py)

**✓ Resolved in v3.0.0.** Parser captures full page metadata in `ParseResult.metadata["gdx"]["pages"]`, parses `split:` / `pad:` ninepatch arrays, preserves numeric `rotate:` degrees, retains arbitrary integer custom name/value pairs (libGDX's `names[]`/`values[]` extension), and supports multi-page atlases. The shared exporter exposes `SpineExportOptions.modern_format` (default `True`) and `strict_spec` for spec-only output.

### JSON Hash + JSON Array — [json_hash_exporter.py](../src/exporters/json_hash_exporter.py) + [json_array_exporter.py](../src/exporters/json_array_exporter.py)

**✓ Resolved in v3.0.0.** Both parsers now expose a `parse_file` classmethod returning `ParseResult` with the full source `meta` block and `meta.frameTags` captured under `metadata["json"]`, and the per-frame `trimmed` flag is read back instead of being silently recomputed downstream. Both exporters gained `emit_durations` (per-frame `duration` copied from sprites when present), `frame_tags` (emitted as `meta.frameTags`), and `extra_meta` (passes through arbitrary meta fields such as Phaser's `related_multi_packs` or TexturePacker's `smartupdate`). `parse_file` rejects malformed files (missing or wrong-type `frames`) with `FormatError(INVALID_FORMAT, ...)`.

**Refined 2026-04-23.** Watermark separated from schema indicator after comparing against the canonical TexturePacker output (`phaser3-examples/.../megaset-0.json`). `meta.app` carries `TextureAtlas Toolbox (<version>)` (soft watermark), `meta.version` keeps `"1.0"` (TexturePacker JSON Hash schema version that loaders such as Phaser, PixiJS and Cocos branch on). Removed the redundant `meta.generator` field that duplicated this information.

### Unity `.tpsheet` — [texture_packer_unity_parser.py](../src/parsers/texture_packer_unity_parser.py) + [unity_exporter.py](../src/exporters/unity_exporter.py)

**✓ Resolved in v3.0.0.** Parser now reads the optional pivot columns when present and surfaces the `:format`, `:texture`, and `:size` headers through `ParseResult.metadata["unity"]` via a new `parse_file` classmethod. Exporter gains `UnityExportOptions.pivot_mode` (`"always"` / `"never"` / `"auto"`); `"auto"` inspects the input and only emits the pivot columns when at least one sprite carries an explicit pivot, so a five-column source round-trips back to a five-column output. `format_version` was already configurable. The legacy `include_pivot` boolean still works when `pivot_mode` is left `None`.

### CSS exporter — [css_exporter.py](../src/exporters/css_exporter.py)

**✓ Resolved in v3.0.0.** Trim is now encoded via `background-position` by default (container sized to `frameWidth` / `frameHeight`, background offset shifted by `-frameX` / `-frameY`), matching SpriteSmith / sprity / Glue conventions. The legacy `margin-left` / `margin-top` hack — which pushed the *box* around in flow layout without ever shifting the background image — is still reachable via `CssExportOptions.trim_mode="margin"`. Rotation now emits `transform-origin: 0 0` plus a compensating `translateY(<atlas_w>px) rotate(-90deg)` so the rotated content stays in its layout slot at the displayed (post-rotation) size, removing the centre-pivot ambiguity that previously caused double-rotation in some pipelines; the legacy centre-pivoted geometry remains available via `rotation_mode="legacy-center"`, and `rotation_mode="none"` skips the transform entirely (e.g. when the consumer handles rotation in JS / shaders). A small `/* tat: x=N y=N w=N h=N [frameX/Y/W/H=N] [rotated=1] */` round-trip comment is emitted by default and read by the legacy CSS parser, restoring lossless geometry that the spec-correct mode would otherwise hide. The parser also distinguishes the new top-left + `translateY` rotation geometry from the legacy bare `rotate(...)` so untagged CSS files from either era still parse correctly.

---

## 🟢 LOW priority — cosmetic / informational

- TexturePacker generic XML: ✓ resolved v3.0.0 — parser flags conflicting `n` / `name` pairs and unrecognised `r=` values via `ParseResult` warnings, captures attribute style and root metadata under `metadata["texturepacker_xml"]`; exporter gains `name_attribute` (`"n"` / `"name"`) and `include_xml_declaration`.
- Paper2D: ✓ resolved v3.0.0 — exporter gains `Paper2DExportOptions.pivot_mode` (`"always"` / `"never"` / `"auto"`); `"auto"` only writes `pivot` for frames whose source sprite carried an explicit `pivotX` / `pivotY`, so a no-pivot atlas round-trips back to a no-pivot atlas. Legacy `include_pivot` still works when `pivot_mode` is left `None`. Parser gains a `parse_file` classmethod that captures the source `meta` block under `ParseResult.metadata["paper2d"]` and only attaches `pivotX` / `pivotY` to sprites whose source frame declared a `pivot`.
- Starling parser: HaxeFlixel `flipX` / `flipY` extension ignored. ✓ resolved v3.0.0 — surfaced as boolean fields on each sprite when present.
- Aseprite: ✓ resolved v3.0.0 — rotation direction is now documented in both the parser class docstring and the exporter's `_build_frame_entry` docstring: when `rotated: true` the atlas sample is rotated **90° clockwise** relative to the source frame (TexturePacker convention inherited by Aseprite), so a consumer rotates **90° counter-clockwise** to restore the source orientation.
- TXT parser: ✓ resolved v3.0.0 — `parse_file` now surfaces malformed lines (wrong separator count, missing coordinates, non-integer coordinates) as `ParseResult` warnings carrying line number and offending content. Lines without `" = "` (comments / blank-ish noise) remain unreported because they were never sprite data. The legacy `parse_txt_packer` helper keeps its silent-skip behaviour for backwards compatibility; an internal `_parse_lines` helper returns the `(sprites, warnings)` pair.


---

## Cross-cutting observations

### Rotation in formats that have no rotation field

**✓ Resolved in v3.0.0.** UIKit plist, Godot `.tpsheet`, Egret2D, and plain TXT cannot represent a rotated sprite. Their exporters now raise `FormatError(UNSUPPORTED_FORMAT, ...)` from `build_metadata` rather than silently swap `w`/`h`. The capability classification lives at `exporters.exporter_types.FORMATS_SUPPORTING_ROTATION` (re-exported into the GUI and reachable through `BaseExporter.supports_rotation()`) so the GUI's rotation checkbox, the packer, and the exporters all draw from one source of truth. CSS retains rotation support via `transform: rotate(-90deg)` and the parser now reads it back. Covered by [test_rotation_impossible_formats.py](../tests/test_rotation_impossible_formats.py) (16 tests).

### Page-level metadata is dropped almost everywhere

**✓ Largely resolved in v3.0.0.** Spine and libGDX now round-trip full page metadata via `ParseResult.metadata["gdx"]["pages"]`, and Starling's root `format` and `scale` round-trip via `ParseResult.metadata["starling"]`. Remaining work is limited to non-Spine/Starling formats whose specs do not define a comparable metadata surface.

### Optional metadata blocks are inconsistent

| Format | Meta block in spec | Parser reads | Exporter writes |
| --- | --- | --- | --- |
| Phaser 3 | yes | no | yes (with non-spec custom fields) |
| Egret2D | no | n/a | no |
| CSS | n/a | n/a | comments only |
| TXT | optional | no | comments only |

### Round-trip fidelity (parse → in-memory → export → re-parse)

| Format | Estimated fidelity |
| --- | --- |
| Phaser 3 (single texture) | ~90% |
| TexturePacker XML | ~95% (round-trips attribute style, atlas size, image path) |
| CSS (legacy) | ~100% (round-trips trim, rotation, and atlas-region size via `/* tat: ... */` marker) |
| JSON Hash / Array | ~100% (round-trips `frameTags`, per-frame `duration`, `trimmed`, arbitrary `meta` extras) |
| Unity `.tpsheet` | ~100% (round-trips optional pivot columns and header metadata) |
| Starling XML | ~100% (round-trips `pivotX/Y`, `scale`, `format`, flip extension) |
| libGDX `.atlas` | ~80% (loses page metadata, ninepatch) |
| Aseprite | ~60% (loses slices, layers, repeat, pivot) |
| Spine `.atlas` | ~45% (modern format breaks immediately) |
| Adobe Animate Spritemap | n/a (extract-only) |
| Egret2D / TXT / UIKit / Godot (rotated content) | broken — wrong orientation after round-trip |

---

## Suggested implementation order

| # | Format | Why first |
| --- | --- | --- |
| 1 | **Aseprite** | Largest single-format gap (slices, layers, repeat, direction, pivot, scale type). |
| 2 | **Spine `.atlas`** | Modern 4.1+ totally broken — anyone on a recent Spine version cannot use us. |
| 3 | **TexturePacker plist (Cocos2D v3)** | Common format, format-version handling currently wrong. |
| 4 | **Phaser 3 multi-atlas** | Phaser is mainstream; multi-page is a real use case. |
| 5 | **Rotation-impossible formats** (UIKit / Godot / Egret2D / TXT) | One coordinated change: teach the packer not to rotate when the chosen output format cannot represent rotation. |
| 6 | **Adobe Animate Spritemap** | Add `spritemap.json` ATLAS/SPRITES reader and link to `Animation.json` by symbol name. |
| 7 | **Starling pivot/scale + libGDX page metadata + ninepatch** | ✓ resolved v3.0.0. |
| 8 | **CSS legacy / TXT extended / JSON `frameTags`+`duration`** | Round-trip fidelity cleanup. |
