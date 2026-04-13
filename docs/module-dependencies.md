# Module Dependency Reference

> **Purpose:** Quickly identify what MAY need updating when changing a module.  
> **Format:** `module` → list of modules that import/use it

---

## Core Extractor (`core/extractor/`)

### `extractor.py`
**Used by:**
- `Main.py` (creates `Extractor` instance)
- `gui/extract_tab_widget.py` (imports for type hints)

### `atlas_processor.py`
**Used by:**
- `extractor.py`
- `preview_generator.py`

### `sprite_processor.py`
**Used by:**
- `extractor.py`
- `preview_generator.py`

### `animation_processor.py`
**Used by:**
- `extractor.py`

### `animation_exporter.py`
**Used by:**
- `animation_processor.py`
- `preview_generator.py`

### `frame_exporter.py`
**Used by:**
- `animation_processor.py`

### `frame_pipeline.py`
**Used by:**
- `animation_processor.py`
- `animation_exporter.py`
- `preview_generator.py`

### `frame_selector.py`
**Used by:**
- `frame_pipeline.py`

### `image_utils.py`
**Used by:**
- `animation_processor.py`
- `animation_exporter.py`
- `frame_exporter.py`
- `frame_pipeline.py`
- `frame_selector.py`
- `preview_generator.py`

### `preview_generator.py`
**Used by:**
- `extractor.py`

### `unknown_spritesheet_handler.py`
**Used by:**
- `extractor.py`

---

## Spritemap (`core/extractor/spritemap/`)

### `renderer.py` (`AdobeSpritemapRenderer`)
**Used by:**
- `extractor.py`
- `preview_generator.py`

### `sprite_atlas.py`
**Used by:**
- `renderer.py`

### `symbols.py`
**Used by:**
- `renderer.py`

### `normalizer.py`
**Used by:**
- `renderer.py`
- `gui/extract_tab_widget.py`

### `metadata.py`
**Used by:**
- `symbols.py`
- `gui/extract_tab_widget.py`

### `transform_matrix.py`
**Used by:**
- `renderer.py`
- `sprite_atlas.py`
- `symbols.py`

### `color_effect.py`
**Used by:**
- `sprite_atlas.py`
- `symbols.py`

---

## Core Generator (`core/generator/`)

### `atlas_generator.py`
**Used by:**
- `gui/generate_tab_widget.py`

**Imports from:**
- `core/optimizer/texture_compress.py` (GPU compression in `_save_output()`)
- `core/optimizer/constants.py` (TextureFormat, TextureContainer enums)

---

## Core Optimizer (`core/optimizer/`)

### `constants.py`
**Used by:**
- `optimizer.py`
- `texture_compress.py`
- `core/generator/atlas_generator.py`
- `gui/generate_tab_widget.py`
- `gui/optimize_tab_widget.py`
- `utils/combo_options.py`

### `optimizer.py`
**Used by:**
- `gui/optimize_tab_widget.py`

### `texture_compress.py`
**Used by:**
- `optimizer.py`
- `core/generator/atlas_generator.py`

---

## Core Editor (`core/editor/`)

### `editor_composite.py`
**Used by:**
- `animation_processor.py`
- `preview_generator.py`

---

## Parsers (`parsers/`)

### `parser_registry.py`
**Used by:**
- `atlas_processor.py`

### `base_parser.py`
**Used by:**
- All `*_parser.py` modules

### `parser_types.py`
**Used by:**
- `base_parser.py`
- `parser_registry.py`
- All `*_parser.py` modules

### `unknown_parser.py`
**Used by:**
- `unknown_spritesheet_handler.py`

### Individual parsers (`json_hash_parser.py`, `starling_xml_parser.py`, etc.)
**Used by:**
- `parser_registry.py` (auto-registered)

---

## Exporters (`exporters/`)

### `exporter_registry.py`
**Used by:**
- `core/generator/atlas_generator.py`

### `base_exporter.py`
**Used by:**
- All `*_exporter.py` modules

### `exporter_types.py`
**Used by:**
- `base_exporter.py`
- `exporter_registry.py`
- `core/generator/atlas_generator.py`

### Individual exporters (`json_hash_exporter.py`, `starling_xml_exporter.py`, etc.)
**Used by:**
- `exporter_registry.py` (auto-registered)

---

## Packers (`packers/`)

### `__init__.py` (exports `get_packer`, `pack`, etc.)
**Used by:**
- `core/generator/atlas_generator.py`

### `packer_registry.py`
**Used by:**
- `packers/__init__.py`

### `base_packer.py`
**Used by:**
- All `*_packer.py` modules

### `packer_types.py`
**Used by:**
- `base_packer.py`
- `packer_registry.py`
- `core/generator/atlas_generator.py`
- All `*_packer.py` modules

---

## GUI (`gui/`)

### `app_ui.py`
**Used by:**
- `Main.py`

### `base_tab_widget.py`
**Used by:**
- `extract_tab_widget.py`
- `generate_tab_widget.py`
- `editor_tab_widget.py`

### `extract_tab_widget.py`
**Used by:**
- `Main.py`

