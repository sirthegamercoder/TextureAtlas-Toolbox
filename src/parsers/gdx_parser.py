#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for libGDX TexturePacker / Spine ``.atlas`` text format.

The two communities use the same file: Spine's runtime atlas reader
delegates to the libGDX ``TextureAtlas`` loader. The schema mirrored
here is taken directly from
``com.badlogic.gdx.graphics.g2d.TextureAtlas$TextureAtlasData.load``
in the upstream libGDX repository.

Format reference:
    https://github.com/libgdx/libgdx/blob/master/gdx/src/com/badlogic/gdx/graphics/g2d/TextureAtlas.java
    http://esotericsoftware.com/spine-atlas-format

Two region layouts are accepted, matching upstream:

* **Modern** (preferred since libGDX 1.10): ``bounds: x, y, w, h`` and
  ``offsets: ox, oy, ow, oh``.
* **Legacy** (deprecated but still parsed by libGDX): the four-line
  ``xy``, ``size``, ``orig``, ``offset`` quadruple.

Page-level fields (``size``, ``format``, ``filter``, ``repeat``,
``pma``) and per-region extras (``split``, ``pad``, ``rotate`` as
degrees, ``index``, plus arbitrary integer name/value pairs) are
captured into ``ParseResult.metadata['gdx']`` so a matching exporter
can round-trip them without loss.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    ContentError,
    FileError,
    ParseResult,
    ParserErrorCode,
)
from utils.utilities import Utilities


# Page-level field names recognised by libGDX's TextureAtlasData. Any
# other ``key: value`` line at the page level is silently ignored, just
# like upstream.
_PAGE_FIELDS = frozenset({"size", "format", "filter", "repeat", "pma"})

# Region fields with bespoke handling. Anything else found at the
# region level is captured as a custom ``names[]``/``values[]`` int
# array, mirroring libGDX's behaviour.
_REGION_KNOWN_FIELDS = frozenset(
    {
        "bounds",
        "offsets",
        "xy",
        "size",
        "orig",
        "offset",
        "rotate",
        "index",
        "split",
        "pad",
    }
)


def _read_entry(line: str) -> Optional[Tuple[str, List[str]]]:
    """Parse a ``key: v1, v2, ...`` line.

    Returns ``None`` when the line has no colon, matching upstream's
    ``readEntry`` returning ``0``.
    """
    stripped = line.strip()
    colon = stripped.find(":")
    if colon == -1:
        return None
    key = stripped[:colon].strip()
    rest = stripped[colon + 1 :].strip()
    if not rest:
        return (key, [])
    return (key, [v.strip() for v in rest.split(",")])


