#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""TexturePacker XML parser (``<sprite>`` nodes with shorthand attributes).

The TexturePacker "Generic XML" data exporter emits ``<sprite>`` elements
using the shorthand attribute names ``n, x, y, w, h, r, oX, oY, oW, oH,
pX, pY``. A number of homebrew exporters use the long form ``name=`` in
place of ``n=``; both are accepted here. When both are present on the
same element with conflicting values the parser keeps ``n`` (matching
TexturePacker's own template) and surfaces a warning via
``ParseResult``.

Booleans for ``r`` are parsed strictly: only ``y / yes / true / 1`` (and
their false counterparts ``n / no / false / 0``, plus the empty string)
are recognised. Anything else still resolves to ``False`` for backwards
compatibility but produces a warning when the file is parsed via
:py:meth:`TexturePackerXmlParser.parse_file`.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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

_TRUE_BOOL_TOKENS = frozenset({"y", "yes", "true", "1", "t"})
_FALSE_BOOL_TOKENS = frozenset({"n", "no", "false", "0", "f", ""})


class TexturePackerXmlParser(BaseParser):
    """Parse TexturePacker XML exports that use ``<sprite>`` elements."""

    FILE_EXTENSIONS = (".xml",)

    SPRITE_TAG = "sprite"

    def __init__(
        self,
        directory: str,
        xml_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the TexturePacker XML parser.

        Args:
            directory: Directory containing the XML file.
            xml_filename: Name of the XML file.
            name_callback: Optional callback invoked for each extracted name.
        """
        super().__init__(directory, xml_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Extract unique animation/sprite base names from the XML file.

        Returns:
            Set of sprite names with trailing digits stripped.

        Raises:
            FileError: If the file cannot be found or read.
            FormatError: If the file contains invalid XML.
        """
        file_path = os.path.join(self.directory, self.filename)
        try:
            tree = ET.parse(file_path)
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
        except ET.ParseError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid XML: {exc}",
                file_path=file_path,
            )
        xml_root = tree.getroot()
        return self.extract_names_from_root(xml_root)

    @classmethod
    def matches_root(cls, xml_root) -> bool:
        """Check if the XML root matches TexturePacker sprite format.

        Args:
            xml_root: The root element of the parsed XML tree.

        Returns:
            True if root is TextureAtlas with sprite children but no SubTexture.
        """
        return (
            xml_root.tag == "TextureAtlas"
            and xml_root.find(cls.SPRITE_TAG) is not None
            and xml_root.find("SubTexture") is None
        )

    @staticmethod
    def extract_names_from_root(xml_root) -> Set[str]:
        """Extract sprite names from an already-parsed XML root.

        Args:
            xml_root: The root element containing sprite children.

        Returns:
            Set of sprite names with trailing digits stripped.
        """
        names: Set[str] = set()
        for sprite in xml_root.findall(".//sprite"):
            name = sprite.get("n") or sprite.get("name")
            if name:
                names.add(Utilities.strip_trailing_digits(name))
        return names

    @classmethod
    def _resolve_sprite_name(
        cls,
        sprite: ET.Element,
    ) -> Tuple[Optional[str], str, Optional[str]]:
        """Resolve a sprite's name across the ``n`` / ``name`` attribute pair.

        Args:
            sprite: The ``<sprite>`` element to inspect.

        Returns:
            ``(name, style, conflict_message)`` where ``style`` is one of
            ``"short"`` (``n=`` was used), ``"long"`` (``name=`` only), or
            ``"missing"`` (neither attribute is set), and
            ``conflict_message`` is a non-empty string describing the
            conflict when both attributes are present with different
            values, ``None`` otherwise.
        """
        short = sprite.get("n")
        long = sprite.get("name")
        conflict: Optional[str] = None
        if short is not None and long is not None and short != long:
            conflict = (
                f"<sprite> has conflicting n={short!r} and name={long!r}; "
                f"using n={short!r}"
            )
        if short is not None:
            return short, "short", conflict
        if long is not None:
            return long, "long", conflict
        return None, "missing", conflict

    @classmethod
    def parse_from_root(cls, xml_root) -> List[Dict[str, Any]]:
        """Parse sprite metadata from an already-parsed XML root.

        Args:
            xml_root: The root element containing sprite children.

        Returns:
            List of sprite dicts with position, dimension, and pivot data.
        """
        sprites: List[Dict[str, Any]] = []
        for sprite in xml_root.findall("sprite"):
            name, _style, _conflict = cls._resolve_sprite_name(sprite)
            sprite_data = {
                "name": name,
                "x": cls._parse_int(sprite.get("x"), default=0),
                "y": cls._parse_int(sprite.get("y"), default=0),
                "width": cls._parse_int(sprite.get("w"), default=0),
                "height": cls._parse_int(sprite.get("h"), default=0),
                "frameX": cls._parse_int(sprite.get("oX"), default=0),
                "frameY": cls._parse_int(sprite.get("oY"), default=0),
                "frameWidth": cls._parse_int(sprite.get("oW"), default=None),
                "frameHeight": cls._parse_int(sprite.get("oH"), default=None),
                "rotated": cls._parse_bool(sprite.get("r")),
                "pivotX": cls._parse_float(sprite.get("pX"), 0.5),
                "pivotY": cls._parse_float(sprite.get("pY"), 0.5),
            }
            if sprite_data["frameWidth"] is None:
                sprite_data["frameWidth"] = sprite_data["width"]
            if sprite_data["frameHeight"] is None:
                sprite_data["frameHeight"] = sprite_data["height"]
            sprites.append(sprite_data)
        return sprites

    @staticmethod
    def _parse_int(value, default: Optional[int] = 0) -> Optional[int]:
        """Parse an integer from a string value.

        Args:
            value: The string value to parse.
            default: Value returned on failure.

        Returns:
            The parsed integer or default.
        """
        if value is None:
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_float(value, default: float = 0.0) -> float:
        """Parse a float from a string value.

        Args:
            value: The string value to parse.
            default: Value returned on failure.

        Returns:
            The parsed float or default.
        """
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_bool(value) -> bool:
        """Parse a boolean from a TexturePacker-style XML attribute.

        Args:
            value: The raw attribute string (e.g. ``'y'``, ``'true'``,
                ``'1'``). ``None`` and the empty string both resolve to
                ``False``.

        Returns:
            ``True`` if the value lower-cases to one of the recognised
            truthy tokens (``y / yes / true / 1 / t``), ``False``
            otherwise. Unrecognised values resolve to ``False`` for
            backwards compatibility; use
            :py:meth:`_classify_bool` to detect them.
        """
        if value is None:
            return False
        return str(value).strip().lower() in _TRUE_BOOL_TOKENS

    @staticmethod
    def _classify_bool(value) -> Tuple[bool, bool]:
        """Classify a boolean attribute as ``(parsed, recognised)``.

        Args:
            value: The raw attribute string.

        Returns:
            A ``(parsed, recognised)`` pair. ``parsed`` is the same
            value returned by :py:meth:`_parse_bool`; ``recognised`` is
            ``False`` when ``value`` is non-empty and does not match any
            known truthy or falsy token, signalling a malformed input
            that should generate a parse warning.
        """
        if value is None:
            return False, True
        token = str(value).strip().lower()
        if token in _TRUE_BOOL_TOKENS:
            return True, True
        if token in _FALSE_BOOL_TOKENS:
            return False, True
        return False, False

    @staticmethod
    def parse_xml_data(file_path: str) -> List[Dict[str, Any]]:
        """Parse a TexturePacker XML file and return sprite metadata.

        Args:
            file_path: Path to the XML file.

        Returns:
            List of sprite dicts with position, dimension, and pivot data.
        """
        try:
            tree = ET.parse(file_path)
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
        except ET.ParseError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid XML: {exc}",
                file_path=file_path,
            )
        xml_root = tree.getroot()
        return TexturePackerXmlParser.parse_from_root(xml_root)

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse a TexturePacker generic XML file with full root metadata.

        Captures the root ``<TextureAtlas>`` attributes (``imagePath``,
        ``width``, ``height``) and the per-file attribute style usage
        (whether sprites are keyed by ``n=`` or ``name=``) into
        ``ParseResult.metadata["texturepacker_xml"]`` so the matching
        exporter can round-trip them. Conflicting ``n`` / ``name`` pairs
        and unrecognised ``r`` values surface as warnings on the
        ``ParseResult`` rather than being silently swallowed.

        Args:
            file_path: Absolute path to the TexturePacker XML file.

        Returns:
            ParseResult with normalised sprites and a
            ``metadata["texturepacker_xml"]`` block containing the root
            attributes and the resolved attribute style.

        Raises:
            FileError: If the file is missing or unreadable.
            FormatError: If the XML is invalid or not a TextureAtlas
                root populated with ``<sprite>`` children.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)
        try:
            tree = ET.parse(file_path)
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
        except ET.ParseError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid XML: {exc}",
                file_path=file_path,
            )

        xml_root = tree.getroot()
        if xml_root.tag != "TextureAtlas":
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Expected <TextureAtlas> root, got <{xml_root.tag}>",
                file_path=file_path,
            )

        atlas_width = cls._parse_int(xml_root.get("width"), default=None)
        atlas_height = cls._parse_int(xml_root.get("height"), default=None)

        style_counts: Dict[str, int] = {"short": 0, "long": 0}
        for sprite_elem in xml_root.findall("sprite"):
            _name, style, conflict = cls._resolve_sprite_name(sprite_elem)
            if style in style_counts:
                style_counts[style] += 1
            if conflict:
                result.add_warning(
                    ParserErrorCode.INVALID_VALUE_TYPE,
                    conflict,
                )
            r_value = sprite_elem.get("r")
            _, recognised = cls._classify_bool(r_value)
            if not recognised:
                result.add_warning(
                    ParserErrorCode.INVALID_VALUE_TYPE,
                    f"<sprite> has unrecognised r={r_value!r}; "
                    f"treating as not rotated",
                )

        if style_counts["short"] and not style_counts["long"]:
            attribute_style: str = "short"
        elif style_counts["long"] and not style_counts["short"]:
            attribute_style = "long"
        elif style_counts["short"] or style_counts["long"]:
            attribute_style = "mixed"
        else:
            attribute_style = "short"

        result.metadata = {
            "texturepacker_xml": {
                "image_path": xml_root.get("imagePath"),
                "width": atlas_width,
                "height": atlas_height,
                "attribute_style": attribute_style,
            }
        }

        for raw_sprite in cls.parse_from_root(xml_root):
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