### `generate_tab_widget.py`
**Used by:**
- `Main.py`

### `editor_tab_widget.py`
**Used by:**
- `Main.py`

### `gui/extractor/processing_window.py`
**Used by:**
- `Main.py`

### `gui/extractor/override_settings_window.py`
**Used by:**
- `extract_tab_widget.py`

### `gui/extractor/animation_preview_window.py`
**Used by:**
- `Main.py`

### `gui/extractor/background_handler_window.py`
**Used by:**
- `unknown_spritesheet_handler.py`

### `gui/extractor/compression_settings_window.py`
**Used by:**
- `Main.py`

### `gui/extractor/enhanced_list_widget.py`
**Used by:**
- `extract_tab_widget.py`

### `gui/generator/animation_tree_widget.py`
**Used by:**
- `generate_tab_widget.py`

---

## Utilities (`utils/`)

### `app_config.py`
**Used by:**
- `Main.py`
- `gui/app_config_window.py`
- `gui/first_start_dialog.py`
- `gui/extractor/compression_settings_window.py`

### `settings_manager.py`
**Used by:**
- `Main.py`
- `extractor.py`
- `animation_processor.py`
- `preview_generator.py`
- `gui/settings_window.py`
- `gui/extractor/override_settings_window.py`
- `gui/extractor/compression_settings_window.py`

### `translation_manager.py`
**Used by:**
- `Main.py`
- Almost all GUI modules
- `extractor.py`
- `dependencies_checker.py`
- `update_checker.py`

### `utilities.py`
**Used by:**
- `Main.py`
- `extractor.py`
- `sprite_processor.py`
- `animation_exporter.py`
- `frame_exporter.py`
- `spritemap/renderer.py`
- `unknown_spritesheet_handler.py`
- `dependencies_checker.py`
- `gui/extract_tab_widget.py`
- `gui/generate_tab_widget.py`
- `gui/extractor/override_settings_window.py`
- `utils/FNF/character_data.py`

### `version.py`
**Used by:**
- `Main.py`
- `update_checker.py`
- `update_installer.py`
- `core/generator/atlas_generator.py`

### `combo_options.py`
**Used by:**
- `gui/app_ui.py`
- `gui/extract_tab_widget.py`
- `gui/generate_tab_widget.py`
- `gui/optimize_tab_widget.py`
- `gui/extractor/animation_preview_window.py`

### `duration_utils.py`
**Used by:**
- `gui/extract_tab_widget.py`
- `gui/extractor/override_settings_window.py`
- `gui/extractor/animation_preview_window.py`

### `resampling.py`
**Used by:**
- `core/extractor/image_utils.py`
- `core/extractor/animation_exporter.py`
- `gui/extractor/override_settings_window.py`
- `gui/extractor/animation_preview_window.py`

### `update_checker.py`
**Used by:**
- `Main.py`

### `update_installer.py`
**Used by:**
- `Main.py` (updater mode)
- `update_checker.py`

### `dependencies_checker.py`
**Used by:**
- `Main.py` (startup)

---

## FNF Utilities (`utils/FNF/`)

### `alignment.py`
**Used by:**
- `animation_processor.py`
- `gui/editor_tab_widget.py`

### `character_data.py`
**Used by:**
- `Main.py`

### `anim_utils.py`
**Used by:**
- `character_data.py`

### `engine_detector.py`
**Used by:**
- `character_data.py`

---

## Quick Impact Lookup

| If you change... | Check these files... |
|------------------|----------------------|
| `image_utils.py` | `animation_processor`, `animation_exporter`, `frame_exporter`, `frame_pipeline`, `frame_selector`, `preview_generator` |
| `frame_pipeline.py` | `animation_processor`, `animation_exporter`, `preview_generator` |
| `parser_types.py` | All parsers, `parser_registry`, `atlas_processor` |
| `exporter_types.py` | All exporters, `exporter_registry`, `atlas_generator` |
| `packer_types.py` | All packers, `packer_registry`, `atlas_generator` |
| `optimizer/constants.py` | `optimizer.py`, `texture_compress.py`, `atlas_generator`, `generate_tab_widget`, `optimize_tab_widget`, `combo_options` |
| `texture_compress.py` | `optimizer.py`, `atlas_generator` |
| `settings_manager.py` | `Main.py`, all extraction code, override windows |
| `translation_manager.py` | All GUI modules |
| `utilities.py` | Widespread - check grep results |
| `combo_options.py` | `app_ui`, `extract_tab_widget`, `generate_tab_widget`, `optimize_tab_widget`, `animation_preview_window` |
| `base_parser.py` | All parsers |
| `base_exporter.py` | All exporters |
| `base_packer.py` | All packers |
| `spritemap/renderer.py` | `extractor.py`, `preview_generator.py` |
| `spritemap/transform_matrix.py` | `renderer`, `sprite_atlas`, `symbols` |
| `duration_utils.py` | `extract_tab_widget`, `override_settings_window`, `animation_preview_window` |
| `resampling.py` | `image_utils`, `animation_exporter`, override/preview windows |
| `FNF/alignment.py` | `animation_processor`, `editor_tab_widget` |
