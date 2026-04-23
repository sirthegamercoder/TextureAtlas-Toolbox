#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Exporter for TexturePacker JSON Hash format.

Generates JSON metadata with frames as an object/hash where sprite names
are keys mapping to frame data. This is the most common TexturePacker format.

Output Format:
    ```json
    {
        "frames": {
            "sprite_01": {
                "frame": {"x": 0, "y": 0, "w": 64, "h": 64},
                "rotated": false,
                "trimmed": true,
                "spriteSourceSize": {"x": 2, "y": 2, "w": 60, "h": 60},
                "sourceSize": {"w": 64, "h": 64},
                "pivot": {"x": 0.5, "y": 0.5}
            }
        },
        "meta": {
            "image": "atlas.png",
            "size": {"w": 512, "h": 512},
            "format": "RGBA8888",
            "scale": "1"
        }
    }
    ```
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from exporters.base_exporter import BaseExporter
from exporters.exporter_registry import ExporterRegistry
from exporters.exporter_types import (
    ExportOptions,
    GeneratorMetadata,
    PackedSprite,
)
from utils.version import APP_VERSION


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tga")


@dataclass
class JsonHashExportOptions:
    """JSON Hash-specific export options.

    Attributes:
        include_pivot: Include pivot point data (default center 0.5, 0.5).
        include_meta: Include meta block with image/size/format info.
        format_string: Pixel format string for meta block (e.g., "RGBA8888").
        scale_string: Scale string for meta block (e.g., "1").
        app_name: Application name for meta.app field.
        app_name: Identifier written to ``meta.app``. The TextureAtlas
            Toolbox version is appended in parentheses as a soft watermark
            so downstream consumers can identify the producing tool while
            ``meta.version`` continues to carry the TexturePacker schema
            version (which Phaser / PixiJS / Cocos may inspect).
        app_version: TexturePacker schema version written to
            ``meta.version``. Defaults to ``"1.0"`` to match TexturePacker's
            current default JSON Hash output.
        append_extension: When True (the TexturePacker default that Phaser /
            PixiJS / Cocos Creator all expect), append `.png` to frame keys
            that do not already carry a known image extension.
        emit_durations: When True, copy each sprite's `duration` field
            (milliseconds) into the per-frame entry. Aseprite and several
            Phaser pipelines use this to drive playback timing.
        frame_tags: Optional list of frame-tag dicts to emit as
            `meta.frameTags`. Each entry should provide `name`, `from`,
            `to`, and `direction` keys, matching Aseprite's schema.
        extra_meta: Optional dict merged into the `meta` block (after the
            built-in fields). Useful for round-tripping `related_multi_packs`,
            `smartupdate`, or other Phaser/TexturePacker extras captured by
            the parser.
    """

    include_pivot: bool = True
    include_meta: bool = True
    format_string: str = "RGBA8888"
    scale_string: str = "1"
    app_name: str = "TextureAtlas Toolbox"
    app_version: str = "1.0"
    append_extension: bool = True
    emit_durations: bool = True
    frame_tags: List[Dict[str, Any]] = None  # type: ignore[assignment]
    extra_meta: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.frame_tags is None:
            self.frame_tags = []
        if self.extra_meta is None:
            self.extra_meta = {}


