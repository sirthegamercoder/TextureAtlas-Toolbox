#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for Paper2D/Unreal atlas JSON metadata.

Paper2D's ``.paper2dsprites`` file is the standard TexturePacker JSON
hash structure with the ``pivot`` field treated as optional. Some
Unreal projects ship atlases where pivots are intentionally omitted so
the importer can fall back to the project default. ``parse_from_frames``
only attaches ``pivotX`` / ``pivotY`` to a sprite when the source frame
carried an explicit ``pivot`` block, so the matching exporter's
``pivot_mode="auto"`` mode can faithfully round-trip both forms.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Set

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    FileError,
    FormatError,
    ParseResult,
    ParserError,
    ParserErrorCode,
    normalize_sprite,
)
from utils.utilities import Utilities


class Paper2DParser(BaseParser):
    """Parse Paper2D (Unreal) JSON atlases (hash-style frames)."""

    FILE_EXTENSIONS = (".paper2dsprites",)

    def __init__(
        self,
        directory: str,
        json_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the Paper2D parser.

        Args:
            directory: Directory containing the JSON file.
            json_filename: Name of the JSON file.
            name_callback: Optional callback invoked for each extracted name.
        """
        super().__init__(directory, json_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Extract unique animation/sprite base names from the JSON file.

        Returns:
            Set of sprite names with trailing digits stripped.
        """
        data = self._load_json()
        frames: Dict[str, Dict[str, Any]] = data.get("frames", {})
        return {Utilities.strip_trailing_digits(name) for name in frames.keys()}

    def _load_json(self) -> Dict[str, Any]:
        """Load and parse the JSON file.

        Returns:
            Parsed JSON data as a dictionary.

        Raises:
            FileError: If the file cannot be found or read.
            FormatError: If the file contains invalid JSON.
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

    @classmethod
    def parse_from_frames(
        cls, frames: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert a frames hash to normalized sprite list.

        Args:
            frames: Dictionary mapping sprite names to frame metadata.

        Returns:
            List of normalized sprite dicts. ``pivotX`` and ``pivotY``
            are only present on sprites whose source frame declared a
            ``pivot`` block, preserving the distinction between
            "explicit pivot" and "importer default" required for a
            faithful round-trip with the matching exporter's
            ``pivot_mode="auto"``.
        """
        sprites: List[Dict[str, Any]] = []
        for filename, entry in frames.items():
            frame = entry.get("frame", {})
            frame_x = int(frame.get("x", 0))
            frame_y = int(frame.get("y", 0))
            frame_w = int(frame.get("w", 0))
            frame_h = int(frame.get("h", 0))

            sprite_source = entry.get("spriteSourceSize", {})
            source_size = entry.get("sourceSize", {})
            rotated = bool(entry.get("rotated", False))

            sprite_data: Dict[str, Any] = {
                "name": filename,
                "x": frame_x,
                "y": frame_y,
                "width": frame_w,
                "height": frame_h,
                "frameX": -int(sprite_source.get("x", 0)),
                "frameY": -int(sprite_source.get("y", 0)),
                "frameWidth": int(source_size.get("w", frame_w)),
                "frameHeight": int(source_size.get("h", frame_h)),
                "rotated": rotated,
            }

            pivot = entry.get("pivot")
            if isinstance(pivot, dict):
                sprite_data["pivotX"] = float(pivot.get("x", 0.5))
                sprite_data["pivotY"] = float(pivot.get("y", 0.5))

            sprites.append(sprite_data)
        return sprites

    @staticmethod
    def parse_json_data(file_path: str) -> List[Dict[str, Any]]:
        """Parse a Paper2D atlas file and return sprite metadata.

        Args:
            file_path: Path to the JSON file.

        Returns:
            List of sprite dicts with position, dimension, and pivot data.
        """
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
        frames = data.get("frames", {})
        return Paper2DParser.parse_from_frames(frames)

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse a Paper2D atlas file with full meta-block metadata.

        Captures the source ``meta`` block into
        ``ParseResult.metadata["paper2d"]["meta"]`` so the matching
        exporter can round-trip it. Per-sprite ``pivotX`` / ``pivotY``
        are carried on each sprite dict by :py:meth:`parse_from_frames`,
        but only when the source frame actually declared a ``pivot``
        block — sprites whose source frames omitted ``pivot`` come
        back without the keys, which lets the exporter's
        ``pivot_mode="auto"`` mode faithfully preserve the original
        per-frame pivot presence.

        Args:
            file_path: Absolute path to the ``.paper2dsprites`` file.

        Returns:
            ParseResult with normalised sprites and a
            ``metadata["paper2d"]`` block containing ``meta`` and a
            boolean ``had_pivot_default`` summarising whether at least
            one source frame carried an explicit pivot.

        Raises:
            FileError: If the file is missing or unreadable.
            FormatError: If the JSON is invalid or missing ``frames``.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
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

        frames = data.get("frames")
        if not isinstance(frames, dict):
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                "Paper2D atlas requires a 'frames' object mapping name -> frame data",
                file_path=file_path,
            )

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        had_pivot = any(
            isinstance(entry, dict) and isinstance(entry.get("pivot"), dict)
            for entry in frames.values()
        )
        result.metadata = {
            "paper2d": {
                "meta": dict(meta),
                "had_pivot_default": had_pivot,
            }
        }

        for raw_sprite in cls.parse_from_frames(frames):
            try:
                normalized = normalize_sprite(raw_sprite)
            except ParserError as exc:
                result.add_warning(
                    ParserErrorCode.INVALID_VALUE_TYPE,
                    str(exc),
                )
                continue
            for optional_key in ("pivotX", "pivotY"):
                if optional_key in raw_sprite:
                    normalized[optional_key] = raw_sprite[optional_key]
            result.sprites.append(normalized)

        return result


__all__ = ["Paper2DParser"]