def _parse_int(value: str, default: int = 0) -> int:
    """Best-effort ``int`` conversion that mirrors libGDX's silent skip."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_int_list(values: List[str]) -> List[int]:
    """Convert a list of string tokens to ints, skipping non-numerics.

    libGDX's ``readEntry`` swallows ``NumberFormatException`` per token
    (see the ``// Silently ignore non-integer value.`` comment); we
    behave the same to stay tolerant of hand-edited files.
    """
    out: List[int] = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


class GdxAtlasParser(BaseParser):
    """Parse libGDX TexturePacker / Spine ``.atlas`` files.

    Supports both modern (``bounds``/``offsets``) and legacy
    (``xy``/``size``/``orig``/``offset``) region layouts, captures
    multi-page atlases, and preserves all page metadata, ninepatch
    splits/pads, numeric ``rotate`` degrees, and arbitrary int-array
    custom fields.
    """

    FILE_EXTENSIONS = (".atlas",)

    def __init__(
        self,
        directory: str,
        atlas_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(directory, atlas_filename, name_callback)

    # ------------------------------------------------------------------
    # BaseParser API
    # ------------------------------------------------------------------

    def extract_names(self) -> Set[str]:
        """Return unique sprite base names from the atlas file."""
        sprites = self.parse_atlas_file(os.path.join(self.directory, self.filename))
        return {Utilities.strip_trailing_digits(sprite["name"]) for sprite in sprites}

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse an atlas file and return a fully-populated ``ParseResult``.

        Per-page metadata is attached as
        ``result.metadata['gdx'] = {'pages': [...]}`` so an exporter can
        round-trip it.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)

        if not os.path.exists(file_path):
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )

        pages, raw_sprites = cls._parse_pages_and_regions(file_path)

        for raw in raw_sprites:
            try:
                normalized = cls.normalize_sprite(raw)
                # Preserve the libGDX-specific extras so they can be
                # round-tripped by the exporter.
                for extra in (
                    "rotated",
                    "degrees",
                    "index",
                    "split",
                    "pad",
                    "custom_values",
                    "page",
                ):
                    if extra in raw:
                        normalized[extra] = raw[extra]
                result.sprites.append(normalized)
            except Exception as exc:  # pragma: no cover - defensive
                result.add_error(
                    ParserErrorCode.SPRITE_PARSE_FAILED,
                    f"Failed to parse sprite: {exc}",
                    sprite_name=raw.get("name", "unknown"),
                )

        if pages:
            result.metadata = {"gdx": {"pages": pages}}

        return result

    @classmethod
    def parse_atlas_file(cls, file_path: str) -> List[Dict[str, Any]]:
        """Parse the atlas file and return its sprite list.

        Returns:
            List of sprite dicts with position, dimension, rotation,
            ninepatch, and custom-value data.
        """
        _pages, sprites = cls._parse_pages_and_regions(file_path)
        return sprites

    # ------------------------------------------------------------------
    # Modern format detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_modern_format(file_path: str) -> bool:
        """Return ``True`` when the atlas uses ``bounds:`` or ``offsets:``."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("bounds:") or stripped.startswith(
                        "offsets:"
                    ):
                        return True
        except (OSError, UnicodeDecodeError):
            pass
        return False

    # ------------------------------------------------------------------
    # Internal: scanner
    # ------------------------------------------------------------------

    @classmethod
    def _parse_pages_and_regions(
        cls, file_path: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Walk the atlas file and return ``(pages, sprites)``.

        Mirrors the structure of ``TextureAtlasData.load``: skip blank
        lines, treat each non-key/non-blank line as either a page name
        (when no page is active) or a region name (when one is).
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                str(exc),
                file_path=file_path,
            )

        pages: List[Dict[str, Any]] = []
        sprites: List[Dict[str, Any]] = []

        idx = 0
        n = len(lines)

        # Skip leading blank lines, matching upstream's "Ignore empty lines
        # before first entry" loop.
        while idx < n and not lines[idx].strip():
            idx += 1

        current_page: Optional[Dict[str, Any]] = None

        while idx < n:
            line = lines[idx].rstrip("\n\r")
            stripped = line.strip()

            # A blank line ends the current page block.
            if not stripped:
                current_page = None
                idx += 1
                continue

            entry = _read_entry(line)

            if current_page is None:
                # First non-blank line of a page block is the texture
                # filename. Upstream also accepts header-only files
                # (no pages); here we only enter page mode when the
                # line has no colon.
                if entry is not None:
                    # A stray header line with no associated page; skip.
                    idx += 1
                    continue
                current_page = cls._new_page(stripped)
                pages.append(current_page)
                idx += 1
                # Consume page header fields.
                while idx < n:
                    header_line = lines[idx].rstrip("\n\r")
                    if not header_line.strip():
                        break
                    header_entry = _read_entry(header_line)
                    if header_entry is None:
                        # First region name encountered.
                        break
                    cls._apply_page_field(current_page, *header_entry)
                    idx += 1
                continue

            # Inside a page: a region name is a non-empty line with no
            # colon at the start.
            if entry is not None:
                # Stray ``key: value`` line at the region level with no
                # active region - skip silently like upstream.
                idx += 1
                continue

            region_name = stripped
            idx += 1
            region_fields: Dict[str, List[str]] = {}
            custom_fields: Dict[str, List[int]] = {}

            while idx < n:
                field_line = lines[idx].rstrip("\n\r")
                if not field_line.strip():
                    break
                field_entry = _read_entry(field_line)
                if field_entry is None:
                    break
                key, values = field_entry
                if key in _REGION_KNOWN_FIELDS:
                    region_fields[key] = values
                else:
                    parsed_ints = _parse_int_list(values)
                    if parsed_ints:
                        custom_fields[key] = parsed_ints
                idx += 1

            sprite = cls._build_sprite(
                region_name, region_fields, custom_fields, current_page
            )
            sprites.append(sprite)

        return pages, sprites

    # ------------------------------------------------------------------
    # Internal: page handling
    # ------------------------------------------------------------------

    @staticmethod
    def _new_page(filename: str) -> Dict[str, Any]:
        """Create an empty page dict with libGDX defaults."""
        return {
            "name": filename,
            "format": "RGBA8888",
            "filter_min": "Nearest",
            "filter_mag": "Nearest",
            "repeat": "none",
            "pma": False,
        }

    @staticmethod
    def _apply_page_field(page: Dict[str, Any], key: str, values: List[str]) -> None:
        """Apply one ``key: value`` pair to a page dict, libGDX-style."""
        if key not in _PAGE_FIELDS or not values:
            return
        if key == "size":
            if len(values) >= 2:
                page["width"] = _parse_int(values[0])
                page["height"] = _parse_int(values[1])
        elif key == "format":
            page["format"] = values[0]
        elif key == "filter":
            page["filter_min"] = values[0]
            if len(values) >= 2:
                page["filter_mag"] = values[1]
            else:
                page["filter_mag"] = values[0]
        elif key == "repeat":
            page["repeat"] = values[0]
        elif key == "pma":
            page["pma"] = values[0].strip().lower() == "true"

    # ------------------------------------------------------------------
    # Internal: region builder
    # ------------------------------------------------------------------

    @classmethod
    def _build_sprite(
        cls,
        name: str,
        fields: Dict[str, List[str]],
        custom: Dict[str, List[int]],
        page: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Convert the parsed field map for one region into a sprite dict."""
        x = y = 0
        width = height = 0
        offset_x = offset_y = 0
        orig_w = orig_h = 0
        rotated = False
        degrees = 0
        index = -1

        try:
            # Modern combined fields take precedence.
            if "bounds" in fields:
                vals = fields["bounds"]
                x = _parse_int(vals[0]) if len(vals) > 0 else 0
                y = _parse_int(vals[1]) if len(vals) > 1 else 0
                width = _parse_int(vals[2]) if len(vals) > 2 else 0
                height = _parse_int(vals[3]) if len(vals) > 3 else 0
            if "xy" in fields:
                vals = fields["xy"]
                x = _parse_int(vals[0]) if len(vals) > 0 else 0
                y = _parse_int(vals[1]) if len(vals) > 1 else 0
            if "size" in fields:
                vals = fields["size"]
                width = _parse_int(vals[0]) if len(vals) > 0 else 0
                height = _parse_int(vals[1]) if len(vals) > 1 else 0

            if "offsets" in fields:
                vals = fields["offsets"]
                offset_x = _parse_int(vals[0]) if len(vals) > 0 else 0
                offset_y = _parse_int(vals[1]) if len(vals) > 1 else 0
                orig_w = _parse_int(vals[2]) if len(vals) > 2 else width
                orig_h = _parse_int(vals[3]) if len(vals) > 3 else height
            if "offset" in fields:
                vals = fields["offset"]
                offset_x = _parse_int(vals[0]) if len(vals) > 0 else 0
                offset_y = _parse_int(vals[1]) if len(vals) > 1 else 0
            if "orig" in fields:
                vals = fields["orig"]
                orig_w = _parse_int(vals[0]) if len(vals) > 0 else 0
                orig_h = _parse_int(vals[1]) if len(vals) > 1 else 0
        except (ValueError, IndexError) as exc:
            raise ContentError(
                ParserErrorCode.INVALID_COORDINATE,
                f"Non-numeric coordinate in sprite '{name}': {exc}",
            )

        # Rotation: per upstream, ``true`` ⇒ 90 degrees, ``false`` ⇒ 0,
        # any other value parsed as an int (non-90 degrees keep
        # ``rotate=false`` but preserve the angle).
        if "rotate" in fields and fields["rotate"]:
            val = fields["rotate"][0].strip().lower()
            if val == "true":
                degrees = 90
                rotated = True
            elif val == "false":
                degrees = 0
                rotated = False
            else:
                degrees = _parse_int(val, 0) % 360
                rotated = degrees == 90

        # When ``rotate=true``, the stored width/height are swapped
        # compared with the source image (upstream sets the AtlasRegion
        # dimensions to the swapped pair). Mirror that here so the
        # ``width``/``height`` fields reflect source orientation.
        if rotated:
            width, height = height, width

        if "index" in fields and fields["index"]:
            index = _parse_int(fields["index"][0], -1)

        # libGDX falls back to packed dims when ``orig`` is absent.
        if orig_w == 0:
            orig_w = width
        if orig_h == 0:
            orig_h = height

        sprite: Dict[str, Any] = {
            "name": name,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "frameX": -offset_x,
            "frameY": -offset_y,
            "frameWidth": orig_w,
            "frameHeight": orig_h,
            "rotated": rotated,
            "degrees": degrees,
            "index": index,
        }

        # Ninepatch splits/pads. libGDX accesses these via
        # ``region.findValue("split")`` and stores them as 4-int arrays.
        if "split" in fields:
            split = _parse_int_list(fields["split"])
            if len(split) == 4:
                sprite["split"] = split
        if "pad" in fields:
            pad = _parse_int_list(fields["pad"])
            if len(pad) == 4:
                sprite["pad"] = pad

        if custom:
            sprite["custom_values"] = custom

        if page is not None and "name" in page:
            sprite["page"] = page["name"]

        return sprite


__all__ = ["GdxAtlasParser"]
