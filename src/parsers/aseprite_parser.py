#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for Aseprite JSON sprite-sheet metadata.

The schema mirrored here is the one Aseprite emits from
``app/doc_exporter.cpp`` (``createDataFile``) when running
``aseprite -b ... --sheet sheet.png --data sheet.json`` with one or more
of ``--list-tags``, ``--list-layers``, ``--list-layer-hierarchy`` and
``--list-slices``.

Format reference:
    https://www.aseprite.org/docs/cli/
    https://github.com/aseprite/aseprite/blob/main/src/app/doc_exporter.cpp

The parser exposes:
    * Per-sprite frame data on :class:`ParseResult.sprites`.
    * Format-rich metadata on ``ParseResult.metadata["aseprite"]`` so a
      matching exporter can round-trip frame tags, layers, and slices
      without losing information.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Set

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    ContentError,
    FileError,
    FormatError,
    ParseResult,
    ParserErrorCode,
)
from utils.logger import get_logger
from utils.utilities import Utilities

logger = get_logger(__name__)

# Canonical animation directions emitted by Aseprite via
# ``convert_anidir_to_string`` in ``doc/anidir.h``.
VALID_DIRECTIONS = frozenset({"forward", "reverse", "pingpong", "pingpong_reverse"})


def _parse_user_data(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extract Aseprite ``userData`` fields from a tag/layer/slice dict.

    Aseprite serializes ``UserData`` as inline keys ``color``, ``data``,
    and ``properties`` appended to the owning entry (see
    ``operator<<(std::ostream&, const doc::UserData&)`` in
    ``doc_exporter.cpp``).

    Args:
        entry: Raw JSON dict for a tag, layer, or slice.

    Returns:
        Dict containing only the present user-data fields.
    """
    out: Dict[str, Any] = {}
    color = entry.get("color")
    if isinstance(color, str) and color:
        out["color"] = color
    data = entry.get("data")
    if isinstance(data, str) and data:
        out["data"] = data
    props = entry.get("properties")
    if isinstance(props, dict) and props:
        out["properties"] = props
    return out


def _normalize_direction(value: Any) -> str:
    """Normalize a frame-tag direction string.

    Accepts the four canonical Aseprite values plus the hyphenated
    spelling ``pingpong-reverse`` that occasionally appears in
    third-party exporters. Anything else is logged and falls back to
    ``"forward"``.
    """
    if not isinstance(value, str):
        logger.warning(
            "[AsepriteParser] Non-string direction %r; defaulting to 'forward'.",
            value,
        )
        return "forward"
    canonical = value.replace("-", "_").strip().lower()
    if canonical in VALID_DIRECTIONS:
        return canonical
    logger.warning(
        "[AsepriteParser] Unknown direction %r; defaulting to 'forward'. "
        "Valid values: %s",
        value,
        sorted(VALID_DIRECTIONS),
    )
    return "forward"


def _parse_frame_tag(tag: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw ``frameTags`` entry into a normalized dict.

    Aseprite emits ``repeat`` as a JSON string (``"\"repeat\": \"3\""``)
    and only when the value is greater than zero. This helper coerces
    it back to an int. ``repeat`` of ``0`` (and a missing field) both
    mean "loop indefinitely".
    """
    out: Dict[str, Any] = {
        "name": str(tag.get("name", "")),
        "from": int(tag.get("from", 0)),
        "to": int(tag.get("to", 0)),
        "direction": _normalize_direction(tag.get("direction", "forward")),
    }
    repeat_val = tag.get("repeat")
    if repeat_val is not None and repeat_val != "":
        try:
            out["repeat"] = int(repeat_val)
        except (TypeError, ValueError):
            logger.warning(
                "[AsepriteParser] Invalid 'repeat' %r on tag %r; ignoring.",
                repeat_val,
                out["name"],
            )
    out.update(_parse_user_data(tag))
    return out


def _parse_layer(layer: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw ``layers`` entry into a normalized dict.

    Captures every documented layer field (``name``, ``group``,
    ``opacity``, ``blendMode``, user data, ``cels``).
    """
    out: Dict[str, Any] = {"name": str(layer.get("name", ""))}
    group = layer.get("group")
    if isinstance(group, str):
        out["group"] = group
    if "opacity" in layer:
        try:
            out["opacity"] = int(layer["opacity"])
        except (TypeError, ValueError):
            pass
    blend_mode = layer.get("blendMode")
    if isinstance(blend_mode, str):
        out["blendMode"] = blend_mode
    out.update(_parse_user_data(layer))
    cels = layer.get("cels")
    if isinstance(cels, list):
        parsed_cels: List[Dict[str, Any]] = []
        for cel in cels:
            if not isinstance(cel, dict):
                continue
            cel_out: Dict[str, Any] = {"frame": int(cel.get("frame", 0))}
            if "opacity" in cel:
                try:
                    cel_out["opacity"] = int(cel["opacity"])
                except (TypeError, ValueError):
                    pass
            if "zIndex" in cel:
                try:
                    cel_out["zIndex"] = int(cel["zIndex"])
                except (TypeError, ValueError):
                    pass
            cel_out.update(_parse_user_data(cel))
            parsed_cels.append(cel_out)
        if parsed_cels:
            out["cels"] = parsed_cels
    return out


def _parse_rect(value: Any) -> Optional[Dict[str, int]]:
    """Coerce a ``{x,y,w,h}`` dict (or ``{x,y,width,height}``) into ints."""
    if not isinstance(value, dict):
        return None
    try:
        return {
            "x": int(value.get("x", 0)),
            "y": int(value.get("y", 0)),
            "w": int(value.get("w", value.get("width", 0))),
            "h": int(value.get("h", value.get("height", 0))),
        }
    except (TypeError, ValueError):
        return None


def _parse_slice_key(key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a slice key entry (one row of ``slices[].keys[]``)."""
    if not isinstance(key, dict):
        return None
    try:
        frame = int(key.get("frame", 0))
    except (TypeError, ValueError):
        return None
    bounds = _parse_rect(key.get("bounds"))
    if bounds is None:
        return None
    out: Dict[str, Any] = {"frame": frame, "bounds": bounds}
    center = _parse_rect(key.get("center"))
    if center is not None:
        out["center"] = center
    pivot = key.get("pivot")
    if isinstance(pivot, dict):
        try:
            out["pivot"] = {
                "x": int(pivot.get("x", 0)),
                "y": int(pivot.get("y", 0)),
            }
        except (TypeError, ValueError):
            pass
    return out


def _parse_slice(slc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw ``slices`` entry into a normalized dict."""
    out: Dict[str, Any] = {"name": str(slc.get("name", ""))}
    out.update(_parse_user_data(slc))
    keys_raw = slc.get("keys")
    keys: List[Dict[str, Any]] = []
    if isinstance(keys_raw, list):
        for raw_key in keys_raw:
            parsed = _parse_slice_key(raw_key)
            if parsed is not None:
                keys.append(parsed)
    out["keys"] = keys
    return out


def _build_aseprite_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ``ParseResult.metadata['aseprite']`` block."""
    block: Dict[str, Any] = {}
    for key in ("app", "version", "image", "format", "scale"):
        if key in meta:
            block[key] = meta[key]
    size = meta.get("size")
    if isinstance(size, dict):
        try:
            block["size"] = {
                "w": int(size.get("w", 0)),
                "h": int(size.get("h", 0)),
            }
        except (TypeError, ValueError):
            pass

    raw_tags = meta.get("frameTags")
    if isinstance(raw_tags, list):
        block["frame_tags"] = [
            _parse_frame_tag(tag) for tag in raw_tags if isinstance(tag, dict)
        ]

    raw_layers = meta.get("layers")
    if isinstance(raw_layers, list):
        block["layers"] = [
            _parse_layer(layer) for layer in raw_layers if isinstance(layer, dict)
        ]

    raw_slices = meta.get("slices")
    if isinstance(raw_slices, list):
        block["slices"] = [
            _parse_slice(slc) for slc in raw_slices if isinstance(slc, dict)
        ]

    return block


class AsepriteParser(BaseParser):
    """Parse Aseprite JSON atlas files with full metadata fidelity.

    Per :file:`src/app/doc_exporter.cpp`, the JSON document has the shape::

        {
          "frames": { name: { frame, rotated, trimmed, spriteSourceSize,
                              sourceSize, duration }, ... } | [...],
          "meta": { app, version, image, format, size, scale,
                    frameTags?, layers?, slices? }
        }

    Both hash-style (``json-hash``) and array-style (``json-array``)
    frames containers are accepted; ``json-array`` entries are expected
    to carry a ``filename`` attribute as Aseprite emits it.

    .. note:: Rotation direction.
        Aseprite's own packer never rotates samples (every frame is
        emitted with ``rotated: false``), but the JSON schema is
        inherited from TexturePacker and the ``rotated`` field is read
        verbatim. When ``rotated`` is ``True`` the convention used
        throughout this toolbox (and across the wider TexturePacker
        ecosystem) is that the sample in the atlas image was rotated
        **90° clockwise** relative to its source frame, so
        ``frame.w`` / ``frame.h`` describe the *post-rotation* slot
        and ``sourceSize`` / ``spriteSourceSize`` describe the
        unrotated source. To restore the original orientation a
        consumer rotates the sample 90° **counter-clockwise**.

    Attributes:
        FILE_EXTENSIONS: Supported file extensions (``.json``).
    """

    FILE_EXTENSIONS = (".json",)

    # Marker to identify Aseprite JSON files
    ASEPRITE_APP_MARKER = "aseprite.org"

    def __init__(
        self,
        directory: str,
        json_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the Aseprite parser.

        Args:
            directory: Directory containing the JSON file.
            json_filename: Name of the JSON file.
            name_callback: Optional callback invoked for each extracted name.
        """
        super().__init__(directory, json_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Extract unique animation/sprite base names from the JSON file.

        If frame tags are present, returns tag names (animation names).
        Otherwise, returns sprite names with trailing digits stripped.

        Returns:
            Set of animation or sprite base names.
        """
        data = self._load_json()

        meta = data.get("meta", {})
        frame_tags = meta.get("frameTags", [])
        if frame_tags:
            return {
                tag.get("name", "")
                for tag in frame_tags
                if isinstance(tag, dict) and tag.get("name")
            }

        names = self._frame_names(data.get("frames", {}))
        return {Utilities.strip_trailing_digits(name) for name in names}

    @staticmethod
    def _frame_names(frames: Any) -> List[str]:
        """Return the ordered list of frame filenames."""
        if isinstance(frames, dict):
            return list(frames.keys())
        if isinstance(frames, list):
            return [
                str(entry.get("filename", ""))
                for entry in frames
                if isinstance(entry, dict) and entry.get("filename")
            ]
        return []

    def _load_json(self) -> Dict[str, Any]:
        """Load and parse the JSON file.

        Returns:
            Parsed JSON data as a dictionary.

        Raises:
            FileError: If the file cannot be read.
            FormatError: If the JSON is malformed.
        """
        file_path = os.path.join(self.directory, self.filename)
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                return json.load(json_file)
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )
        except json.JSONDecodeError as e:
            raise FormatError(
                ParserErrorCode.MALFORMED_STRUCTURE,
                f"Invalid JSON: {e}",
                file_path=file_path,
            )

    @classmethod
    def is_aseprite_json(cls, data: Dict[str, Any]) -> bool:
        """Check if JSON data is from Aseprite export.

        Args:
            data: Parsed JSON dictionary.

        Returns:
            True if the data appears to be Aseprite format.
        """
        meta = data.get("meta", {})
        app = meta.get("app", "")

        if isinstance(app, str) and cls.ASEPRITE_APP_MARKER in app.lower():
            return True

        # Aseprite always includes frameTags (even if empty) and layers
        # when --list-tags / --list-layers were used.
        if "frameTags" in meta and "layers" in meta:
            return True

        # Fall back to the per-frame ``duration`` field that Aseprite
        # always emits (it is required by the JSON sheet schema).
        frames = data.get("frames", {})
        if isinstance(frames, dict) and frames:
            first_frame = next(iter(frames.values()))
            if isinstance(first_frame, dict) and "duration" in first_frame:
                return True
        elif isinstance(frames, list) and frames:
            first_frame = frames[0]
            if isinstance(first_frame, dict) and "duration" in first_frame:
                return True

        return False

    @classmethod
    def parse_from_frames(
        cls,
        frames: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert Aseprite frames container to a normalized sprite list.

        Args:
            frames: Either a dict (``json-hash``) or list (``json-array``)
                of frame entries as emitted by Aseprite.
            meta: Optional metadata dict with ``frameTags`` for
                animation lookup.

        Returns:
            List of normalized sprite dicts with Aseprite-specific fields.
        """
        sprites: List[Dict[str, Any]] = []
        normalized_tags: List[Dict[str, Any]] = []
        if meta:
            raw_tags = meta.get("frameTags", [])
            if isinstance(raw_tags, list):
                normalized_tags = [
                    _parse_frame_tag(tag) for tag in raw_tags if isinstance(tag, dict)
                ]

        if isinstance(frames, dict):
            ordered_entries = list(frames.items())
        elif isinstance(frames, list):
            ordered_entries = [
                (str(entry.get("filename", f"frame_{i}")), entry)
                for i, entry in enumerate(frames)
                if isinstance(entry, dict)
            ]
        else:
            return sprites

        for idx, (filename, entry) in enumerate(ordered_entries):
            frame = entry.get("frame", {})
            sprite_source = entry.get("spriteSourceSize", {})
            source_size = entry.get("sourceSize", {})
            try:
                frame_x = int(frame.get("x", 0))
                frame_y = int(frame.get("y", 0))
                frame_w = int(frame.get("w", 0))
                frame_h = int(frame.get("h", 0))
                source_x = int(sprite_source.get("x", 0))
                source_y = int(sprite_source.get("y", 0))
                source_w = int(source_size.get("w", frame_w))
                source_h = int(source_size.get("h", frame_h))
                duration = int(entry.get("duration", 100))
            except (TypeError, ValueError) as exc:
                raise ContentError(
                    ParserErrorCode.INVALID_COORDINATE,
                    f"Non-numeric coordinate in sprite '{filename}': {exc}",
                )

            rotated = bool(entry.get("rotated", False))
            trimmed = bool(entry.get("trimmed", False))

            sprite_data: Dict[str, Any] = {
                "name": filename,
                "x": frame_x,
                "y": frame_y,
                "width": frame_w,
                "height": frame_h,
                "frameX": -source_x,
                "frameY": -source_y,
                "frameWidth": source_w,
                "frameHeight": source_h,
                "rotated": rotated,
                "trimmed": trimmed,
                "duration": duration,
            }

            for tag in normalized_tags:
                if tag["from"] <= idx <= tag["to"]:
                    sprite_data["animation_tag"] = tag["name"]
                    sprite_data["animation_direction"] = tag["direction"]
                    if "repeat" in tag:
                        sprite_data["animation_repeat"] = tag["repeat"]
                    if "color" in tag:
                        sprite_data["animation_color"] = tag["color"]
                    if "data" in tag:
                        sprite_data["animation_data"] = tag["data"]
                    break

            sprites.append(sprite_data)

        return sprites

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse an Aseprite JSON atlas file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            ParseResult with sprites, warnings, and (when present)
            ``metadata['aseprite']`` carrying frame tags, layers, and
            slices for round-trip use by :class:`AsepriteExporter`.

        Raises:
            FileError: If the file cannot be read.
            FormatError: If the JSON structure is invalid.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)

        if not os.path.exists(file_path):
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )

        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
        except json.JSONDecodeError as e:
            raise FormatError(
                ParserErrorCode.MALFORMED_STRUCTURE,
                f"Invalid JSON: {e}",
                file_path=file_path,
            )

        frames = data.get("frames")
        if frames is None:
            raise FormatError(
                ParserErrorCode.MISSING_FRAMES_KEY,
                "Missing 'frames' key in JSON",
                file_path=file_path,
            )

        if not isinstance(frames, (dict, list)):
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                "Expected 'frames' to be either a dict (json-hash) or list (json-array)",
                file_path=file_path,
            )

        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}

        raw_sprites = cls.parse_from_frames(frames, meta)

        for raw_sprite in raw_sprites:
            try:
                normalized = cls.normalize_sprite(raw_sprite)
                # Preserve Aseprite-specific per-sprite fields
                for extra in (
                    "duration",
                    "trimmed",
                    "animation_tag",
                    "animation_direction",
                    "animation_repeat",
                    "animation_color",
                    "animation_data",
                ):
                    if extra in raw_sprite:
                        normalized[extra] = raw_sprite[extra]
                result.sprites.append(normalized)
            except Exception as e:
                result.add_error(
                    ParserErrorCode.SPRITE_PARSE_FAILED,
                    f"Failed to parse sprite: {e}",
                    sprite_name=raw_sprite.get("name", "unknown"),
                )

        # Attach the rich metadata block so an exporter can round-trip it.
        aseprite_meta = _build_aseprite_metadata(meta)
        if aseprite_meta:
            result.metadata = {"aseprite": aseprite_meta}

        if aseprite_meta.get("frame_tags"):
            tag_names = [t.get("name", "") for t in aseprite_meta["frame_tags"]]
            result.add_warning(
                ParserErrorCode.UNKNOWN_ERROR,  # Used as info marker
                f"Found {len(tag_names)} animation tags: {', '.join(tag_names)}",
            )

        return result

    @staticmethod
    def parse_json_data(file_path: str) -> List[Dict[str, Any]]:
        """Parse an Aseprite JSON file and return sprite metadata.

        Legacy method retained for the base parser interface.

        Args:
            file_path: Path to the JSON file.

        Returns:
            List of sprite dicts with position, dimension, and duration data.
        """
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
        frames = data.get("frames", {})
        meta = data.get("meta", {})
        return AsepriteParser.parse_from_frames(frames, meta)

    @classmethod
    def get_frame_tags(cls, file_path: str) -> List[Dict[str, Any]]:
        """Extract frame tags (animation definitions) from an Aseprite JSON.

        Args:
            file_path: Path to the JSON file.

        Returns:
            List of normalized frame-tag dicts. Each entry contains
            ``name``, ``from``, ``to``, ``direction``, and (when present
            in the source) ``repeat``, ``color``, ``data``,
            ``properties``.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )
        except json.JSONDecodeError as exc:
            raise FormatError(
                ParserErrorCode.MALFORMED_STRUCTURE,
                f"Invalid JSON in frame tags: {exc}",
                file_path=file_path,
            ) from exc
        except OSError as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                f"Cannot read file: {exc}",
                file_path=file_path,
            ) from exc
        meta = data.get("meta", {})
        raw_tags = meta.get("frameTags", []) if isinstance(meta, dict) else []
        if not isinstance(raw_tags, list):
            return []
        return [_parse_frame_tag(tag) for tag in raw_tags if isinstance(tag, dict)]

    @classmethod
    def get_animation_frames(
        cls,
        file_path: str,
        animation_name: str,
    ) -> List[Dict[str, Any]]:
        """Get frames belonging to a specific animation tag.

        Args:
            file_path: Path to the JSON file.
            animation_name: Name of the animation tag.

        Returns:
            List of sprite dicts for frames in the specified animation,
            in the order the tag spans them.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )
        except json.JSONDecodeError as exc:
            raise FormatError(
                ParserErrorCode.MALFORMED_STRUCTURE,
                f"Invalid JSON in animation frames: {exc}",
                file_path=file_path,
            ) from exc
        except OSError as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                f"Cannot read file: {exc}",
                file_path=file_path,
            ) from exc

        meta = data.get("meta", {})
        frames = data.get("frames", {})
        raw_tags = meta.get("frameTags", []) if isinstance(meta, dict) else []
        if not isinstance(raw_tags, list):
            return []

        target_tag = None
        for tag in raw_tags:
            if isinstance(tag, dict) and tag.get("name") == animation_name:
                target_tag = _parse_frame_tag(tag)
                break

        if not target_tag:
            return []

        from_idx = target_tag["from"]
        to_idx = target_tag["to"]

        if isinstance(frames, dict):
            frame_list = list(frames.items())
        elif isinstance(frames, list):
            frame_list = [
                (str(entry.get("filename", f"frame_{i}")), entry)
                for i, entry in enumerate(frames)
                if isinstance(entry, dict)
            ]
        else:
            return []

        animation_frames: List[Dict[str, Any]] = []

        for idx in range(from_idx, to_idx + 1):
            if idx >= len(frame_list):
                break
            filename, entry = frame_list[idx]
            frame = entry.get("frame", {})
            sprite_source = entry.get("spriteSourceSize", {})
            source_size = entry.get("sourceSize", {})

            try:
                frame_x = int(frame.get("x", 0))
                frame_y = int(frame.get("y", 0))
                frame_w = int(frame.get("w", 0))
                frame_h = int(frame.get("h", 0))
                source_x = int(sprite_source.get("x", 0))
                source_y = int(sprite_source.get("y", 0))
                source_w = int(source_size.get("w", frame_w))
                source_h = int(source_size.get("h", frame_h))
                duration = int(entry.get("duration", 100))
            except (TypeError, ValueError) as exc:
                raise ContentError(
                    ParserErrorCode.INVALID_COORDINATE,
                    f"Non-numeric coordinate in sprite '{filename}': {exc}",
                )

            sprite_data: Dict[str, Any] = {
                "name": filename,
                "x": frame_x,
                "y": frame_y,
                "width": frame_w,
                "height": frame_h,
                "frameX": -source_x,
                "frameY": -source_y,
                "frameWidth": source_w,
                "frameHeight": source_h,
                "rotated": bool(entry.get("rotated", False)),
                "trimmed": bool(entry.get("trimmed", False)),
                "duration": duration,
                "animation_tag": animation_name,
                "animation_direction": target_tag["direction"],
            }
            if "repeat" in target_tag:
                sprite_data["animation_repeat"] = target_tag["repeat"]
            if "color" in target_tag:
                sprite_data["animation_color"] = target_tag["color"]
            if "data" in target_tag:
                sprite_data["animation_data"] = target_tag["data"]
            animation_frames.append(sprite_data)

        return animation_frames


__all__ = ["AsepriteParser", "VALID_DIRECTIONS"]
