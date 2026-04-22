#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for legacy CSS spritesheet format.

Reads CSS class blocks emitted by tools such as TexturePacker's CSS
exporter, SpriteSmith, Glue, and sprity. Recognises:

    background / background-image / background-position
        Negative offsets are interpreted as the sprite's atlas
        position (`x = -bg_x`, `y = -bg_y`).
    width / height
        Atlas region size in pixels.
    transform: rotate(-90deg)
        90 degree clockwise rotation marker. Two emission geometries
        are supported:

        * "Centre-pivoted" (legacy / pre-3.0.0): the exporter
          pre-swapped ``width`` / ``height`` to the displayed (rotated)
          size. The parser swaps them back to recover the source
          dimensions when ``rotate(...)`` appears alone.
        * "Top-left + translate" (default since 3.0.0): the exporter
          uses ``transform-origin: 0 0`` plus a compensating
          ``translateY(<atlas_w>px)`` so the rotated content stays in
          its layout slot. The parser detects the accompanying
          ``translateY(...)`` term and treats ``width`` / ``height`` as
          the atlas-region dimensions directly.

    margin-left / margin-top
        Negative trim offsets emitted by SpriteSmith / Glue / sprity
        for trimmed sprites; surfaced as `frameX` / `frameY` (with
        the sign flipped to match the project's convention) so trim
        is preserved on round-trip.

    /* tat: ... */
        Round-trip metadata comment emitted by `CssExporter` since
        v3.0.0. Carries ``x``, ``y``, ``w``, ``h``, optional
        ``frameX`` / ``frameY`` / ``frameW`` / ``frameH``, and
        ``rotated``. Authoritative when present, since the
        spec-correct ``trim_mode="background-position"`` collapses
        atlas and frame geometry into a single ``background-position``
        offset and otherwise loses the atlas-region size.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Set

from parsers.base_parser import BaseParser
from parsers.parser_types import FileError, ParserErrorCode
from utils.utilities import Utilities


_CLASS_BLOCK_RE = re.compile(
    r"\.([A-Za-z0-9_\-]+)\s*\{(.*?)\}", re.DOTALL | re.IGNORECASE
)
_BACKGROUND_RE = re.compile(
    r"background(?:-position)?\s*:[^;]*?(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px",
    re.IGNORECASE,
)
_WIDTH_RE = re.compile(r"width\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
_HEIGHT_RE = re.compile(r"height\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
_MARGIN_LEFT_RE = re.compile(r"margin-left\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
_MARGIN_TOP_RE = re.compile(r"margin-top\s*:\s*(-?\d+(?:\.\d+)?)px", re.IGNORECASE)
_TRANSFORM_ROTATE_RE = re.compile(
    r"transform\s*:[^;]*\brotate\(\s*(-?\d+(?:\.\d+)?)deg\s*\)",
    re.IGNORECASE,
)
_TRANSFORM_TRANSLATE_Y_RE = re.compile(
    r"transform\s*:[^;]*\btranslateY?\s*\(\s*(-?\d+(?:\.\d+)?)px",
    re.IGNORECASE,
)
# Round-trip metadata comment emitted by `CssExporter` since v3.0.0.
# Format: ``/* tat: x=N y=N w=N h=N [frameX=N frameY=N frameW=N frameH=N]
# [rotated=1] */``. Reading this restores the source geometry losslessly
# even when the active exporter mode hides it from the rendered CSS
# properties (e.g. the spec-correct trim mode collapses both atlas and
# frame size into a single background-position offset).
_ROUND_TRIP_COMMENT_RE = re.compile(
    r"/\*\s*tat:\s*([^*]+?)\s*\*/", re.IGNORECASE | re.DOTALL
)
_ROUND_TRIP_FIELD_RE = re.compile(r"([A-Za-z]+)\s*=\s*(-?\d+)")


class CssLegacyParser(BaseParser):
    """Parse CSS spritesheet exports from TexturePacker / SpriteSmith / Glue / sprity."""

    FILE_EXTENSIONS = (".css",)

    def __init__(
        self,
        directory: str,
        css_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the legacy CSS parser.

        Args:
            directory: Directory containing the CSS file.
            css_filename: Name of the CSS file.
            name_callback: Optional callback invoked for each base
                name produced by `extract_names`.

        Returns:
            None.
        """
        super().__init__(directory, css_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Extract unique animation/sprite base names from the CSS file.

        Returns:
            Set of sprite base names with trailing digits stripped.
        """
        sprites = self._parse_css()
        return {Utilities.strip_trailing_digits(entry["name"]) for entry in sprites}

    def _parse_css(self) -> List[Dict[str, int]]:
        """Parse the configured CSS file from disk.

        Returns:
            List of sprite dicts with position, dimension, trim, and
            rotation data.
        """
        file_path = os.path.join(self.directory, self.filename)
        return self.parse_css_data(file_path)

    @staticmethod
    def parse_css_data(file_path: str) -> List[Dict[str, int]]:
        """Parse a CSS file and extract sprite definitions.

        Args:
            file_path: Path to the CSS file.

        Returns:
            List of sprite dicts with keys `name`, `x`, `y`, `width`,
            `height`, `frameX`, `frameY`, `frameWidth`, `frameHeight`,
            `rotated`.

        Raises:
            FileError: If the file cannot be opened or read.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as css_file:
                content = css_file.read()
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"CSS file not found: {file_path}",
                file_path=file_path,
            )
        except OSError as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                f"Cannot read CSS file: {exc}",
                file_path=file_path,
            ) from exc

        sprites: List[Dict[str, int]] = []
        for match in _CLASS_BLOCK_RE.finditer(content):
            name = match.group(1)
            body = match.group(2)

            tat_meta = CssLegacyParser._parse_round_trip_comment(body)

            bg_match = _BACKGROUND_RE.search(body)
            width_match = _WIDTH_RE.search(body)
            height_match = _HEIGHT_RE.search(body)

            if not (bg_match and width_match and height_match) and not tat_meta:
                continue

            rotate_match = _TRANSFORM_ROTATE_RE.search(body)
            translate_match = _TRANSFORM_TRANSLATE_Y_RE.search(body)
            rotated_from_css = False
            if rotate_match:
                degrees = CssLegacyParser._parse_float(rotate_match.group(1))
                normalized = ((int(round(degrees)) % 360) + 360) % 360
                rotated_from_css = normalized in (90, 270)

            margin_left_match = _MARGIN_LEFT_RE.search(body)
            margin_top_match = _MARGIN_TOP_RE.search(body)
            margin_left = (
                CssLegacyParser._parse_float(margin_left_match.group(1))
                if margin_left_match
                else 0.0
            )
            margin_top = (
                CssLegacyParser._parse_float(margin_top_match.group(1))
                if margin_top_match
                else 0.0
            )

            if tat_meta is not None:
                # The round-trip comment is authoritative when present:
                # the spec-correct trim mode collapses atlas and frame
                # geometry into a single background-position, so the
                # CSS properties alone cannot recover it.
                sprite_data = CssLegacyParser._sprite_from_tat_meta(name, tat_meta)
                sprites.append(sprite_data)
                continue

            x_offset = CssLegacyParser._parse_float(bg_match.group(1))
            y_offset = CssLegacyParser._parse_float(bg_match.group(2))
            display_w = CssLegacyParser._parse_float(width_match.group(1))
            display_h = CssLegacyParser._parse_float(height_match.group(1))

            rotated = rotated_from_css

            # Two rotation geometries are possible:
            #
            # * Legacy ("centre-pivoted"): the exporter pre-swapped
            #   width / height to displayed size. Recovering the source
            #   means swapping them back. Detected by a bare ``rotate(...)``
            #   without an accompanying ``translate*`` term.
            # * New ("top-left + translate"): width / height already
            #   carry the atlas-region dimensions. Detected by the
            #   presence of ``translateY(...)`` alongside the rotate.
            if rotated and translate_match is None:
                src_w = int(round(display_h))
                src_h = int(round(display_w))
            else:
                src_w = int(round(display_w))
                src_h = int(round(display_h))

            frame_x = -int(round(margin_left))
            frame_y = -int(round(margin_top))

            original_w = src_w + abs(frame_x) if frame_x else src_w
            original_h = src_h + abs(frame_y) if frame_y else src_h

            sprite_data = {
                "name": name,
                "x": int(round(-x_offset)),
                "y": int(round(-y_offset)),
                "width": src_w,
                "height": src_h,
                "frameX": frame_x,
                "frameY": frame_y,
                "frameWidth": original_w,
                "frameHeight": original_h,
                "rotated": rotated,
            }
            sprites.append(sprite_data)
        return sprites

    @staticmethod
    def _parse_round_trip_comment(body: str) -> Optional[Dict[str, int]]:
        """Extract a ``/* tat: ... */`` round-trip marker from a rule body.

        Args:
            body: Raw text between the rule's ``{`` and ``}``.

        Returns:
            Dict of decoded fields (``x``, ``y``, ``w``, ``h``, optional
            ``frameX`` / ``frameY`` / ``frameW`` / ``frameH`` / ``rotated``),
            or ``None`` when the marker is absent or malformed.
        """
        comment = _ROUND_TRIP_COMMENT_RE.search(body)
        if comment is None:
            return None
        fields: Dict[str, int] = {}
        for field_match in _ROUND_TRIP_FIELD_RE.finditer(comment.group(1)):
            fields[field_match.group(1).lower()] = int(field_match.group(2))
        if not {"x", "y", "w", "h"}.issubset(fields):
            return None
        return fields

    @staticmethod
    def _sprite_from_tat_meta(name: str, meta: Dict[str, int]) -> Dict[str, int]:
        """Build a sprite dict from a decoded round-trip comment.

        Args:
            name: Sprite name (CSS class identifier).
            meta: Decoded ``/* tat: ... */`` field map.

        Returns:
            Sprite dict mirroring the structure produced by the
            heuristic CSS-property path.
        """
        atlas_w = int(meta["w"])
        atlas_h = int(meta["h"])
        frame_x = int(meta.get("framex", 0))
        frame_y = int(meta.get("framey", 0))
        frame_w = int(meta.get("framew", atlas_w))
        frame_h = int(meta.get("frameh", atlas_h))
        rotated = bool(meta.get("rotated", 0))
        return {
            "name": name,
            "x": int(meta["x"]),
            "y": int(meta["y"]),
            "width": atlas_w,
            "height": atlas_h,
            "frameX": frame_x,
            "frameY": frame_y,
            "frameWidth": frame_w,
            "frameHeight": frame_h,
            "rotated": rotated,
        }

    @staticmethod
    def _parse_float(value: Optional[str]) -> float:
        """Safely parse a string to float, defaulting to 0.0 on failure.

        Args:
            value: String value to parse.

        Returns:
            Parsed float, or `0.0` when `value` is `None` or
            unparseable.
        """
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


__all__ = ["CssLegacyParser"]