@ExporterRegistry.register
class JsonHashExporter(BaseExporter):
    """Export sprites to TexturePacker JSON Hash format.

    The JSON Hash format uses sprite names as keys in a frames object,
    making it easy to look up sprites by name at runtime.

    Usage:
        from exporters import JsonHashExporter, ExportOptions

        exporter = JsonHashExporter()
        result = exporter.export_file(sprites, images, "/path/to/atlas")
    """

    FILE_EXTENSION = ".json"
    FORMAT_NAME = "json-hash"

    def __init__(self, options: Optional[ExportOptions] = None) -> None:
        """Initialize the JSON Hash exporter.

        Args:
            options: Export options. Format-specific options should be
                     provided in options.custom_properties["json_hash"].
        """
        super().__init__(options)
        self._format_options = self._get_format_options()

    def _get_format_options(self) -> JsonHashExportOptions:
        """Extract format-specific options from custom_properties.

        Returns:
            JsonHashExportOptions instance.
        """
        custom = self.options.custom_properties
        opts = custom.get("json_hash")

        if isinstance(opts, JsonHashExportOptions):
            return opts
        elif isinstance(opts, dict):
            try:
                return JsonHashExportOptions(**opts)
            except TypeError:
                return JsonHashExportOptions()
        else:
            return JsonHashExportOptions()

    def build_metadata(
        self,
        packed_sprites: List[PackedSprite],
        atlas_width: int,
        atlas_height: int,
        image_name: str,
        generator_metadata: Optional[GeneratorMetadata] = None,
    ) -> str:
        """Generate JSON Hash metadata.

        Args:
            packed_sprites: Sprites with their atlas positions assigned.
            atlas_width: Final atlas width in pixels.
            atlas_height: Final atlas height in pixels.
            image_name: Filename of the atlas image.
            generator_metadata: Optional metadata for watermark info.

        Returns:
            JSON string with frames hash and optional meta block.
        """
        opts = self._format_options

        # Build frames hash. TexturePacker's default JSON Hash output
        # keys frames by their source filename including extension; Phaser /
        # PixiJS / Cocos Creator loaders all key off that exact string.
        frames: Dict[str, Dict[str, Any]] = {}
        for packed in packed_sprites:
            frames[self._frame_key(packed.name, opts)] = self._build_frame_entry(
                packed, opts
            )

        # Build output structure
        output: Dict[str, Any] = {"frames": frames}

        # Add meta block if requested
        if opts.include_meta:
            # Soft watermark: embed the TextureAtlas Toolbox version inside
            # ``meta.app`` so ``meta.version`` can keep carrying the
            # TexturePacker schema version (parsers like Phaser / PixiJS /
            # Cocos may inspect that field). Prefer the generator-supplied
            # toolbox version when available.
            toolbox_version = APP_VERSION
            if generator_metadata and generator_metadata.app_version:
                toolbox_version = generator_metadata.app_version
            app_field = (
                f"{opts.app_name} ({toolbox_version})"
                if opts.app_name
                else f"TextureAtlas Toolbox ({toolbox_version})"
            )
            meta_block: Dict[str, Any] = {
                "app": app_field,
                "version": opts.app_version,
                "image": image_name,
                "format": opts.format_string,
                "size": {"w": atlas_width, "h": atlas_height},
                "scale": opts.scale_string,
            }
            if generator_metadata:
                if generator_metadata.packer:
                    meta_block["packer"] = generator_metadata.packer
                if generator_metadata.heuristic:
                    meta_block["heuristic"] = generator_metadata.heuristic
                if generator_metadata.efficiency > 0:
                    meta_block["efficiency"] = f"{generator_metadata.efficiency:.1f}%"
            # Aseprite-style frame tags surface here so animation pipelines
            # (Aseprite, Phaser, custom loaders) can recover playback ranges.
            if opts.frame_tags:
                meta_block["frameTags"] = [dict(tag) for tag in opts.frame_tags]
            if opts.extra_meta:
                for key, value in opts.extra_meta.items():
                    meta_block.setdefault(key, value)
            output["meta"] = meta_block

        # Serialize
        indent = 4 if self.options.pretty_print else None
        return json.dumps(output, indent=indent, ensure_ascii=False)

    @staticmethod
    def _frame_key(name: str, opts: JsonHashExportOptions) -> str:
        """Return the JSON Hash dictionary key for *name*.

        Appends `.png` when ``opts.append_extension`` is True and the name
        does not already carry a known image extension. Matches
        TexturePacker's default JSON Hash output.
        """
        if opts.append_extension and not name.lower().endswith(_IMAGE_EXTENSIONS):
            return f"{name}.png"
        return name

    def _build_frame_entry(
        self,
        packed: PackedSprite,
        opts: JsonHashExportOptions,
    ) -> Dict[str, Any]:
        """Build a single frame entry for the frames hash.

        Args:
            packed: Packed sprite with atlas position.
            opts: Format-specific options.

        Returns:
            Frame data dict with frame, rotated, trimmed, sourceSize, etc.
        """
        sprite = packed.sprite
        width = sprite["width"]
        height = sprite["height"]
        frame_x = sprite.get("frameX", 0)
        frame_y = sprite.get("frameY", 0)
        frame_w = sprite.get("frameWidth", width)
        frame_h = sprite.get("frameHeight", height)

        # Check if rotated
        is_rotated = packed.rotated or sprite.get("rotated", False)

        # Atlas dimensions: swap width/height when rotated (standard TexturePacker convention)
        atlas_w, atlas_h = (height, width) if is_rotated else (width, height)

        # Determine if trimmed
        trimmed = frame_x != 0 or frame_y != 0 or frame_w != width or frame_h != height

        entry: Dict[str, Any] = {
            "frame": {
                "x": packed.atlas_x,
                "y": packed.atlas_y,
                "w": atlas_w,
                "h": atlas_h,
            },
            "rotated": is_rotated,
            "trimmed": trimmed,
            "spriteSourceSize": {
                "x": -frame_x,
                "y": -frame_y,
                "w": width,
                "h": height,
            },
            "sourceSize": {
                "w": frame_w,
                "h": frame_h,
            },
        }

        if opts.include_pivot:
            entry["pivot"] = {
                "x": sprite.get("pivotX", 0.5),
                "y": sprite.get("pivotY", 0.5),
            }

        if opts.emit_durations and "duration" in sprite:
            entry["duration"] = int(sprite["duration"])

        return entry


__all__ = ["JsonHashExporter", "JsonHashExportOptions"]
