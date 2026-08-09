#!/usr/bin/env python3
"""Add an empty LCSC property to placed symbols in KiCad schematics."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ListSpan:
    name: str
    start: int
    end: int
    depth: int


@dataclass
class Statistics:
    added: int = 0
    existing: int = 0
    skipped_power: int = 0


def scan_lists(text: str) -> list[ListSpan]:
    """Return S-expression list spans while ignoring parentheses in strings."""
    spans: list[ListSpan] = []
    stack: list[tuple[str, int, int]] = []
    depth = 0
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
        elif char == "(":
            name_start = index + 1
            while name_start < len(text) and text[name_start].isspace():
                name_start += 1
            name_end = name_start
            while name_end < len(text) and not text[name_end].isspace() and text[name_end] not in "()":
                name_end += 1
            stack.append((text[name_start:name_end], index, depth))
            depth += 1
        elif char == ")":
            if not stack:
                raise ValueError(f"Unmatched ')' at byte {index}")
            name, start, list_depth = stack.pop()
            depth -= 1
            spans.append(ListSpan(name=name, start=start, end=index + 1, depth=list_depth))
        index += 1

    if in_string:
        raise ValueError("Unterminated string in schematic")
    if stack:
        raise ValueError("Unclosed S-expression in schematic")
    return spans


def quoted_values(expression: str) -> list[str]:
    values = re.findall(r'"((?:\\.|[^"\\])*)"', expression)
    return [value.replace(r'\"', '"').replace(r"\\", "\\") for value in values]


def symbol_property(name: str, x: str, y: str, indent: str, newline: str) -> str:
    child = indent + "\t"
    grandchild = child + "\t"
    return newline.join(
        [
            f'{indent}(property "{name}" ""',
            f"{child}(at {x} {y} 0)",
            f"{child}(hide yes)",
            f"{child}(show_name no)",
            f"{child}(do_not_autoplace no)",
            f"{child}(effects",
            f"{grandchild}(font",
            f"{grandchild}\t(size 1.27 1.27)",
            f"{grandchild})",
            f"{child})",
            f"{indent})",
        ]
    )


def update_symbol(block: str, newline: str, include_power: bool) -> tuple[str, str]:
    children = [span for span in scan_lists(block) if span.depth == 1]
    properties: dict[str, ListSpan] = {}
    for span in children:
        if span.name != "property":
            continue
        values = quoted_values(block[span.start : span.end])
        if values:
            properties[values[0].casefold()] = span

    if "lcsc" in properties:
        return block, "existing"

    reference_span = properties.get("reference")
    if reference_span is None:
        return block, "ignored"
    reference_values = quoted_values(block[reference_span.start : reference_span.end])
    reference = reference_values[1] if len(reference_values) > 1 else ""
    if reference.startswith("#") and not include_power:
        return block, "power"

    at_span = next((span for span in children if span.name == "at"), None)
    x, y = "0", "0"
    if at_span:
        match = re.match(r"\(at\s+([^\s()]+)\s+([^\s()]+)", block[at_span.start : at_span.end])
        if match:
            x, y = match.groups()

    last_property = max(properties.values(), key=lambda span: span.end)
    line_start = block.rfind(newline, 0, last_property.start) + len(newline)
    indent = block[line_start:last_property.start]
    insertion = symbol_property("LCSC", x, y, indent, newline)
    updated = block[: last_property.end] + newline + insertion + block[last_property.end :]
    return updated, "added"


def update_schematic(text: str, include_power: bool = False) -> tuple[str, Statistics]:
    newline = "\r\n" if "\r\n" in text else "\n"
    # Placed symbols are direct children of the root kicad_sch expression.
    symbols = [span for span in scan_lists(text) if span.name == "symbol" and span.depth == 1]
    stats = Statistics()

    for span in reversed(symbols):
        block = text[span.start : span.end]
        updated, result = update_symbol(block, newline, include_power)
        if result == "added":
            stats.added += 1
            text = text[: span.start] + updated + text[span.end :]
        elif result == "existing":
            stats.existing += 1
        elif result == "power":
            stats.skipped_power += 1

    return text, stats


def write_atomic(path: Path, content: str) -> None:
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add an empty LCSC field to placed symbols in KiCad .kicad_sch files."
    )
    parser.add_argument("schematics", nargs="+", type=Path, help="Schematic file(s) to update")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    parser.add_argument(
        "--include-power-symbols",
        action="store_true",
        help="Also add the field to references such as #PWR and #FLG",
    )
    args = parser.parse_args()

    exit_code = 0
    for path in args.schematics:
        try:
            original = path.read_bytes().decode("utf-8")
            updated, stats = update_schematic(original, args.include_power_symbols)
            if not args.dry_run and updated != original:
                write_atomic(path, updated)
            action = "would add" if args.dry_run else "added"
            print(
                f"{path}: {action} {stats.added}, already present {stats.existing}, "
                f"power/helper symbols skipped {stats.skipped_power}"
            )
        except (OSError, UnicodeError, ValueError) as error:
            print(f"{path}: error: {error}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
