#!/usr/bin/env python3
"""RETIRED: the ecommerce image skill now requires 100% AI whole-image generation.

This legacy file is intentionally disabled and must not be used for typesetting,
dimension lines, compositing, validation, or any other production step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_color(value: str) -> str:
    value = value.strip().upper()
    if len(value) == 7 and value.startswith("#"):
        int(value[1:], 16)
        return value
    fail(f"invalid color: {value}")


def word_count(value: str) -> int:
    """Count readable Latin-script words and numbers in short ecommerce copy."""
    return len(re.findall(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*", value))


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def rect_to_rect_distance(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Return the visible gap between rectangles, or zero when they touch/overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def point_to_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - x1, py - y1)
    ratio = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + ratio * dx), py - (y1 + ratio * dy))


def point_to_rect_distance(point: tuple[float, float], rect: tuple[float, float, float, float]) -> float:
    px, py = point
    dx = max(rect[0] - px, 0.0, px - rect[2])
    dy = max(rect[1] - py, 0.0, py - rect[3])
    return math.hypot(dx, dy)


def segment_to_rect_distance(
    start: tuple[float, float], end: tuple[float, float], rect: tuple[float, float, float, float]
) -> float:
    samples = [
        (start[0] + (end[0] - start[0]) * index / 20, start[1] + (end[1] - start[1]) * index / 20)
        for index in range(21)
    ]
    corners = [(rect[0], rect[1]), (rect[2], rect[1]), (rect[0], rect[3]), (rect[2], rect[3])]
    return min(
        [point_to_rect_distance(point, rect) for point in samples]
        + [point_to_segment_distance(point, start, end) for point in corners]
    )


def draw_dimension_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    fill: str,
    width: int,
    arrow_size: float,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    for tip, inward in ((start, 1.0), (end, -1.0)):
        base_x = tip[0] + inward * ux * arrow_size
        base_y = tip[1] + inward * uy * arrow_size
        left = (base_x + px * arrow_size * 0.45, base_y + py * arrow_size * 0.45)
        right = (base_x - px * arrow_size * 0.45, base_y - py * arrow_size * 0.45)
        draw.polygon((tip, left, right), fill=fill)


def resolve_font(lock: dict, role: str, spec_dir: Path) -> Path:
    key = "headline_font" if role == "headline" else "support_font"
    raw = lock.get(key)
    if not raw:
        fail(f"typography_lock.{key} is required")
    font_path = Path(raw)
    if not font_path.is_absolute():
        font_path = (spec_dir / font_path).resolve()
    if not font_path.is_file():
        fail(f"font not found: {font_path}")
    expected_hash = lock.get(f"{key}_sha256")
    if expected_hash and file_hash(font_path).lower() != expected_hash.lower():
        fail(f"font hash changed: {font_path}")
    return font_path


def lock_value(lock: dict, role: str, name: str):
    prefix = "headline" if role == "headline" else "support"
    key = f"{prefix}_{name}"
    if key not in lock:
        fail(f"typography_lock.{key} is required")
    return lock[key]


def validate_metrics(role: str, tracking: float, word_spacing: float, line_gap: float) -> None:
    if role == "headline":
        if not 0.0 <= tracking <= 0.04:
            fail("headline tracking_em must be 0.00 to 0.04; negative or extreme tracking is forbidden")
        if not 0.30 <= word_spacing <= 0.46:
            fail("headline word_spacing_em must be 0.30 to 0.46")
        if not 0.14 <= line_gap <= 0.26:
            fail("headline line_gap_em must be 0.14 to 0.26")
    else:
        if not 0.0 <= tracking <= 0.06:
            fail("support tracking_em must be 0.00 to 0.06")
        if not 0.30 <= word_spacing <= 0.50:
            fail("support word_spacing_em must be 0.30 to 0.50")
        if not 0.16 <= line_gap <= 0.32:
            fail("support line_gap_em must be 0.16 to 0.32")


def line_width(font: ImageFont.FreeTypeFont, text: str, tracking_px: float, word_px: float) -> float:
    width = 0.0
    visible = [index for index, char in enumerate(text) if char != " "]
    last_visible = visible[-1] if visible else -1
    for index, char in enumerate(text):
        if char == " ":
            width += word_px
        else:
            width += font.getlength(char)
            if index != last_visible:
                width += tracking_px
    return width


def draw_line(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    tracking_px: float,
    word_px: float,
) -> None:
    x, y = position
    cap_bbox = font.getbbox("H", anchor="ls")
    baseline_y = y - cap_bbox[1]
    visible = [index for index, char in enumerate(text) if char != " "]
    last_visible = visible[-1] if visible else -1
    for index, char in enumerate(text):
        if char == " ":
            x += word_px
            continue
        draw.text((x, baseline_y), char, font=font, fill=fill, anchor="ls")
        x += font.getlength(char)
        if index != last_visible:
            x += tracking_px


def validate_lock(lock: dict, spec_dir: Path) -> dict:
    headline_font = resolve_font(lock, "headline", spec_dir)
    support_font = resolve_font(lock, "support", spec_dir)
    headline_color = normalize_color(lock_value(lock, "headline", "color"))
    subtitle_color = normalize_color(lock.get("subtitle_color", ""))
    support_color = normalize_color(lock_value(lock, "support", "color"))
    if headline_color != subtitle_color:
        fail("headline and subtitle colors must be identical")
    for role in ("headline", "support"):
        validate_metrics(
            role,
            float(lock_value(lock, role, "tracking_em")),
            float(lock_value(lock, role, "word_spacing_em")),
            float(lock_value(lock, role, "line_gap_em")),
        )
    normalized = dict(lock)
    normalized["headline_font"] = str(headline_font)
    normalized["support_font"] = str(support_font)
    normalized["headline_font_sha256"] = file_hash(headline_font)
    normalized["support_font_sha256"] = file_hash(support_font)
    normalized["headline_color"] = headline_color
    normalized["subtitle_color"] = subtitle_color
    normalized["support_color"] = support_color
    return normalized


def render(base_path: Path, spec_path: Path, output_path: Path | None, check_only: bool) -> None:
    spec = load_json(spec_path)
    canvas = tuple(spec.get("canvas", [1024, 1024]))
    if len(canvas) != 2:
        fail("canvas must be [width, height]")
    layout_role = spec.get("layout_role", "marketing")
    if layout_role not in {"marketing_hero", "marketing", "platform_clean"}:
        fail("layout_role must be marketing_hero, marketing, or platform_clean")
    blocks = spec.get("blocks", [])
    if layout_role == "platform_clean" and blocks:
        fail("platform_clean layouts may not contain text blocks")
    subtitle_count = sum(1 for block in blocks if block.get("role") == "subtitle")
    headline_count = sum(1 for block in blocks if block.get("role") == "headline")
    detail_count = sum(1 for block in blocks if block.get("role") == "detail")
    if layout_role == "marketing_hero" and headline_count != 1:
        fail("marketing_hero must contain exactly one headline block")
    if layout_role == "marketing_hero" and subtitle_count > 1:
        fail("marketing_hero may contain at most one subtitle block")
    if layout_role != "marketing_hero" and subtitle_count:
        fail("subtitle blocks are reserved for marketing_hero; use detail or label on later images")
    if layout_role == "marketing_hero" and detail_count:
        fail("marketing_hero may not contain detail blocks")
    if detail_count > 3:
        fail("a marketing image may contain at most three detail blocks")
    short_edge = float(min(canvas))
    lock = validate_lock(spec.get("typography_lock", {}), spec_path.parent)
    forbidden = []
    for region in spec.get("forbidden_regions", []):
        box = tuple(float(value) for value in region["box"])
        if len(box) != 4:
            fail("forbidden region box must have four values")
        forbidden.append((region.get("name", "unnamed"), box))

    image = Image.open(base_path).convert("RGB")
    if image.size != canvas:
        fail(f"base image size {image.size} does not match canvas {canvas}")
    draw = ImageDraw.Draw(image)
    headline_color = lock["headline_color"]
    rendered_blocks: dict[str, dict] = {}
    rendered_sequence: list[dict] = []

    for index, block in enumerate(blocks, start=1):
        role = block.get("role")
        if role not in {"headline", "subtitle", "detail", "label"}:
            fail(f"block {index}: role must be headline, subtitle, detail, or label")
        metric_role = "headline" if role == "headline" else "support"
        lines = block.get("lines")
        if not isinstance(lines, list) or not lines or any(not isinstance(line, str) or not line for line in lines):
            fail(f"block {index}: lines must be a non-empty list of strings")
        if role == "headline" and len(lines) > 2:
            fail(f"block {index}: headline may not exceed two lines")
        if role == "subtitle" and len(lines) > 1:
            fail(f"block {index}: subtitle must be a single concise line")
        if role == "detail" and len(lines) > 2:
            fail(f"block {index}: detail may not exceed two lines")
        if role == "detail":
            detail_words = word_count(" ".join(lines))
            if not 4 <= detail_words <= 12:
                fail(
                    f"block {index}: detail must contain 4 to 12 readable words so it explains "
                    f"evidence instead of acting as a bare part label; found {detail_words}"
                )
        case = lock.get(f"{role}_case", "upper" if role == "headline" else "mixed")
        if case == "upper" and any(line != line.upper() for line in lines):
            fail(f"block {index}: text violates locked uppercase style")

        font_path = Path(lock[f"{metric_role}_font"])
        font_size = int(block["font_size"])
        if font_size <= 0:
            fail(f"block {index}: font_size must be positive")
        if role == "headline":
            minimum_size = 136 if layout_role == "marketing_hero" and len(lines) == 1 else 108 if layout_role == "marketing_hero" else 96
        elif role == "subtitle":
            minimum_size = 48
        elif role == "detail":
            minimum_size = 38
        else:
            minimum_size = 32
        if font_size < minimum_size:
            fail(
                f"block {index}: {role} font_size {font_size}px is below the {minimum_size}px "
                f"mobile baseline for {layout_role}"
            )
        font = ImageFont.truetype(str(font_path), font_size)
        tracking_em = float(lock[f"{metric_role}_tracking_em"])
        word_spacing_em = float(lock[f"{metric_role}_word_spacing_em"])
        line_gap_em = float(lock[f"{metric_role}_line_gap_em"])
        tracking_px = tracking_em * font_size
        word_px = word_spacing_em * font_size
        line_gap_px = line_gap_em * font_size
        default_color = lock["headline_color"] if role == "headline" else lock["subtitle_color"] if role == "subtitle" else lock["support_color"]
        color = normalize_color(block.get("color", default_color))
        if role == "subtitle" and color != headline_color:
            fail(f"block {index}: subtitle color must exactly match headline color")

        box = tuple(float(value) for value in block["box"])
        if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
            fail(f"block {index}: invalid box")
        minimum_padding = 40.0 if role in {"headline", "subtitle"} else 28.0
        padding = float(block.get("padding", minimum_padding))
        if padding < minimum_padding:
            fail(f"block {index}: {role} padding must be at least {minimum_padding:.0f}px")
        minimum_edge_margin = short_edge * (0.08 if role in {"headline", "subtitle"} else 0.055)
        edge_margin = float(block.get("edge_margin", minimum_edge_margin))
        if edge_margin < minimum_edge_margin:
            fail(
                f"block {index}: {role} edge_margin must be at least "
                f"{minimum_edge_margin:.1f}px"
            )
        inner = (box[0] + padding, box[1] + padding, box[2] - padding, box[3] - padding)
        if inner[2] <= inner[0] or inner[3] <= inner[1]:
            fail(f"block {index}: padding consumes the text box")

        cap_box = font.getbbox("H")
        cap_height = float(cap_box[3] - cap_box[1])
        if role == "headline" and layout_role == "marketing_hero":
            minimum_cap_ratio = 0.095 if len(lines) == 1 else 0.078
            if cap_height / short_edge < minimum_cap_ratio:
                fail(
                    f"block {index}: visible headline cap height is too small for marketing_hero; "
                    f"minimum is {minimum_cap_ratio:.1%} of canvas"
                )
        elif role == "headline" and cap_height / short_edge < 0.065:
            fail(f"block {index}: visible headline cap height must be at least 6.5% of canvas")
        elif role == "subtitle" and cap_height / short_edge < 0.034:
            fail(f"block {index}: visible subtitle cap height must be at least 3.4% of canvas")
        elif role == "detail" and cap_height / short_edge < 0.025:
            fail(f"block {index}: visible detail cap height must be at least 2.5% of canvas")
        elif role == "label" and cap_height / short_edge < 0.021:
            fail(f"block {index}: visible label cap height must be at least 2.1% of canvas")
        widths = [line_width(font, line, tracking_px, word_px) for line in lines]
        available_width = inner[2] - inner[0]
        if any(width > available_width for width in widths):
            fail(
                f"block {index}: headline needs {max(widths):.1f}px but T region has "
                f"{available_width:.1f}px; shorten copy or enlarge T region"
            )
        if role == "headline":
            width_fill = max(widths) / available_width
            minimum_fill = float(block.get("min_width_fill", 0.62))
            maximum_fill = float(block.get("max_width_fill", 0.86))
            if not minimum_fill <= width_fill <= maximum_fill:
                fail(
                    f"block {index}: headline width fill is {width_fill:.1%}; "
                    f"required range is {minimum_fill:.0%}-{maximum_fill:.0%}"
                )
        total_height = cap_height * len(lines) + line_gap_px * (len(lines) - 1)
        if role == "headline" and layout_role == "marketing_hero" and len(lines) == 2 and total_height / short_edge < 0.18:
            fail(f"block {index}: two-line marketing hero must occupy at least 18% visible canvas height")
        if total_height > inner[3] - inner[1]:
            fail(f"block {index}: lines are vertically crowded")

        align = block.get("align", "left")
        if align not in {"left", "center", "right"}:
            fail(f"block {index}: invalid alignment")
        line_boxes = []
        y = inner[1]
        for line, width in zip(lines, widths):
            if align == "left":
                x = inner[0]
            elif align == "center":
                x = inner[0] + ((inner[2] - inner[0]) - width) / 2
            else:
                x = inner[2] - width
            actual = (x, y, x + width, y + cap_height)
            safe_actual = (
                actual[0] - padding,
                actual[1] - padding,
                actual[2] + padding,
                actual[3] + padding,
            )
            if (
                safe_actual[0] < edge_margin
                or safe_actual[1] < edge_margin
                or safe_actual[2] > canvas[0] - edge_margin
                or safe_actual[3] > canvas[1] - edge_margin
            ):
                fail(
                    f"block {index}: text plus padding enters the canvas edge safety zone; "
                    f"keep at least {edge_margin:.1f}px clear"
                )
            for name, region in forbidden:
                if intersects(safe_actual, region):
                    fail(f"block {index}: text plus padding intersects forbidden region {name}")
            line_boxes.append(actual)
            if not check_only:
                draw_line(draw, (x, y), line, font, color, tracking_px, word_px)
            y += cap_height + line_gap_px

        rendered = {
            "role": role,
            "align": align,
            "box": (
                min(item[0] for item in line_boxes),
                min(item[1] for item in line_boxes),
                max(item[2] for item in line_boxes),
                max(item[3] for item in line_boxes),
            ),
        }
        minimum_block_gap = short_edge * 0.018
        requested_block_gap = float(block.get("min_block_gap", minimum_block_gap))
        if requested_block_gap < minimum_block_gap or requested_block_gap > short_edge * 0.08:
            fail(
                f"block {index}: min_block_gap must be {minimum_block_gap:.1f}-"
                f"{short_edge * 0.08:.1f}px"
            )
        for previous_index, previous in enumerate(rendered_sequence, start=1):
            visible_distance = rect_to_rect_distance(rendered["box"], previous["box"])
            required_distance = max(requested_block_gap, previous["min_block_gap"])
            if visible_distance < required_distance:
                fail(
                    f"block {index}: visible text is only {visible_distance:.1f}px from block "
                    f"{previous_index}; minimum is {required_distance:.1f}px"
                )
        rendered["min_block_gap"] = requested_block_gap
        rendered_sequence.append(rendered)
        block_id = block.get("id")
        if block_id:
            if block_id in rendered_blocks:
                fail(f"block {index}: duplicate id {block_id}")
            rendered_blocks[block_id] = rendered

    if layout_role == "marketing_hero" and subtitle_count:
        headline = next(item for item in rendered_sequence if item["role"] == "headline")
        subtitle = next(item for item in rendered_sequence if item["role"] == "subtitle")
        if headline["align"] != subtitle["align"]:
            fail("marketing_hero headline and subtitle must share one alignment axis")
        visible_gap = subtitle["box"][1] - headline["box"][3]
        minimum_gap = short_edge * 0.02
        maximum_gap = short_edge * 0.055
        if not minimum_gap <= visible_gap <= maximum_gap:
            fail(
                "marketing_hero subtitle must form one compact copy group with the headline; "
                f"visible glyph gap is {visible_gap:.1f}px, required {minimum_gap:.1f}-{maximum_gap:.1f}px"
            )
        alignment_tolerance = short_edge * 0.024
        if headline["align"] == "left":
            anchor_delta = abs(headline["box"][0] - subtitle["box"][0])
        elif headline["align"] == "right":
            anchor_delta = abs(headline["box"][2] - subtitle["box"][2])
        else:
            headline_center = (headline["box"][0] + headline["box"][2]) / 2
            subtitle_center = (subtitle["box"][0] + subtitle["box"][2]) / 2
            anchor_delta = abs(headline_center - subtitle_center)
        if anchor_delta > alignment_tolerance:
            fail(
                "marketing_hero headline and subtitle do not share a stable visual anchor; "
                f"anchor delta is {anchor_delta:.1f}px, maximum {alignment_tolerance:.1f}px"
            )

    for index, line in enumerate(spec.get("dimension_lines", []), start=1):
        start = tuple(float(value) for value in line.get("start", []))
        end = tuple(float(value) for value in line.get("end", []))
        if len(start) != 2 or len(end) != 2:
            fail(f"dimension line {index}: start and end must have two values")
        if start == end:
            fail(f"dimension line {index}: start and end may not match")
        if any(value < 0 for value in (*start, *end)) or start[0] > canvas[0] or end[0] > canvas[0] or start[1] > canvas[1] or end[1] > canvas[1]:
            fail(f"dimension line {index}: line leaves the canvas")
        label_id = line.get("label_id")
        if not label_id or label_id not in rendered_blocks:
            fail(f"dimension line {index}: label_id must reference a rendered block id")
        if rendered_blocks[label_id]["role"] != "label":
            fail(f"dimension line {index}: label_id must reference a label block")
        max_gap = float(line.get("max_label_gap", 48))
        if not 8 <= max_gap <= 96:
            fail(f"dimension line {index}: max_label_gap must be 8 to 96 px")
        actual_gap = segment_to_rect_distance(start, end, rendered_blocks[label_id]["box"])
        if actual_gap > max_gap:
            fail(
                f"dimension line {index}: label {label_id} is {actual_gap:.1f}px from its line; "
                f"maximum is {max_gap:.1f}px"
            )
        line_width_px = int(line.get("width", 3))
        arrow_size = float(line.get("arrow_size", 12))
        if not 1 <= line_width_px <= 8 or not 4 <= arrow_size <= 24:
            fail(f"dimension line {index}: invalid width or arrow_size")
        if not check_only:
            draw_dimension_line(
                draw,
                start,
                end,
                normalize_color(line.get("color", lock["support_color"])),
                line_width_px,
                arrow_size,
            )

    if not check_only:
        if output_path is None:
            fail("--output is required unless --check-only is used")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG", optimize=True)
    fingerprint = hashlib.sha256(json.dumps(lock, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    print(
        f"typography-lock={fingerprint} blocks={len(spec.get('blocks', []))} "
        f"dimension-lines={len(spec.get('dimension_lines', []))} status=ok"
    )


def validate_set(paths: list[Path]) -> None:
    if len(paths) < 2:
        fail("--validate-set requires at least two spec files")
    locks = []
    for path in paths:
        spec = load_json(path)
        locks.append(validate_lock(spec.get("typography_lock", {}), path.parent))
    baseline = json.dumps(locks[0], sort_keys=True)
    for path, lock in zip(paths[1:], locks[1:]):
        if json.dumps(lock, sort_keys=True) != baseline:
            fail(f"typography lock differs: {path}")
    print(f"typography-set specs={len(paths)} status=ok")


def validate_suite(manifest_path: Path) -> None:
    """Validate suite-level persuasion coverage and the evidence-to-copy ledger."""
    manifest = load_json(manifest_path)
    images = manifest.get("images")
    if not isinstance(images, list) or not 7 <= len(images) <= 9:
        fail("suite manifest must contain 7 to 9 images")
    image_ids = [item.get("id") for item in images]
    if any(not value for value in image_ids) or len(set(image_ids)) != len(image_ids):
        fail("suite manifest image ids must be present and unique")

    selling_points = manifest.get("selling_points")
    if not isinstance(selling_points, list) or not 4 <= len(selling_points) <= 6:
        fail("suite manifest must declare 4 to 6 distinct confirmed selling points")
    point_ids = [item.get("id") for item in selling_points]
    if any(not value for value in point_ids) or len(set(point_ids)) != len(point_ids):
        fail("selling point ids must be present and unique")
    allowed_status = {"confirmed", "simulated_confirmed"}
    for point in selling_points:
        if point.get("status") not in allowed_status:
            fail(f"selling point {point.get('id')}: status must be confirmed or simulated_confirmed")
        if not point.get("claim") or not point.get("evidence"):
            fail(f"selling point {point.get('id')}: claim and evidence are required")

    hero_count = sum(1 for item in images if item.get("layout_role") == "marketing_hero")
    if hero_count != 1:
        fail("suite manifest must contain exactly one marketing_hero")
    later = [item for item in images if item.get("layout_role") not in {"platform_clean", "marketing_hero"}]
    evidence_rich = []
    visual_led = []
    headline_only = []
    used_points: set[str] = set()
    doubt_resolvers = 0

    for item in images:
        if not item.get("main_task") or not item.get("visual_evidence"):
            fail(f"image {item.get('id')}: main_task and visual_evidence are required")
        linked = item.get("selling_point_ids", [])
        if not isinstance(linked, list) or any(point not in point_ids for point in linked):
            fail(f"image {item.get('id')}: selling_point_ids contains an unknown id")
        used_points.update(linked)
        if item.get("decision_role") in {"dimension", "compatibility", "steps", "package"}:
            doubt_resolvers += 1
        if item not in later:
            continue
        mode = item.get("text_mode")
        explanations = item.get("explanation_blocks", [])
        if mode == "visual_only":
            if explanations:
                fail(f"image {item.get('id')}: visual_only may not contain explanation_blocks")
            visual_led.append(item)
            continue
        if mode == "headline_only":
            if explanations:
                fail(f"image {item.get('id')}: headline_only may not contain explanation_blocks")
            headline_only.append(item)
            continue
        if mode not in {"headline_detail", "detail_only", "headline_label"}:
            fail(f"image {item.get('id')}: invalid text_mode")
        if mode in {"headline_detail", "detail_only"}:
            if not isinstance(explanations, list) or not 1 <= len(explanations) <= 3:
                fail(f"image {item.get('id')}: evidence-rich image needs 1 to 3 explanation_blocks")
            for block in explanations:
                copy = block.get("copy", "")
                count = word_count(copy)
                if not 4 <= count <= 12:
                    fail(f"image {item.get('id')}: explanation copy must contain 4 to 12 words")
                for field in ("feature", "evidence", "user_relevance"):
                    if not block.get(field):
                        fail(f"image {item.get('id')}: explanation block requires {field}")
            evidence_rich.append(item)

    if used_points != set(point_ids):
        missing = sorted(set(point_ids) - used_points)
        fail(f"suite manifest does not use every declared selling point: {missing}")
    if not 3 <= len(evidence_rich) <= 5:
        fail("suite must contain 3 to 5 evidence-rich later images")
    if len(visual_led) < 2:
        fail("suite must preserve at least two visual-led later images")
    if len(headline_only) > 1:
        fail("suite may contain at most one later headline-only image")
    if doubt_resolvers < 1:
        fail("suite needs at least one dimension, compatibility, steps, or package decision image")
    print(
        f"suite-images={len(images)} selling-points={len(selling_points)} "
        f"evidence-rich={len(evidence_rich)} visual-led={len(visual_led)} status=ok"
    )


def main() -> int:
    print(
        "ERROR: retired workflow; use the image model to generate or edit the complete image",
        file=sys.stderr,
    )
    return 2

    # Legacy implementation retained only because this workspace does not permit deletion.
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--validate-set", type=Path, nargs="+")
    parser.add_argument("--validate-suite", type=Path)
    args = parser.parse_args()
    try:
        if args.validate_suite:
            validate_suite(args.validate_suite)
        elif args.validate_set:
            validate_set(args.validate_set)
        else:
            if not args.base or not args.spec:
                fail("--base and --spec are required")
            render(args.base, args.spec, args.output, args.check_only)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
