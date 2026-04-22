#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for Apple/TexturePacker `.plist` atlas metadata files.

Supports all four Cocos2d-x plist format versions (`format: 0` through
`format: 3`) as documented in TexturePacker's plist exporter and parsed
by Cocos2d-x's `CCSpriteFrameCache::addSpriteFramesWithDictionary`.

Format reference:
    https://www.codeandweb.com/texturepacker/documentation/cocos2d-x
    https://github.com/cocos2d/cocos2d-x/blob/master/cocos/2d/CCSpriteFrameCache.cpp

Per-frame keys by version:

    Version 0/1 (Zwoptex original):
        x, y, width, height,
        offsetX, offsetY, originalWidth, originalHeight

    Version 2 (TexturePacker classic):
        frame, offset, sourceColorRect, sourceSize, rotated

    Version 3 (TexturePacker modern, default):
        textureRect, textureRotated, spriteOffset,
        spriteSize, spriteSourceSize, aliases,
        plus optional polygon-mesh fields (triangles, vertices,
        verticesUV, anchor)
"""

from __future__ import annotations

import os
import plistlib
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    FileError,
    FormatError,
    ParseResult,
    ParserErrorCode,
)
from utils.utilities import Utilities


_RECT_RE = re.compile(
    r"\{\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\},\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}\}"
)
_SIZE_RE = re.compile(r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}")

# Page-metadata keys captured for round-trip via ParseResult.metadata.
_PAGE_META_KEYS = (
    "format",
    "textureFileName",
    "realTextureFileName",
    "size",
    "pixelFormat",
    "premultiplyAlpha",
    "smartupdate",
    "target",
)


class PlistAtlasParser(BaseParser):
    """Parse `.plist` atlases exported by Apple/TexturePacker tools.

    Reads format versions 0-3 transparently and preserves the original
    page metadata, frame aliases, and polygon-mesh data so the result
    can be round-tripped without loss.
    """

    FILE_EXTENSIONS = (".plist",)

    def __init__(
        self,
        directory: str,
        plist_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the plist parser.

        Args:
            directory: Directory containing the plist file.
            plist_filename: Name of the plist file.
            name_callback: Optional callback invoked for each extracted
                base name during `extract_names`.

        Returns:
            None.
        """
        super().__init__(directory, plist_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Extract unique animation/sprite base names from the plist.

        Strips trailing digits from each frame key so animation
        sequences (`run0001`, `run0002`, ...) collapse to one base
        name.

        Returns:
            Set of sprite base names with trailing digits removed.
        """
        plist_data = self._load_plist()
        frames = plist_data.get("frames", {})
        names: Set[str] = set()
        for sprite_name in frames.keys():
            names.add(Utilities.strip_trailing_digits(sprite_name))
        return names

    def _load_plist(self) -> Dict[str, Any]:
        """Load and parse the plist file from disk.

        Returns:
            The decoded plist as a dictionary.

        Raises:
            FileError: If the file cannot be opened or read.
            FormatError: If the file content is not a valid plist.
        """
        file_path = os.path.join(self.directory, self.filename)
        return _load_plist_strict(file_path)

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse a plist file and return a structured result.

        Args:
            file_path: Absolute path to the plist file.

        Returns:
            A ParseResult containing normalized sprites and a
            `metadata["plist"]` block carrying the format version,
            page metadata, and any polygon-mesh / aliases data so the
            file can be round-tripped.

        Raises:
            FileError: If the file is missing or unreadable.
            FormatError: If the plist is malformed or its `frames`
                section is not a dictionary.
        """
        if not os.path.exists(file_path):
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )

        plist_data = _load_plist_strict(file_path)
        frames = plist_data.get("frames", {})
        if not isinstance(frames, dict):
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                "Plist 'frames' entry is not a dictionary.",
                file_path=file_path,
            )

        metadata = plist_data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        version = _coerce_int(metadata.get("format"), 2)

        result = ParseResult(file_path=file_path, parser_name=cls.__name__)
        for sprite_name, sprite_info in frames.items():
            if not isinstance(sprite_info, dict):
                continue
            raw = _decode_frame(sprite_name, sprite_info, version)
            try:
                normalized = cls.normalize_sprite(raw)
            except Exception as exc:  # pragma: no cover - defensive
                result.add_error(
                    ParserErrorCode.SPRITE_PARSE_FAILED,
                    f"Failed to parse sprite: {exc}",
                    sprite_name=raw.get("name", "unknown"),
                )
                continue
            # Preserve the plist-specific extras so an exporter can
            # round-trip them losslessly.
            for extra in ("aliases", "mesh"):
                if extra in raw:
                    normalized[extra] = raw[extra]
            result.sprites.append(normalized)

        # Carry the rich plist block so round-trip exporters can
        # reproduce page metadata, aliases, and polygon meshes.
        page_meta = {key: metadata[key] for key in _PAGE_META_KEYS if key in metadata}
        result.metadata = {
            "plist": {
                "version": version,
                "page": page_meta,
            }
        }
        return result

    @classmethod
    def parse_from_frames(
        cls,
        frames: Dict[str, Dict[str, Any]],
        version: int = 2,
    ) -> List[Dict[str, Any]]:
        """Convert a `frames` dict into normalized sprite dicts.

        Provided for callers that have already loaded the plist body
        (for example tests, or the `parse_plist_data` legacy path).

        Args:
            frames: Mapping of frame key to per-frame metadata.
            version: Cocos2d-x plist format version (0-3).

        Returns:
            List of normalized sprite dicts, one per frame.
        """
        sprites: List[Dict[str, Any]] = []
        for sprite_name, sprite_info in frames.items():
            if not isinstance(sprite_info, dict):
                continue
            sprites.append(_decode_frame(sprite_name, sprite_info, version))
        return sprites

    @staticmethod
    def parse_plist_data(file_path: str) -> List[Dict[str, Any]]:
        """Parse a plist atlas file and return raw sprite dicts.

        Legacy entry point retained so the BaseParser fallback in
        `parse_file` (for callers that bypass the new path) keeps
        working. New code should prefer `parse_file`.

        Args:
            file_path: Path to the plist file.

        Returns:
            List of raw sprite dicts (not yet validated / normalized).
        """
        plist_data = _load_plist_strict(file_path)
        frames = plist_data.get("frames", {})
        metadata = plist_data.get("metadata", {})
        version = _coerce_int(
            metadata.get("format") if isinstance(metadata, dict) else None, 2
        )
        return PlistAtlasParser.parse_from_frames(frames, version)

    @staticmethod
    def detect_version(file_path: str) -> int:
        """Inspect a plist file and return its `format` version.

        Useful for the parser registry's content-based dispatch.

        Args:
            file_path: Path to the plist file.

        Returns:
            The Cocos2d-x format version (0-3). Defaults to 2 when no
            `metadata.format` key is present.
        """
        try:
            data = _load_plist_strict(file_path)
        except (FileError, FormatError):
            return 2
        meta = data.get("metadata", {})
        if not isinstance(meta, dict):
            return 2
        return _coerce_int(meta.get("format"), 2)


