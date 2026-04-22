#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Parser for Spine ``.atlas`` text files.

Spine's runtime atlas reader is a direct port of libGDX's
``TextureAtlasData`` (see Spine-Runtimes' ``Atlas.cs`` /
``atlas.c`` etc.), so the on-disk format is identical between the two
ecosystems. Rather than maintain two copies of the same parser,
:class:`SpineAtlasParser` is now a thin alias around
:class:`parsers.gdx_parser.GdxAtlasParser` that handles every
documented field (``bounds``/``offsets`` modern layout, the legacy
quadruple, numeric ``rotate`` degrees, ``split``/``pad`` ninepatch
data, page-level metadata, and arbitrary custom int-array fields).

Format reference:
    http://esotericsoftware.com/spine-atlas-format
    https://github.com/EsotericSoftware/spine-runtimes/blob/4.2/spine-csharp/src/Atlas.cs
    https://github.com/libgdx/libgdx/blob/master/gdx/src/com/badlogic/gdx/graphics/g2d/TextureAtlas.java
"""

from __future__ import annotations

from parsers.gdx_parser import GdxAtlasParser


class SpineAtlasParser(GdxAtlasParser):
    """Parser for Spine ``.atlas`` files.

    Identical to :class:`GdxAtlasParser`; subclassed only to keep the
    public class name stable for the registry and for any external
    callers that import :class:`SpineAtlasParser` directly.
    """


__all__ = ["SpineAtlasParser"]
