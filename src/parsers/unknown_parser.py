#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from typing import Set, Optional, Callable, List, Dict, Any, Tuple
from PIL import Image
import numpy as np

# Import our own modules
from parsers.base_parser import BaseParser
from parsers.parser_types import (
    ParseResult,
    ParserErrorCode,
    FileError,
    FormatError,
    validate_sprites,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Qt imports
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QApplication


class UnknownParser(BaseParser):
    """Fallback parser for images without metadata files.

    Uses computer vision (flood fill) to detect sprite regions from the image's
    alpha channel. Can optionally detect and remove solid background colors.

    Note: This parser handles image files directly, not metadata files.
    FILE_EXTENSIONS is empty because it's used as a fallback for any image type.
    """

    FILE_EXTENSIONS = ()  # Used as fallback for any image, not extension-based

    @classmethod
    def parse_file(cls, file_path: str, parent_window=None) -> ParseResult:
        """Parse an image file using computer vision sprite detection.

        Args:
            file_path: Path to the image file.
            parent_window: Optional parent for dialogs.

        Returns:
            ParseResult with detected sprite regions.
        """
        result = ParseResult(file_path=file_path, parser_name=cls.__name__)

        if not os.path.exists(file_path):
            raise FileError(
                ParserErrorCode.FILE_NOT_FOUND,
                f"Image file not found: {file_path}",
                file_path=file_path,
            )

        try:
            _, sprites = cls.parse_unknown_image(file_path, parent_window)
            result = validate_sprites(sprites, file_path)
            result.parser_name = cls.__name__
            return result
        except Exception as e:
            raise FormatError(
                ParserErrorCode.UNKNOWN_ERROR,
                f"Error analyzing image for sprites: {e}",
                file_path=file_path,
                details={"exception_type": type(e).__name__},
            )

    def __init__(
        self,
        directory: str,
        image_filename: str,
        name_callback: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the unknown image parser.

        Args:
            directory: Directory containing the image file.
            image_filename: Name of the image file.
            name_callback: Optional callback invoked for each extracted name.
        """
        super().__init__(directory, image_filename, name_callback)

    def extract_names(self) -> Set[str]:
        """Generate sequential sprite names based on detected regions.

        Returns:
            Set of names like ``sprite_001``, ``sprite_002``, etc.
        """
        try:
            file_path = os.path.join(self.directory, self.filename)
            _, sprites = self.parse_unknown_image(file_path)

            names = set()
            for i, sprite in enumerate(sprites):
                # Generate names like "sprite_001", "sprite_002", etc.
                name = f"sprite_{i + 1:03d}"
                names.add(name)

            return names
        except Exception as e:
            logger.exception("Error extracting names from image %s", self.filename)
            return set()

    @staticmethod
    def parse_unknown_image(
        file_path: str, parent_window=None
    ) -> Tuple[Image.Image, List[Dict[str, Any]]]:
        """Detect sprite regions in an image using alpha transparency.

        If the user has already chosen how to handle this file via
        ``BackgroundHandlerWindow`` (set during the pre-extraction batch
        dialog), that choice is honoured silently — no extra dialog is
        popped from the worker thread.  When no choice is recorded we fall
        back to the legacy single-color confirmation dialog.

        Args:
            file_path: Path to the image file.
            parent_window: Optional parent widget for background-removal dialogs.

        Returns:
            A tuple (processed_image, sprites) where sprites is a list of dicts.
        """
        try:
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = None
            image = Image.open(file_path)

            if image.mode != "RGBA":
                image = image.convert("RGBA")

            user_choice = UnknownParser._lookup_user_choice(file_path)
            processed_image = image

            if user_choice == "exclude_background":
                # Honour the user's pre-recorded "keep background" choice.
                pass
            else:
                # Detect candidate background colors (vectorised).
                bg_colors = UnknownParser._detect_background_colors(image, max_colors=3)
                if bg_colors:
                    if user_choice == "key_background":
                        processed_image = UnknownParser._apply_color_keying_multi(
                            image, bg_colors
                        )
                    elif UnknownParser._should_apply_color_keying(
                        bg_colors[0], parent_window
                    ):
                        processed_image = UnknownParser._apply_color_keying_multi(
                            image, bg_colors
                        )

            sprites = UnknownParser._find_sprites_in_image(processed_image)

            return processed_image, sprites

        except Exception as e:
            logger.exception("Error parsing unknown image %s", file_path)
            from PIL import Image

            return Image.new("RGBA", (1, 1), (0, 0, 0, 0)), []

    @staticmethod
    def _lookup_user_choice(file_path: str) -> Optional[str]:
        """Return the user's pre-recorded background choice for *file_path*.

        Choices are populated by ``BackgroundHandlerWindow`` during the
        pre-extraction batch dialog and stored on the class as
        ``BackgroundHandlerWindow._file_choices`` (a mapping of
        relative-filename → ``"key_background"``/``"exclude_background"``).
        We match by basename or by suffix to handle both relative and
        absolute paths.

        Returns:
            The recorded choice string, or ``None`` if no choice was made.
        """
        try:
            from gui.extractor.background_handler_window import (
                BackgroundHandlerWindow,
            )

            choices = getattr(BackgroundHandlerWindow, "_file_choices", None)
            if not choices:
                return None

            target_name = os.path.basename(file_path)
            if target_name in choices:
                return choices[target_name]

            normalised = file_path.replace("\\", "/")
            for key, value in choices.items():
                key_norm = key.replace("\\", "/")
                if (
                    normalised.endswith(key_norm)
                    or os.path.basename(key) == target_name
                ):
                    return value
        except Exception:
            return None
        return None

    @staticmethod
    def _detect_background_color(image: Image.Image) -> Optional[Tuple[int, int, int]]:
        """Detect the most likely background color.

        Delegates to :meth:`_detect_background_colors` (which samples both
        edges and corner blocks) and returns the highest-confidence colour.

        Args:
            image: The PIL Image to analyze.

        Returns:
            RGB tuple of the background color, or None if not detected.
        """
        colors = UnknownParser._detect_background_colors(image, max_colors=1)
        return colors[0] if colors else None

    @staticmethod
    def _should_apply_color_keying(
        background_color: Tuple[int, int, int], parent_window=None
    ) -> bool:
        """Prompt user to confirm background color removal.

        Args:
            background_color: The detected background RGB tuple.
            parent_window: Optional parent widget for the dialog.

        Returns:
            True if the user confirms removal.
        """
        try:
            if parent_window is None:
                app = QApplication.instance()
                if app:
                    for widget in app.topLevelWidgets():
                        if widget.isMainWindow():
                            parent_window = widget
                            break

            msg_box = QMessageBox(parent_window)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(
                QCoreApplication.translate("UnknownParser", "Background Color Detected")
            )
            msg_box.setText(
                QCoreApplication.translate(
                    "UnknownParser",
                    (
                        "Detected background color: RGB{color}\n\n"
                        "Would you like to remove this background color and make it transparent?"
                    ),
                ).format(color=background_color)
            )
            msg_box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            result = msg_box.exec()
            return result == QMessageBox.StandardButton.Yes
        except Exception:
            return False

    @staticmethod
    def _apply_color_keying(
        image: Image.Image, background_color: Tuple[int, int, int], tolerance: int = 10
    ) -> Image.Image:
        """Make pixels matching the background color transparent.

        Args:
            image: The source RGBA image.
            background_color: RGB tuple of the color to remove.
            tolerance: Maximum per-channel deviation allowed.

        Returns:
            A new image with matching pixels set to alpha 0.
        """
        return UnknownParser._apply_color_keying_multi(
            image, [background_color], tolerance=tolerance
        )

    @staticmethod
    def _apply_color_keying_multi(
        image: Image.Image,
        background_colors: List[Tuple[int, int, int]],
        tolerance: int = 10,
    ) -> Image.Image:
        """Vectorised color-keying for one or more background colors.

        Casting the uint8 channels to int16 *before* the subtraction is
        required — raw uint8 subtraction wraps around (e.g. ``0 - 255 = 1``)
        and would silently match the wrong pixels for high-value targets.

        Args:
            image: The source RGBA image.
            background_colors: List of RGB tuples to remove.
            tolerance: Maximum per-channel deviation allowed.

        Returns:
            A new image with matching pixels set to alpha 0.
        """
        if not background_colors:
            return image

        try:
            img_array = np.array(image)
            if img_array.shape[-1] < 4:
                # Defensive: caller is responsible for RGBA, but bail safely.
                return image

            rgb = img_array[:, :, :3].astype(np.int16)
            combined_mask = np.zeros(rgb.shape[:2], dtype=bool)

            for color in background_colors:
                target = np.array(color, dtype=np.int16)
                diff = np.abs(rgb - target)
                combined_mask |= np.all(diff <= tolerance, axis=2)

            if combined_mask.any():
                img_array[combined_mask, 3] = 0

            try:
                return Image.fromarray(img_array, "RGBA")
            except TypeError:
                h, w = img_array.shape[:2]
                return Image.frombytes(
                    "RGBA", (w, h), np.ascontiguousarray(img_array).tobytes()
                )
        except Exception as e:
            logger.exception("Error applying color keying")
            return image

    @staticmethod
    def _find_sprites_in_image(image: Image.Image) -> List[Dict[str, Any]]:
        """Find connected non-transparent regions in the image.

        Args:
            image: The RGBA image to analyze.

        Returns:
            List of sprite dicts with name, x, y, width, height.
        """
        try:
            img_array = np.array(image)
            alpha_mask = img_array[:, :, 3] > 0

            # Fast path: scipy C-level connected-component labeling (8-connectivity)
            try:
                from scipy.ndimage import label as _label, find_objects as _find_objects

                struct = np.ones((3, 3), dtype=bool)  # 8-connectivity kernel
                labeled, n_features = _label(alpha_mask, structure=struct)
                if n_features == 0:
                    return []
                counts = np.bincount(labeled.ravel())  # counts[0] = background
                sprites = []
                for i, sl in enumerate(_find_objects(labeled), start=1):
                    if counts[i] <= 10:  # filter noise
                        continue
                    y_sl, x_sl = sl
                    sprites.append(
                        {
                            "name": f"sprite_{i:03d}",
                            "x": int(x_sl.start),
                            "y": int(y_sl.start),
                            "width": int(x_sl.stop - x_sl.start),
                            "height": int(y_sl.stop - y_sl.start),
                        }
                    )
                return sprites
            except ImportError:
                pass

            # Fallback: pure-Python flood-fill
            regions = UnknownParser._find_connected_regions(alpha_mask)
            sprites = []
            for i, region in enumerate(regions):
                if len(region) > 10:
                    bbox = UnknownParser._get_bounding_box(region)
                    sprites.append(
                        {
                            "name": f"sprite_{i + 1:03d}",
                            "x": bbox[0],
                            "y": bbox[1],
                            "width": bbox[2] - bbox[0],
                            "height": bbox[3] - bbox[1],
                        }
                    )
            return sprites
        except Exception as e:
            logger.exception("Error finding sprites in image")
            return []

    @staticmethod
    def _find_connected_regions(alpha_mask: np.ndarray) -> List[List[Tuple[int, int]]]:
        """Flood-fill the alpha mask to find connected regions.

        Args:
            alpha_mask: Boolean 2D array where True indicates non-transparent pixels.

        Returns:
            List of regions, each a list of (x, y) coordinate tuples.
        """
        try:
            height, width = alpha_mask.shape
            visited = np.zeros_like(alpha_mask, dtype=bool)
            regions = []

            def flood_fill(start_x, start_y):
                stack = [(start_x, start_y)]
                region = []

                while stack:
                    x, y = stack.pop()
                    if (
                        x < 0
                        or x >= width
                        or y < 0
                        or y >= height
                        or visited[y, x]
                        or not alpha_mask[y, x]
                    ):
                        continue

                    visited[y, x] = True
                    region.append((x, y))

                    for dx in [-1, 0, 1]:
                        for dy in [-1, 0, 1]:
                            if dx != 0 or dy != 0:
                                stack.append((x + dx, y + dy))

                return region

            for y in range(height):
                for x in range(width):
                    if alpha_mask[y, x] and not visited[y, x]:
                        region = flood_fill(x, y)
                        if region:
                            regions.append(region)

            return regions
        except Exception as e:
            logger.exception("Error finding connected regions")
            return []

    @staticmethod
    def _get_bounding_box(
        region_coords: List[Tuple[int, int]],
    ) -> Tuple[int, int, int, int]:
        """Compute the bounding box of a region.

        Args:
            region_coords: List of (x, y) coordinate tuples.

        Returns:
            A tuple (min_x, min_y, max_x + 1, max_y + 1).
        """
        if not region_coords:
            return (0, 0, 0, 0)

        coords = np.array(region_coords)
        return (
            int(coords[:, 0].min()),
            int(coords[:, 1].min()),
            int(coords[:, 0].max()) + 1,
            int(coords[:, 1].max()) + 1,
        )

    @staticmethod
    def _has_transparency(image: Image.Image) -> bool:
        """Check if the image has any transparent pixels.

        Args:
            image: The image to check.

        Returns:
            True if any pixel has alpha < 255.
        """
        try:
            if image.mode != "RGBA":
                return False

            img_array = np.array(image)

            return np.any(img_array[:, :, 3] < 255)
        except Exception as e:
            logger.exception("Error checking transparency")
            return False

    @staticmethod
    def _detect_background_colors(
        image: Image.Image, max_colors: int = 3
    ) -> List[Tuple[int, int, int]]:
        """Detect up to N candidate background colors.

        Samples colour from four sources, weighted by how characteristic of a
        background they are:

        * Strided edge rows/columns (cheap, broad coverage).
        * Solid corner blocks of up to 8×8 pixels, repeated 4× because
          corners are the strongest background indicator on most sprite
          atlases.
        * For images with an alpha channel, only fully-opaque samples are
          considered — already-transparent pixels can’t be “the background”.

        Args:
            image: The image to analyze.
            max_colors: Maximum number of background colors to return.

        Returns:
            List of RGB tuples sorted by frequency.
        """
        try:
            from collections import Counter

            rgba = np.array(image.convert("RGBA"))
            rgb = rgba[:, :, :3]
            alpha = rgba[:, :, 3]
            h, w = rgb.shape[:2]
            if h < 2 or w < 2:
                return []

            x_step = max(1, w // 50)
            y_step = max(1, h // 50)

            # Edge strips (downsampled) — vectorised slicing avoids getpixel().
            edge_rgb = [
                rgb[0, ::x_step, :],
                rgb[h - 1, ::x_step, :],
                rgb[::y_step, 0, :],
                rgb[::y_step, w - 1, :],
            ]
            edge_alpha = [
                alpha[0, ::x_step],
                alpha[h - 1, ::x_step],
                alpha[::y_step, 0],
                alpha[::y_step, w - 1],
            ]

            # Corner blocks — use larger samples so a single off-colour pixel
            # at the very corner doesn’t skew detection.
            block = max(1, min(8, h // 4, w // 4))
            corner_blocks_rgb = [
                rgb[:block, :block, :].reshape(-1, 3),
                rgb[:block, -block:, :].reshape(-1, 3),
                rgb[-block:, :block, :].reshape(-1, 3),
                rgb[-block:, -block:, :].reshape(-1, 3),
            ]
            corner_blocks_alpha = [
                alpha[:block, :block].reshape(-1),
                alpha[:block, -block:].reshape(-1),
                alpha[-block:, :block].reshape(-1),
                alpha[-block:, -block:].reshape(-1),
            ]
            # Repeat corner blocks 4× to outweigh stray edge noise.
            corner_rgb = np.tile(np.concatenate(corner_blocks_rgb), (4, 1))
            corner_alpha = np.tile(np.concatenate(corner_blocks_alpha), 4)

            samples_rgb = np.concatenate(edge_rgb + [corner_rgb])
            samples_alpha = np.concatenate(edge_alpha + [corner_alpha])

            # Drop transparent samples — they can’t be “the background”.
            opaque_mask = samples_alpha >= 250
            if opaque_mask.any():
                samples_rgb = samples_rgb[opaque_mask]
            if samples_rgb.size == 0:
                return []

            color_counts = Counter(map(tuple, samples_rgb.tolist()))

            total = len(samples_rgb)
            min_occurrences = max(1, int(total * 0.05))
            background_colors: List[Tuple[int, int, int]] = []
            for color, count in color_counts.most_common(max_colors * 4):
                if count < min_occurrences:
                    break
                # Skip near-duplicates of colours we already accepted to
                # avoid returning three slightly-different shades of the
                # same JPEG-blocky background.
                if any(
                    all(abs(int(a) - int(b)) <= 8 for a, b in zip(color, existing))
                    for existing in background_colors
                ):
                    continue
                background_colors.append(color)
                if len(background_colors) >= max_colors:
                    break

            return background_colors

        except Exception as e:
            logger.exception("Error detecting background colors")
            return []