def _load_plist_strict(file_path: str) -> Dict[str, Any]:
    """Load a plist file, raising structured errors on failure.

    Args:
        file_path: Path to the plist file.

    Returns:
        The decoded plist as a dictionary.

    Raises:
        FileError: If the file cannot be opened or read.
        FormatError: If the file is not a valid plist or does not
            decode to a dictionary at the root.
    """
    try:
        with open(file_path, "rb") as plist_file:
            data = plistlib.load(plist_file)
    except FileNotFoundError:
        raise FileError(
            ParserErrorCode.FILE_NOT_FOUND,
            f"File not found: {file_path}",
            file_path=file_path,
        )
    except OSError as exc:
        raise FileError(
            ParserErrorCode.FILE_READ_ERROR,
            str(exc),
            file_path=file_path,
        )
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise FormatError(
            ParserErrorCode.INVALID_FORMAT,
            f"Invalid plist: {exc}",
            file_path=file_path,
        )
    if not isinstance(data, dict):
        raise FormatError(
            ParserErrorCode.INVALID_FORMAT,
            "Plist root is not a dictionary.",
            file_path=file_path,
        )
    return data


def _decode_frame(
    sprite_name: str, sprite_info: Dict[str, Any], version: int
) -> Dict[str, Any]:
    """Decode a single frame entry into a raw sprite dict.

    Args:
        sprite_name: The frame key (also used as the sprite name).
        sprite_info: The per-frame dict from the plist.
        version: Cocos2d-x format version (0-3); selects which key
            naming convention to read.

    Returns:
        A raw sprite dict ready for normalization.
    """
    if version >= 3:
        sprite = _decode_v3(sprite_name, sprite_info)
    elif version == 2:
        sprite = _decode_v2(sprite_name, sprite_info)
    else:
        sprite = _decode_v0_v1(sprite_name, sprite_info)

    aliases = sprite_info.get("aliases")
    if isinstance(aliases, list) and aliases:
        sprite["aliases"] = list(aliases)

    mesh = _extract_mesh(sprite_info)
    if mesh:
        sprite["mesh"] = mesh

    return sprite


