# -*- coding: utf-8 -*-
"""Text parsing helpers for TTS controls (SSML subset + punctuation pauses)."""

from __future__ import annotations

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET


@dataclass
class SynthesisSegment:
    text: str
    speed_multiplier: float = 1.0
    pause_after_ms: int = 0


def _parse_rate_multiplier(value: str | None) -> float:
    if not value:
        return 1.0

    raw = value.strip().lower()
    named = {
        "x-slow": 0.65,
        "slow": 0.8,
        "medium": 1.0,
        "fast": 1.2,
        "x-fast": 1.4,
    }
    if raw in named:
        return named[raw]

    if raw.endswith("%"):
        try:
            return float(raw[:-1]) / 100.0
        except Exception:
            return 1.0

    try:
        return float(raw)
    except Exception:
        return 1.0


def _parse_break_ms(value: str | None) -> int:
    if not value:
        return 0

    raw = value.strip().lower()
    try:
        if raw.endswith("ms"):
            return max(0, int(float(raw[:-2])))
        if raw.endswith("s"):
            return max(0, int(float(raw[:-1]) * 1000.0))
        return max(0, int(float(raw)))
    except Exception:
        return 0


def _pause_for_punctuation(punct: str, comma_ms: int, mid_ms: int, end_ms: int) -> int:
    if punct in {",", "，"}:
        return comma_ms
    if punct in {";", ":", "；", "："}:
        return mid_ms
    if punct in {".", "!", "?", "…", "。", "！", "？"}:
        return end_ms
    return 0


