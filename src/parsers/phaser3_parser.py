#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for Phaser 3 atlas JSON metadata.

Handles all three documented Phaser 3 atlas variants used by
`Phaser.Loader.FileTypes.MultiAtlasFile` and
`Phaser.Textures.Parsers.JSONArray` / `JSONHash`:

    JSONArray  -- root has `frames` as a flat array of frame objects.
    JSONHash   -- root has `frames` as an object keyed by filename.
    MultiAtlas -- root has `textures[]`, each texture carries its own
                  page metadata and frames array.

Format reference:
    https://github.com/phaserjs/phaser/blob/master/src/textures/parsers/JSONArray.js
    https://github.com/phaserjs/phaser/blob/master/src/textures/parsers/JSONHash.js
    https://github.com/phaserjs/phaser/blob/master/src/loader/filetypes/MultiAtlasFile.js
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    FileError,
    FormatError,
    ParseResult,
    ParserErrorCode,
)
from utils.utilities import Utilities


class Phaser3Parser(BaseParser):
    """Parse Phaser 3 atlas JSON files in any of the three documented forms."""

    FILE_EXTENSIONS = (".json",)

    def __init__(
        self,
        directory: str,
        json_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the Phaser 3 parser.

        Args:
            directory: Directory containing the JSON file.
            json_filename: Name of the JSON file.
            name_callback: Optional callback invoked for each base
                name produced by `extract_names`.

        Returns:
            None.
        """
        super().__init__(directory, json_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Return unique animation/sprite base names from the atlas.

        Returns:
            Set of sprite base names with trailing digits stripped.
        """
        data = self._load_json()
        names: Set[str] = set()
        for filename, _frame in _iter_frame_entries(data):
            if filename:
                names.add(Utilities.strip_trailing_digits(filename))
        return names

    def _load_json(self) -> Dict[str, Any]:
        """Load and parse the JSON file from disk.

        Returns:
            The decoded JSON document as a dictionary.

        Raises:
            FileError: If the file is missing or unreadable.
            FormatError: If the file is not valid JSON or its root is
                not a JSON object.
        """
        file_path = os.path.join(self.directory, self.filename)
        return _load_json_strict(file_path)

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse a Phaser 3 atlas file and return a structured result.

        Args:
            file_path: Absolute path to the JSON file.

        Returns:
            A ParseResult with one normalized sprite per frame, plus a
            `metadata["phaser3"]` block carrying the schema variant,
            per-page texture metadata, and the file's top-level
            `meta` dict (`app`, `version`, `smartupdate`,
            `related_multi_packs`, etc.) so the file can be
            round-tripped without loss.

        Raises:
            FileError: If the file is missing or unreadable.
            FormatError: If the JSON does not match any of the three
                documented Phaser 3 atlas variants.
        """
        if not os.path.exists(file_path):
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )

        data = _load_json_strict(file_path)
        variant = _detect_variant(data)
        if variant is None:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                "Phaser 3 atlas must contain a 'textures' array or a 'frames' member.",
                file_path=file_path,
            )

        result = ParseResult(file_path=file_path, parser_name=cls.__name__)
        pages: List[Dict[str, Any]] = []

        for page_meta, raw_sprites in _iter_pages(data, variant):
            if page_meta:
                pages.append(page_meta)
            for raw in raw_sprites:
                try:
                    normalized = cls.normalize_sprite(raw)
                except Exception as exc:  # pragma: no cover - defensive
                    result.add_error(
                        ParserErrorCode.SPRITE_PARSE_FAILED,
                        f"Failed to parse sprite: {exc}",
                        sprite_name=raw.get("name", "unknown"),
                    )
                    continue
                for extra in ("page", "trimmed"):
                    if extra in raw:
                        normalized[extra] = raw[extra]
                result.sprites.append(normalized)

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        result.metadata = {
            "phaser3": {
                "variant": variant,
                "pages": pages,
                "meta": dict(meta),
            }
        }
        return result

    @classmethod
    def parse_from_textures(
        cls, textures: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert a `textures[]` list into normalized raw sprite dicts.

        Args:
            textures: The `textures` array from a multi-atlas JSON
                document.

        Returns:
            List of raw sprite dicts, one per frame across all
            textures.
        """
        sprites: List[Dict[str, Any]] = []
        for texture in textures:
            if not isinstance(texture, dict):
                continue
            page_image = texture.get("image")
            for raw in _decode_frames_field(texture.get("frames")):
                if page_image:
                    raw["page"] = page_image
                sprites.append(raw)
        return sprites

    @staticmethod
    def parse_json_data(file_path: str) -> List[Dict[str, Any]]:
        """Parse a Phaser 3 atlas file and return raw sprite dicts.

        Legacy entry point retained so the BaseParser fallback keeps
        working. New code should prefer `parse_file`.

        Args:
            file_path: Path to the JSON file.

        Returns:
            List of raw sprite dicts (not yet validated).
        """
        data = _load_json_strict(file_path)
        sprites: List[Dict[str, Any]] = []
        for _page_meta, raw in _iter_pages(data, _detect_variant(data) or "array"):
            sprites.extend(raw)
        return sprites


def _load_json_strict(file_path: str) -> Dict[str, Any]:
    """Load a JSON file, raising structured errors on failure.

    Args:
        file_path: Path to the JSON file.

    Returns:
        The decoded document as a dictionary.

    Raises:
        FileError: If the file is missing or unreadable.
        FormatError: If the file is not valid JSON or its root is not
            a JSON object.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
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
    except json.JSONDecodeError as exc:
        raise FormatError(
            ParserErrorCode.INVALID_FORMAT,
            f"Invalid JSON: {exc}",
            file_path=file_path,
        )
    if not isinstance(data, dict):
        raise FormatError(
            ParserErrorCode.INVALID_FORMAT,
            "Phaser 3 atlas root must be a JSON object.",
            file_path=file_path,
        )
    return data


def _detect_variant(data: Dict[str, Any]) -> Optional[str]:
    """Identify which of the three Phaser 3 schemas a document uses.

    Args:
        data: Decoded root JSON object.

    Returns:
        `"multi"` for the `textures[]` form, `"array"` for the
        `frames: [...]` form, `"hash"` for the `frames: {...}` form,
        or `None` when the document matches none of them.
    """
    textures = data.get("textures")
    if isinstance(textures, list) and textures:
        return "multi"
    frames = data.get("frames")
    if isinstance(frames, list):
        return "array"
    if isinstance(frames, dict):
        return "hash"
    return None


def _iter_pages(
    data: Dict[str, Any], variant: str
) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Walk a Phaser 3 atlas and yield per-page metadata + raw sprites.

    Args:
        data: Decoded root JSON object.
        variant: Result of `_detect_variant`.

    Returns:
        A list of `(page_meta, raw_sprites)` tuples. For single-atlas
        forms (`array` / `hash`) the list contains exactly one
        element; the page metadata is reconstructed from the root
        `meta` block. For `multi` the list has one entry per texture
        in `textures[]`.
    """
    pages: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []

    if variant == "multi":
        for texture in data.get("textures", []):
            if not isinstance(texture, dict):
                continue
            page_meta = _texture_page_meta(texture)
            raw = _decode_frames_field(texture.get("frames"))
            page_image = texture.get("image")
            if page_image:
                for entry in raw:
                    entry["page"] = page_image
            pages.append((page_meta, raw))
        return pages

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    page_meta = _meta_page_block(meta)
    raw = _decode_frames_field(data.get("frames"))
    page_image = meta.get("image")
    if page_image:
        for entry in raw:
            entry["page"] = page_image
    pages.append((page_meta, raw))
    return pages


def _iter_frame_entries(data: Dict[str, Any]):
    """Yield `(filename, frame_dict)` tuples across all schema variants.

    Used by `extract_names` to enumerate sprites without running the
    full parse pipeline.

    Args:
        data: Decoded root JSON object.

    Yields:
        Tuples of `(filename, frame_dict)`.
    """
    textures = data.get("textures")
    if isinstance(textures, list):
        for texture in textures:
            if isinstance(texture, dict):
                yield from _yield_from_frames_field(texture.get("frames"))
        return
    yield from _yield_from_frames_field(data.get("frames"))


def _yield_from_frames_field(frames: Any):
    """Yield `(filename, frame_dict)` from either array or hash forms.

    Args:
        frames: The `frames` payload (list, dict, or other).

    Yields:
        Tuples of `(filename, frame_dict)`.
    """
    if isinstance(frames, list):
        for entry in frames:
            if isinstance(entry, dict):
                yield entry.get("filename", ""), entry
    elif isinstance(frames, dict):
        for filename, entry in frames.items():
            if isinstance(entry, dict):
                yield filename, entry


def _decode_frames_field(frames: Any) -> List[Dict[str, Any]]:
    """Decode a Phaser 3 `frames` payload into raw sprite dicts.

    Args:
        frames: Either a list of frame objects (JSONArray /
            multi-atlas) or a dict keyed by filename (JSONHash).

    Returns:
        List of raw sprite dicts ready for normalization.
    """
    sprites: List[Dict[str, Any]] = []
    for filename, entry in _yield_from_frames_field(frames):
        sprites.append(_decode_frame(filename, entry))
    return sprites


def _decode_frame(filename: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a single Phaser 3 frame entry into a raw sprite dict.

    Args:
        filename: The frame's filename (already extracted from the
            container, since JSONHash stores it as the key).
        entry: The per-frame dict.

    Returns:
        Raw sprite dict carrying position, trim, rotation, optional
        pivot, and the file's `trimmed` flag.
    """
    frame = entry.get("frame", {}) or {}
    sprite_source = entry.get("spriteSourceSize", {}) or {}
    source_size = entry.get("sourceSize", {}) or {}

    frame_x = _to_int(frame.get("x"))
    frame_y = _to_int(frame.get("y"))
    frame_w = _to_int(frame.get("w"))
    frame_h = _to_int(frame.get("h"))

    sprite: Dict[str, Any] = {
        "name": entry.get("filename") or filename,
        "x": frame_x,
        "y": frame_y,
        "width": frame_w,
        "height": frame_h,
        "frameX": -_to_int(sprite_source.get("x")),
        "frameY": -_to_int(sprite_source.get("y")),
        "frameWidth": _to_int(source_size.get("w")) or frame_w,
        "frameHeight": _to_int(source_size.get("h")) or frame_h,
        "rotated": bool(entry.get("rotated", False)),
    }

    if "trimmed" in entry:
        sprite["trimmed"] = bool(entry.get("trimmed"))

    pivot = entry.get("pivot") or entry.get("anchor")
    if isinstance(pivot, dict):
        if "x" in pivot:
            sprite["pivotX"] = float(pivot["x"])
        if "y" in pivot:
            sprite["pivotY"] = float(pivot["y"])

    return sprite


def _texture_page_meta(texture: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the per-texture page metadata for a multi-atlas entry.

    Args:
        texture: One element from the root `textures[]` array.

    Returns:
        A dict carrying whichever of `image`, `format`, `size`,
        `scale` were present.
    """
    page: Dict[str, Any] = {}
    for key in ("image", "format", "size", "scale"):
        if key in texture:
            page[key] = texture[key]
    return page


def _meta_page_block(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruct a synthetic page metadata dict from the root `meta`.

    Used for single-atlas (`array` / `hash`) variants which carry
    page info on `meta` rather than on a `textures[]` element.

    Args:
        meta: The root `meta` dict.

    Returns:
        Dict with `image` / `format` / `size` / `scale` keys when
        present.
    """
    page: Dict[str, Any] = {}
    for key in ("image", "format", "size", "scale"):
        if key in meta:
            page[key] = meta[key]
    return page


def _to_int(value: Any) -> int:
    """Coerce a JSON scalar to an integer.

    Args:
        value: Any JSON scalar (int, float, numeric string, or None).

    Returns:
        The integer form of `value`, or `0` on failure.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


__all__ = ["Phaser3Parser"]