def _decode_v0_v1(sprite_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a Zwoptex-style scalar frame entry (format 0 / 1).

    Args:
        sprite_name: Frame key.
        info: Per-frame dict.

    Returns:
        Raw sprite dict; never rotated.
    """
    x = _coerce_int(info.get("x"))
    y = _coerce_int(info.get("y"))
    width = _coerce_int(info.get("width"))
    height = _coerce_int(info.get("height"))
    offset_x = _coerce_int(info.get("offsetX"))
    offset_y = _coerce_int(info.get("offsetY"))
    original_w = _coerce_int(info.get("originalWidth")) or width
    original_h = _coerce_int(info.get("originalHeight")) or height
    return {
        "name": sprite_name,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "frameX": -offset_x,
        "frameY": -offset_y,
        "frameWidth": original_w,
        "frameHeight": original_h,
        "rotated": False,
    }


def _decode_v2(sprite_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a TexturePacker classic string-rect entry (format 2).

    Args:
        sprite_name: Frame key.
        info: Per-frame dict containing `frame` / `offset` /
            `sourceColorRect` / `sourceSize` / `rotated`.

    Returns:
        Raw sprite dict.
    """
    frame_rect = _parse_rect(info.get("frame"))
    color_rect = _parse_rect(info.get("sourceColorRect"))
    source_size = _parse_size(info.get("sourceSize"))

    return {
        "name": sprite_name,
        "x": frame_rect[0],
        "y": frame_rect[1],
        "width": frame_rect[2],
        "height": frame_rect[3],
        "frameX": -color_rect[0],
        "frameY": -color_rect[1],
        "frameWidth": source_size[0] or frame_rect[2],
        "frameHeight": source_size[1] or frame_rect[3],
        "rotated": _parse_bool(info.get("rotated")),
    }


def _decode_v3(sprite_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a TexturePacker modern entry (format 3).

    `textureRect` is the position and size in the atlas; when
    `textureRotated` is true Cocos2d-x stores the rect's width and
    height pre-swapped, so we mirror that convention.

    Args:
        sprite_name: Frame key.
        info: Per-frame dict containing `textureRect` /
            `textureRotated` / `spriteSourceSize` / `spriteOffset` /
            `spriteSize`.

    Returns:
        Raw sprite dict.
    """
    texture_rect = _parse_rect(info.get("textureRect"))
    sprite_offset = _parse_size(info.get("spriteOffset"))
    source_size = _parse_size(info.get("spriteSourceSize"))
    rotated = _parse_bool(info.get("textureRotated"))

    width = texture_rect[2]
    height = texture_rect[3]

    return {
        "name": sprite_name,
        "x": texture_rect[0],
        "y": texture_rect[1],
        "width": width,
        "height": height,
        "frameX": -sprite_offset[0],
        "frameY": -sprite_offset[1],
        "frameWidth": source_size[0] or width,
        "frameHeight": source_size[1] or height,
        "rotated": rotated,
    }


def _extract_mesh(info: Dict[str, Any]) -> Dict[str, Any]:
    """Pull TexturePacker polygon-mesh fields out of a frame entry.

    Args:
        info: Per-frame dict.

    Returns:
        A dict containing whichever of `triangles`, `vertices`,
        `verticesUV`, and `anchor` were present (empty if none).
    """
    mesh: Dict[str, Any] = {}
    for key in ("triangles", "vertices", "verticesUV", "anchor"):
        value = info.get(key)
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        mesh[key] = value
    return mesh


def _parse_rect(rect_value: Any) -> Tuple[int, int, int, int]:
    """Parse a rectangle from plist representation.

    Args:
        rect_value: Either a nested list/tuple of the form
            `((x, y), (w, h))` or a string of the form `{{x,y},{w,h}}`.

    Returns:
        A 4-tuple `(x, y, width, height)`. Returns `(0, 0, 0, 0)`
        when the input is missing or malformed.
    """
    if isinstance(rect_value, (list, tuple)) and len(rect_value) == 2:
        try:
            (x, y), (w, h) = rect_value
            return int(x), int(y), int(w), int(h)
        except (TypeError, ValueError):
            return 0, 0, 0, 0
    if isinstance(rect_value, str):
        match = _RECT_RE.match(rect_value)
        if match:
            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
            )
    return 0, 0, 0, 0


def _parse_size(size_value: Any) -> Tuple[int, int]:
    """Parse a size from plist representation.

    Args:
        size_value: Either a list/tuple `(w, h)` or a string of the
            form `{w,h}`.

    Returns:
        A 2-tuple `(width, height)`. Returns `(0, 0)` when the input
        is missing or malformed.
    """
    if isinstance(size_value, (list, tuple)) and len(size_value) == 2:
        try:
            return int(size_value[0]), int(size_value[1])
        except (TypeError, ValueError):
            return 0, 0
    if isinstance(size_value, str):
        match = _SIZE_RE.match(size_value)
        if match:
            return int(match.group(1)), int(match.group(2))
    return 0, 0


def _parse_bool(value: Any) -> bool:
    """Parse a boolean from plist representation.

    Args:
        value: Either a Python bool, or a string such as `"true"`,
            `"yes"`, `"1"` (case-insensitive).

    Returns:
        The parsed boolean. Defaults to `False` for unrecognized
        input.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return False


def _coerce_int(value: Any, default: int = 0) -> int:
    """Coerce a plist scalar to an integer.

    Args:
        value: Any plist value (int, float, numeric string, or None).
        default: Value to return when coercion fails.

    Returns:
        The integer form of `value`, or `default` on failure.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


__all__ = ["PlistAtlasParser"]
