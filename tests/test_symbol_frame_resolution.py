#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for _resolve_instance_frame in the Symbols class.

Verifies that MovieClip (MC) symbols advance continuously from the parent
timeline start while Graphic (G) symbols reset at each keyframe boundary.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module loading (bypass core/__init__.py which triggers wand/ImageMagick)
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))


def _load_module_directly(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-register dependencies so symbols.py can import them
_load_module_directly(
    "core.extractor.spritemap.transform_matrix",
    str(_SRC / "core" / "extractor" / "spritemap" / "transform_matrix.py"),
)
_load_module_directly(
    "core.extractor.spritemap.color_effect",
    str(_SRC / "core" / "extractor" / "spritemap" / "color_effect.py"),
)
_load_module_directly(
    "core.extractor.spritemap.metadata",
    str(_SRC / "core" / "extractor" / "spritemap" / "metadata.py"),
)
_symbols_mod = _load_module_directly(
    "core.extractor.spritemap.symbols",
    str(_SRC / "core" / "extractor" / "spritemap" / "symbols.py"),
)

Symbols = _symbols_mod.Symbols


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_symbol(name: str, frame_count: int) -> dict:
    """Build a minimal symbol dict with *frame_count* frames (1 frame each)."""
    frames = [{"I": i, "DU": 1, "E": []} for i in range(frame_count)]
    return {"SN": name, "TL": {"L": [{"FR": frames}]}}


def _make_symbols(*symbol_specs) -> Symbols:
    """Construct a minimal Symbols instance.

    Each *symbol_spec* is ``(name, frame_count)``.
    """
    animation_json = {
        "AN": {"SN": "root", "TL": {"L": []}},
        "SD": {"S": [_make_symbol(n, c) for n, c in symbol_specs]},
    }
    atlas = MagicMock()
    return Symbols(animation_json, atlas, canvas_size=(100, 100))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCFrozenAtFirstFrame:
    """MovieClip symbols are frozen at firstFrame (non-swfRender convention).

    In game engines (FNF/flxanimate non-swfRender mode), MC symbols don't
    advance independently -- they stay at their firstFrame.  The LP field
    is ignored for MC types.
    """

    @pytest.fixture()
    def symbols(self):
        return _make_symbols(("Body", 5))

    def test_mc_stays_on_frame_zero(self, symbols):
        """MC with no FF always returns frame 0 regardless of parent frame."""
        instance = {"ST": "MC"}
        results = [
            symbols._resolve_instance_frame("Body", instance, frame_start=0, parent_frame_index=i)
            for i in range(15)
        ]
        assert results == [0] * 15

    def test_mc_ignores_loop_mode(self, symbols):
        """MC freezes at firstFrame even when LP=LP (loop) is set."""
        instance = {"ST": "MC", "LP": "LP", "FF": 0}
        kf_starts = [0, 0, 0, 3, 3, 3, 6, 6, 6]
        results = [
            symbols._resolve_instance_frame("Body", instance, frame_start=kf_starts[i], parent_frame_index=i)
            for i in range(9)
        ]
        assert results == [0] * 9

    def test_mc_respects_first_frame(self, symbols):
        """MC with FF=3 always returns frame 3."""
        instance = {"ST": "MC", "LP": "LP", "FF": 3}
        results = [
            symbols._resolve_instance_frame("Body", instance, frame_start=0, parent_frame_index=i)
            for i in range(8)
        ]
        assert results == [3] * 8

    def test_mc_first_frame_clamped_to_length(self, symbols):
        """MC with FF exceeding symbol length is clamped to last frame."""
        instance = {"ST": "MC", "FF": 99}
        result = symbols._resolve_instance_frame("Body", instance, frame_start=0, parent_frame_index=0)
        assert result == 4  # Body has 5 frames, so max index is 4


class TestGraphicKeyframeRelative:
    """Graphic symbols reset their offset at each keyframe boundary."""

    @pytest.fixture()
    def symbols(self):
        return _make_symbols(("Arm", 8))

    def test_graphic_resets_at_keyframe(self, symbols):
        """Graphic offset is relative to parent keyframe start."""
        instance = {"ST": "G", "LP": "LP", "FF": 0}
        # Keyframes at I=0, I=3, I=6
        kf_starts = [0, 0, 0, 3, 3, 3, 6, 6, 6]
        results = [
            symbols._resolve_instance_frame("Arm", instance, frame_start=kf_starts[i], parent_frame_index=i)
            for i in range(9)
        ]
        # G resets at each keyframe boundary: 0,1,2 | 0,1,2 | 0,1,2
        assert results == [0, 1, 2, 0, 1, 2, 0, 1, 2]

    def test_graphic_single_frame_stays_on_first_frame(self, symbols):
        """Graphic SF stays on first_frame regardless of parent frame."""
        instance = {"ST": "G", "LP": "SF", "FF": 3}
        results = [
            symbols._resolve_instance_frame("Arm", instance, frame_start=0, parent_frame_index=i)
            for i in range(5)
        ]
        assert results == [3, 3, 3, 3, 3]

    def test_graphic_play_once_clamps(self, symbols):
        """Graphic PO clamps at end relative to keyframe."""
        instance = {"ST": "G", "LP": "PO", "FF": 0}
        results = [
            symbols._resolve_instance_frame("Arm", instance, frame_start=0, parent_frame_index=i)
            for i in range(12)
        ]
        assert results == [0, 1, 2, 3, 4, 5, 6, 7, 7, 7, 7, 7]

    def test_graphic_loops_relative_to_keyframe(self, symbols):
        """Graphic LP loops starting from keyframe boundary."""
        instance = {"ST": "G", "LP": "LP", "FF": 0}
        results = [
            symbols._resolve_instance_frame("Arm", instance, frame_start=0, parent_frame_index=i)
            for i in range(16)
        ]
        assert results == [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]


class TestDefaultSymbolType:
    """Missing or absent ST defaults to Graphic behaviour."""

    @pytest.fixture()
    def symbols(self):
        return _make_symbols(("Sprite", 4))

    def test_missing_st_defaults_to_graphic(self, symbols):
        """No ST key at all => Graphic (keyframe-relative offset)."""
        instance = {"LP": "LP", "FF": 0}
        kf_starts = [0, 0, 2, 2]
        results = [
            symbols._resolve_instance_frame("Sprite", instance, frame_start=kf_starts[i], parent_frame_index=i)
            for i in range(4)
        ]
        assert results == [0, 1, 0, 1]

    def test_explicit_g_matches_default(self, symbols):
        """Explicit ST=G gives same results as missing ST."""
        instance_default = {"LP": "LP", "FF": 0}
        instance_explicit = {"ST": "G", "LP": "LP", "FF": 0}
        kf_starts = [0, 0, 2, 2]
        for i in range(4):
            default = symbols._resolve_instance_frame("Sprite", instance_default, frame_start=kf_starts[i], parent_frame_index=i)
            explicit = symbols._resolve_instance_frame("Sprite", instance_explicit, frame_start=kf_starts[i], parent_frame_index=i)
            assert default == explicit, f"frame {i}: default={default} != explicit={explicit}"


class TestFirstFrameOffset:
    """first_frame (FF) offsets are respected for both MC and G."""

    @pytest.fixture()
    def symbols(self):
        return _make_symbols(("Anim", 6))

    def test_mc_with_first_frame_offset(self, symbols):
        """MC with FF=2 always returns frame 2 (frozen at firstFrame)."""
        instance = {"ST": "MC", "LP": "LP", "FF": 2}
        results = [
            symbols._resolve_instance_frame("Anim", instance, frame_start=0, parent_frame_index=i)
            for i in range(10)
        ]
        assert results == [2] * 10

    def test_graphic_with_first_frame_offset(self, symbols):
        """Graphic looping with FF=3 starts from frame 3."""
        instance = {"ST": "G", "LP": "LP", "FF": 3}
        results = [
            symbols._resolve_instance_frame("Anim", instance, frame_start=0, parent_frame_index=i)
            for i in range(10)
        ]
        # target = FF + offset = 3+0, 3+1, ..., 3+7 mod 6
        # 3, 4, 5, 0, 1, 2, 3, 4, 5, 0
        assert results == [3, 4, 5, 0, 1, 2, 3, 4, 5, 0]
