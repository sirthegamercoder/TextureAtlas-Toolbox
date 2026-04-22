#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser utilities for Adobe Spritemap Animation.json files.

Targets two related on-disk specs:

1. Adobe Animate's stock "Texture Atlas" exporter, which writes a single
   `Animation.json` plus one `spritemap.json` (with verbose `ATLAS.SPRITES`
   keys and a `meta.scale` field).
2. The Better Texture Atlas (BTA) Adobe Animate extension by Dot-Stuff,
   which extends the same family with: optimized one-letter keys
   (`AN` / `SD` / `MD`), numeric sprite names, *multiple* paged sheets
   (`spritemap1.json` ... `spritemapN.json`), an optional sibling
   `metadata.json` when symbols are not inlined, an optional `LIBRARY/`
   directory of external symbol files, and `meta.resolution` in place of
   `meta.scale`.

The parser surfaces both variants through a single `ParseResult.metadata`
shape under the `spritemap` key, while `extract_names` continues to read
only `Animation.json` (preserving the established extraction pipeline).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from parsers.base_parser import BaseParser
from parsers.parser_types import (
    ContentError,
    FileError,
    FormatError,
    ParseResult,
    ParserError,
    ParserErrorCode,
    normalize_sprite,
)
from utils.utilities import Utilities
from core.extractor.spritemap.metadata import (
    collect_direct_child_symbols,
    collect_referenced_symbols,
    compute_layers_length,
    compute_symbol_lengths,
    extract_label_ranges,
)
from core.extractor.spritemap.normalizer import normalize_animation_document