def _sanitize_plain_text_input(text: str) -> str:
    """Conservatively clean markdown/noise from plain-text TTS input.

    Only used for non-SSML input so valid SSML markup is preserved.
    """
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not cleaned.strip():
        return ""

    # Remove line-level markdown markers but keep the actual text content.
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}[-+*]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}>\s?", "", cleaned)

    # Drop fenced-code markers and unwrap common inline markdown emphasis.
    cleaned = re.sub(r"(?m)^\s*`{3,}.*$", " ", cleaned)
    emphasis_patterns = [
        (r"\*\*(.+?)\*\*", r"\1"),
        (r"__(.+?)__", r"\1"),
        (r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1"),
        (r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"\1"),
        (r"`([^`]+)`", r"\1"),
    ]
    for pattern, replacement in emphasis_patterns:
        cleaned = re.sub(pattern, replacement, cleaned)

    # Remove leftover standalone markdown tokens without touching normal words.
    cleaned = re.sub(r"(?<!\w)(?:\*\*|__|~~|`{1,3})(?!\w)", " ", cleaned)
    cleaned = re.sub(r"(?<!\w)[*_~`]+(?!\w)", " ", cleaned)

    # Normalize obvious punctuation spam while preserving sentence meaning.
    cleaned = re.sub(r"\.{3,}", "…", cleaned)
    cleaned = re.sub(r"([!?;,.:])\1+", r"\1", cleaned)
    cleaned = re.sub(r"([。！？；：，])\1+", r"\1", cleaned)

    # Flatten whitespace for more stable segmentation.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,;:.!?…，；：。！？])", r"\1", cleaned)
    return cleaned.strip()


def _split_plain_text_to_segments(
    text: str,
    speed_multiplier: float,
    comma_ms: int,
    mid_ms: int,
    end_ms: int,
) -> list[SynthesisSegment]:
    cleaned = text.strip()
    if not cleaned:
        return []

    pattern = re.compile(r"([^,;:.!?…，；：。！？]+)\s*([,;:.!?…，；：。！？]+)?")
    result: list[SynthesisSegment] = []

    for m in pattern.finditer(cleaned):
        body = (m.group(1) or "").strip()
        punct = (m.group(2) or "").strip()
        if not body and not punct:
            continue

        text_part = (body + (punct[-1] if punct else "")).strip()
        if not text_part:
            continue

        pause_ms = 0
        if punct:
            pause_ms = _pause_for_punctuation(punct[-1], comma_ms, mid_ms, end_ms)

        result.append(
            SynthesisSegment(
                text=text_part,
                speed_multiplier=max(0.2, min(3.0, speed_multiplier)),
                pause_after_ms=max(0, pause_ms),
            )
        )

    if not result:
        result.append(SynthesisSegment(text=cleaned, speed_multiplier=speed_multiplier, pause_after_ms=0))
    return result


def _merge_adjacent(segments: list[SynthesisSegment]) -> list[SynthesisSegment]:
    if not segments:
        return []

    merged: list[SynthesisSegment] = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if (
            prev.pause_after_ms == 0
            and seg.pause_after_ms == 0
            and abs(prev.speed_multiplier - seg.speed_multiplier) < 1e-6
        ):
            prev.text = (prev.text + " " + seg.text).strip()
        else:
            merged.append(seg)
    return merged


def _tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _collect_ssml_segments(
    node: ET.Element,
    current_speed: float,
    comma_ms: int,
    mid_ms: int,
    end_ms: int,
    out: list[SynthesisSegment],
) -> None:
    if node.text and node.text.strip():
        out.extend(
            _split_plain_text_to_segments(
                node.text,
                current_speed,
                comma_ms,
                mid_ms,
                end_ms,
            )
        )

    for child in list(node):
        name = _tag_name(child.tag)

        if name == "break":
            pause_ms = _parse_break_ms(child.attrib.get("time"))
            if pause_ms > 0:
                out.append(SynthesisSegment(text="", speed_multiplier=current_speed, pause_after_ms=pause_ms))
        elif name == "prosody":
            rate_mul = _parse_rate_multiplier(child.attrib.get("rate"))
            _collect_ssml_segments(
                child,
                current_speed * rate_mul,
                comma_ms,
                mid_ms,
                end_ms,
                out,
            )
        elif name == "emphasis":
            level = (child.attrib.get("level") or "moderate").strip().lower()
            emphasis_mul = {
                "strong": 0.92,
                "moderate": 0.96,
                "reduced": 1.05,
            }.get(level, 0.96)
            _collect_ssml_segments(
                child,
                current_speed * emphasis_mul,
                comma_ms,
                mid_ms,
                end_ms,
                out,
            )
        else:
            _collect_ssml_segments(child, current_speed, comma_ms, mid_ms, end_ms, out)

        if child.tail and child.tail.strip():
            out.extend(
                _split_plain_text_to_segments(
                    child.tail,
                    current_speed,
                    comma_ms,
                    mid_ms,
                    end_ms,
                )
            )


def _try_parse_ssml(text: str) -> ET.Element | None:
    raw = text.strip()
    if "<" not in raw or ">" not in raw:
        return None

    # If user provides fragments, wrap with speak.
    xml_src = raw
    if "<speak" not in raw.lower():
        xml_src = f"<speak>{raw}</speak>"

    try:
        root = ET.fromstring(xml_src)
    except ET.ParseError:
        return None

    if _tag_name(root.tag) != "speak":
        return None
    return root


def build_synthesis_segments(
    text: str,
    punctuation_pause_comma_ms: int,
    punctuation_pause_mid_ms: int,
    punctuation_pause_end_ms: int,
) -> list[SynthesisSegment]:
    """Build synthesis segments from plain text or SSML subset.

    Supported SSML tags:
    - <break time="500ms"/>
    - <prosody rate="slow|fast|120%">...</prosody>
    - <emphasis level="strong|moderate|reduced">...</emphasis>
    """
    source = (text or "").strip()
    if not source:
        return []

    root = _try_parse_ssml(source)
    if root is None:
        normalized = _sanitize_plain_text_input(source)
        if not normalized:
            return []
        return _merge_adjacent(
            _split_plain_text_to_segments(
                normalized,
                speed_multiplier=1.0,
                comma_ms=punctuation_pause_comma_ms,
                mid_ms=punctuation_pause_mid_ms,
                end_ms=punctuation_pause_end_ms,
            )
        )

    out: list[SynthesisSegment] = []
    _collect_ssml_segments(
        root,
        current_speed=1.0,
        comma_ms=punctuation_pause_comma_ms,
        mid_ms=punctuation_pause_mid_ms,
        end_ms=punctuation_pause_end_ms,
        out=out,
    )

    # If explicit break-only nodes exist, keep them; merge text segments where possible.
    merged: list[SynthesisSegment] = []
    for seg in out:
        if not seg.text:
            if merged:
                merged[-1].pause_after_ms += seg.pause_after_ms
            else:
                merged.append(seg)
            continue
        if (
            merged
            and merged[-1].text
            and merged[-1].pause_after_ms == 0
            and seg.pause_after_ms == 0
            and abs(merged[-1].speed_multiplier - seg.speed_multiplier) < 1e-6
        ):
            merged[-1].text = (merged[-1].text + " " + seg.text).strip()
        else:
            merged.append(seg)

    # Drop leading empty pause marker.
    while merged and not merged[0].text:
        merged.pop(0)

    return merged