class SpritemapParser(BaseParser):
    """Extract animation names from Adobe Animate spritemap exports."""

    FILE_EXTENSIONS = (".json",)

    def __init__(
        self,
        directory: str,
        animation_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
        filter_single_frame: bool = True,
        filter_unused_symbols: bool = False,
        root_animation_only: bool = False,
    ) -> None:
        """Initialize the spritemap parser.

        Args:
            directory: Directory containing the Animation.json file.
            animation_filename: Name of the Animation.json file.
            name_callback: Optional callback invoked for each extracted name.
            filter_single_frame: If True, skip single-frame symbols.
            filter_unused_symbols: If True, skip symbols not referenced by
                the root animation timeline.
            root_animation_only: If True, only include the root animation
                name; skip individual symbols and timeline labels.
        """
        super().__init__(directory, animation_filename, name_callback)
        self.filter_single_frame = filter_single_frame
        self.filter_unused_symbols = filter_unused_symbols
        self.root_animation_only = root_animation_only

    def extract_names(self) -> Set[str]:
        """Extract animation and label names from the spritemap file.

        Returns:
            Set of animation names with trailing digits stripped.
        """
        names: Set[str] = set()
        animation_path = Path(self.directory) / self.filename
        try:
            with open(animation_path, "r", encoding="utf-8") as animation_file:
                animation_json = normalize_animation_document(json.load(animation_file))
        except FileNotFoundError:
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {animation_path}",
                file_path=str(animation_path),
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                str(exc),
                file_path=str(animation_path),
            )
        except json.JSONDecodeError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid JSON: {exc}",
                file_path=str(animation_path),
            )

        try:
            symbol_lengths = compute_symbol_lengths(animation_json)

            # Compute which symbols to show as standalone animations.
            # Direct children of the root timeline are the actual playable
            # animations; deeper nested symbols are internal helpers.
            direct_children = collect_direct_child_symbols(animation_json)
            if direct_children:
                referenced_symbols = direct_children
            elif self.filter_unused_symbols:
                referenced_symbols = collect_referenced_symbols(animation_json)
            else:
                referenced_symbols = None

            # Include the root animation (full AN timeline) name
            an = animation_json.get("AN", {})
            root_name = an.get("SN") or an.get("N")
            if root_name:
                root_layers = an.get("TL", {}).get("L", [])
                root_frame_count = compute_layers_length(root_layers)
                if not (self.filter_single_frame and root_frame_count <= 1):
                    names.add(root_name)

            if not self.root_animation_only:
                for symbol in animation_json.get("SD", {}).get("S", []):
                    raw_name = symbol.get("SN")
                    if raw_name:
                        if (
                            referenced_symbols is not None
                            and raw_name not in referenced_symbols
                        ):
                            continue
                        if (
                            self.filter_single_frame
                            and symbol_lengths.get(raw_name, 0) <= 1
                        ):
                            continue
                        names.add(Utilities.strip_trailing_digits(raw_name))

                for label in extract_label_ranges(animation_json, None):
                    frame_count = label["end"] - label["start"]
                    if self.filter_single_frame and frame_count <= 1:
                        continue
                    names.add(label["name"])
        except ParserError:
            raise
        except Exception as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Error parsing spritemap animation file {animation_path}: {exc}",
                file_path=str(animation_path),
            )
        return names

    def extract_raw_sprite_names(self) -> List[str]:
        """Return an empty list to preserve legacy extraction behaviour.

        Adobe Animate spritemap pages identify sprites by anonymous numeric
        IDs (`"0"`, `"1"`, ...). Those identifiers are not animation names
        and must not feed back into the smart-grouping pipeline used by
        :meth:`BaseParser.get_data`.
        """
        return []

    @classmethod
    def parse_file(cls, file_path: str) -> ParseResult:
        """Parse an Adobe Animate spritemap export.

        The returned `ParseResult.sprites` contains every atlas region
        discovered across all sibling `spritemap*.json` pages, with each
        sprite's `page` field tagged with its 1-indexed page number so
        multi-sheet BTA exports survive a load/save cycle. A
        `ParseResult.metadata["spritemap"]` block carries the per-page
        `meta` payloads, the export variant (`"stock"` or `"bta"`),
        the optional sibling `metadata.json` document fields, and the
        list of `LIBRARY/` external-symbol files when present.

        Args:
            file_path: Path to the `Animation.json` file. Sibling
                `spritemap*.json` files, `metadata.json`, and `LIBRARY/`
                are discovered relative to the same directory.

        Returns:
            ParseResult with sprites populated from every atlas page and
            a rich `metadata["spritemap"]` block.

        Raises:
            FileError: If `Animation.json` is missing or unreadable.
            FormatError: If `Animation.json` or any spritemap page is not
                a recognised Adobe Animate / BTA structure.
            ContentError: If no `spritemap*.json` page exists alongside
                `Animation.json`.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)

        animation_json = cls._read_animation_json(file_path, result)
        directory = Path(file_path).parent

        page_files = cls._discover_spritemap_pages(directory)
        if not page_files:
            raise ContentError(
                ParserErrorCode.MISSING_REQUIRED_KEY,
                f"No spritemap*.json page found alongside {file_path}",
                file_path=file_path,
            )

        pages_meta: List[Dict[str, Any]] = []
        sprite_index: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        is_bta = False

        for page_index, page_path in page_files:
            page_data = cls._read_spritemap_page(page_path, page_index)
            page_meta, page_sprites = cls._extract_page(
                page_data, page_path, page_index
            )
            if page_meta.get("variant") == "bta":
                is_bta = True
            pages_meta.append(page_meta)
            for sprite in page_sprites:
                try:
                    normalized = normalize_sprite(sprite)
                except ContentError as exc:
                    result.add_warning(
                        ParserErrorCode.INVALID_VALUE_TYPE,
                        f"page {page_index}: {exc}",
                    )
                    continue
                normalized["page"] = page_index
                result.sprites.append(normalized)
                sprite_index[normalized["name"]] = (page_index, normalized)

        document_meta = cls._read_metadata_json(directory)
        external_symbols = cls._discover_library_dir(directory)

        if document_meta or external_symbols:
            is_bta = True

        unresolved = cls._collect_unresolved_asi(animation_json, sprite_index)

        result.metadata = {
            "spritemap": {
                "variant": "bta" if is_bta else "stock",
                "pages": pages_meta,
                "document": document_meta,
                "external_symbols": external_symbols,
                "unresolved_sprites": unresolved,
            }
        }
        return result

    @classmethod
    def _read_animation_json(
        cls, file_path: str, result: ParseResult
    ) -> Dict[str, Any]:
        """Load and validate the Animation.json document."""
        path = Path(file_path)
        if not path.exists():
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"File not found: {file_path}",
                file_path=file_path,
            )
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = normalize_animation_document(json.load(fp))
        except json.JSONDecodeError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid JSON in Animation.json: {exc}",
                file_path=file_path,
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                str(exc),
                file_path=file_path,
            )
        if not isinstance(data, dict) or "AN" not in data:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                "Not a valid Adobe Animate Animation.json (missing AN/ANIMATION block)",
                file_path=file_path,
            )
        return data

    _PAGE_FILE_RE = re.compile(r"^spritemap(\d*)\.json$", re.IGNORECASE)

    @classmethod
    def _discover_spritemap_pages(cls, directory: Path) -> List[Tuple[int, Path]]:
        """Find every `spritemap*.json` sibling, sorted by page index.

        Stock Adobe Animate writes a single `spritemap.json`. BTA writes
        `spritemap1.json`, `spritemap2.json`, ... contiguously when an
        export overflows. A bare `spritemap.json` is treated as page 1.
        """
        if not directory.is_dir():
            return []
        found: List[Tuple[int, Path]] = []
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            match = cls._PAGE_FILE_RE.match(entry.name)
            if not match:
                continue
            digits = match.group(1)
            page_index = int(digits) if digits else 1
            found.append((page_index, entry))
        found.sort(key=lambda item: item[0])
        return found

    @classmethod
    def _read_spritemap_page(cls, page_path: Path, page_index: int) -> Dict[str, Any]:
        """Load a single `spritemap*.json` page."""
        try:
            with open(page_path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except json.JSONDecodeError as exc:
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Invalid JSON in spritemap page {page_index} ({page_path.name}): {exc}",
                file_path=str(page_path),
                details={"page": page_index},
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise FileError(
                ParserErrorCode.FILE_READ_ERROR,
                str(exc),
                file_path=str(page_path),
            )

    _BTA_APP_SUFFIX = "(Better TA Extension)"

    @classmethod
    def _extract_page(
        cls,
        page_data: Dict[str, Any],
        page_path: Path,
        page_index: int,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Pull `meta` and `ATLAS.SPRITES` out of a single page."""
        atlas = page_data.get("ATLAS") if isinstance(page_data, dict) else None
        if not isinstance(atlas, dict):
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Spritemap page {page_index} ({page_path.name}) missing ATLAS block",
                file_path=str(page_path),
                details={"page": page_index},
            )

        sprites_field = atlas.get("SPRITES", [])
        if not isinstance(sprites_field, list):
            raise FormatError(
                ParserErrorCode.INVALID_FORMAT,
                f"Spritemap page {page_index} ATLAS.SPRITES must be a list",
                file_path=str(page_path),
                details={"page": page_index},
            )

        sprites: List[Dict[str, Any]] = []
        for entry in sprites_field:
            if not isinstance(entry, dict):
                continue
            data = entry["SPRITE"] if isinstance(entry.get("SPRITE"), dict) else entry
            name = data.get("name")
            if name is None:
                continue
            sprites.append(
                {
                    "name": str(name),
                    "x": data.get("x", 0),
                    "y": data.get("y", 0),
                    "width": data.get("w", 0),
                    "height": data.get("h", 0),
                    "rotated": bool(data.get("rotated", False)),
                }
            )

        meta_block = page_data.get("meta") if isinstance(page_data, dict) else None
        if not isinstance(meta_block, dict):
            meta_block = {}

        app = meta_block.get("app")
        is_bta = isinstance(app, str) and app.endswith(cls._BTA_APP_SUFFIX)

        # Normalise scale/resolution into a single numeric value while
        # preserving the original key on the meta block so round-trips
        # do not lose which spelling the export used.
        resolution_value = cls._coerce_float(
            meta_block.get("resolution") or meta_block.get("scale")
        )

        page_meta: Dict[str, Any] = {
            "page": page_index,
            "file": page_path.name,
            "image": meta_block.get("image"),
            "format": meta_block.get("format"),
            "size": meta_block.get("size"),
            "scale": meta_block.get("scale"),
            "resolution": (
                meta_block.get("resolution") if "resolution" in meta_block else None
            ),
            "resolution_value": resolution_value,
            "app": app,
            "version": meta_block.get("version"),
            "variant": "bta" if is_bta else "stock",
            "image_missing": cls._image_missing(page_path, meta_block.get("image")),
            "sprite_count": len(sprites),
        }
        return page_meta, sprites

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        """Best-effort conversion of `meta.scale`/`meta.resolution` to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _image_missing(page_path: Path, image_name: Optional[Any]) -> bool:
        """Return True when the page declares an image that is absent on disk."""
        if not isinstance(image_name, str) or not image_name:
            return False
        return not (page_path.parent / image_name).exists()

    @staticmethod
    def _read_metadata_json(directory: Path) -> Dict[str, Any]:
        """Load BTA's optional sibling `metadata.json`, if present."""
        candidate = directory / "metadata.json"
        if not candidate.is_file():
            return {}
        try:
            with open(candidate, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _discover_library_dir(directory: Path) -> Dict[str, str]:
        """List BTA's `LIBRARY/` external symbol files by stem."""
        library = directory / "LIBRARY"
        if not library.is_dir():
            return {}
        entries: Dict[str, str] = {}
        for path in library.rglob("*.json"):
            relative = path.relative_to(library).as_posix()
            stem = relative[: -len(".json")] if relative.endswith(".json") else relative
            entries[stem] = relative
        return entries

    @classmethod
    def _collect_unresolved_asi(
        cls,
        animation_json: Dict[str, Any],
        sprite_index: Dict[str, Tuple[int, Dict[str, Any]]],
    ) -> List[str]:
        """Return ASI/ATLAS_SPRITE_instance names not present in any page."""
        seen: Set[str] = set()
        unresolved: List[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if "ASI" in node or "ATLAS_SPRITE_instance" in node:
                    asi = node.get("ASI") or node.get("ATLAS_SPRITE_instance")
                    if isinstance(asi, dict):
                        name = asi.get("N") or asi.get("name")
                        if name is not None:
                            key = str(name)
                            if key not in sprite_index and key not in seen:
                                seen.add(key)
                                unresolved.append(key)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(animation_json)
        return unresolved

    @staticmethod
    def is_spritemap_animation(file_path: str) -> bool:
        """Check if a JSON file is an Adobe Spritemap Animation.json.

        Args:
            file_path: Path to check.

        Returns:
            True if this is a spritemap Animation.json file.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = normalize_animation_document(json.load(f))
            return "SD" in data or ("ATLAS" in data and "AN" in data)
        except Exception:
            return False


__all__ = ["SpritemapParser"]
