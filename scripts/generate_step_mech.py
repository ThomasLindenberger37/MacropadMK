#!/usr/bin/env python3
"""
Generate a STEP board model from Edge.Cuts Gerber + Excellon drill,
keeping only mechanical holes.

Mechanical hole selection:
- Default: drill tools tagged as NPTH / NonPlated in Excellon attributes.
- Optional override: --mechanical-tools T1,T3,...

Dependencies:
- cadquery (for STEP export)
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class Segment:
    kind: str  # "line" or "arc"
    start: Point
    end: Point
    center: Optional[Point] = None
    cw: Optional[bool] = None


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _read_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def parse_gerber_outline(edge_gerber: Path, tol: float = 1e-5) -> List[Point]:
    lines = _read_lines(edge_gerber)
    unit_scale = 1.0  # mm
    fmt_decimals = 6
    abs_mode = True

    fs_re = re.compile(r"%FSL.AX(\d)(\d)Y(\d)(\d)\*%")
    line_cmd_re = re.compile(
        r"^(?:X(?P<x>-?\d+))?(?:Y(?P<y>-?\d+))?(?:I(?P<i>-?\d+))?(?:J(?P<j>-?\d+))?(?:D(?P<d>\d+))?\*?$"
    )

    cur: Point = (0.0, 0.0)
    cur_mode = "G01"
    segments: List[Segment] = []

    def parse_coord(raw: Optional[str]) -> Optional[float]:
        if raw is None:
            return None
        return float(raw) / (10**fmt_decimals) * unit_scale

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("%FS"):
            m = fs_re.match(line)
            if m:
                # We only need decimals for scaling here.
                fmt_decimals = int(m.group(2))
            continue

        if line.startswith("%MOIN"):
            unit_scale = 25.4
            continue
        if line.startswith("%MOMM"):
            unit_scale = 1.0
            continue

        if line.startswith("G90"):
            abs_mode = True
            continue
        if line.startswith("G91"):
            raise ValueError("Incremental Gerber coordinates (G91) are not supported")

        if line.startswith("G01"):
            cur_mode = "G01"
            continue
        if line.startswith("G02"):
            cur_mode = "G02"
            continue
        if line.startswith("G03"):
            cur_mode = "G03"
            continue

        if line.startswith(("G04", "%", "M02", "M30", "D10", "D11", "D12")):
            continue

        m = line_cmd_re.match(line)
        if not m:
            continue

        x = parse_coord(m.group("x"))
        y = parse_coord(m.group("y"))
        i = parse_coord(m.group("i"))
        j = parse_coord(m.group("j"))
        d = m.group("d")

        next_x = cur[0] if x is None else x
        next_y = cur[1] if y is None else y
        nxt = (next_x, next_y)

        if not abs_mode:
            nxt = (cur[0] + (x or 0.0), cur[1] + (y or 0.0))

        if d == "02":
            cur = nxt
            continue

        if d == "01":
            if cur_mode == "G01":
                segments.append(Segment(kind="line", start=cur, end=nxt))
            elif cur_mode in ("G02", "G03"):
                if i is None or j is None:
                    raise ValueError("Arc command missing I/J center offset")
                center = (cur[0] + i, cur[1] + j)
                segments.append(
                    Segment(kind="arc", start=cur, end=nxt, center=center, cw=(cur_mode == "G02"))
                )
            cur = nxt

    if not segments:
        raise ValueError(f"No drawable profile segments found in {edge_gerber}")

    loops = stitch_loops(segments, tol=tol)
    if not loops:
        raise ValueError("Failed to stitch outline loops from Edge.Cuts")

    # Use largest-area loop as board outer profile.
    sampled_loops = [sample_loop(loop) for loop in loops]
    sampled_loops = [normalize_closed_points(pts, tol=tol) for pts in sampled_loops if len(pts) >= 3]
    if not sampled_loops:
        raise ValueError("No closed loop sampled from Edge.Cuts")

    outer = max(sampled_loops, key=lambda pts: abs(polygon_area(pts)))
    return outer


def stitch_loops(segments: Sequence[Segment], tol: float = 1e-5) -> List[List[Segment]]:
    remaining = list(segments)
    loops: List[List[Segment]] = []

    while remaining:
        loop: List[Segment] = [remaining.pop(0)]
        start = loop[0].start
        end = loop[0].end

        progressed = True
        while progressed and _distance(end, start) > tol:
            progressed = False
            for idx, seg in enumerate(remaining):
                if _distance(seg.start, end) <= tol:
                    loop.append(seg)
                    end = seg.end
                    remaining.pop(idx)
                    progressed = True
                    break
                if _distance(seg.end, end) <= tol:
                    rev = reverse_segment(seg)
                    loop.append(rev)
                    end = rev.end
                    remaining.pop(idx)
                    progressed = True
                    break

        if _distance(end, start) <= tol:
            loops.append(loop)

    return loops


def reverse_segment(seg: Segment) -> Segment:
    if seg.kind == "line":
        return Segment(kind="line", start=seg.end, end=seg.start)
    return Segment(kind="arc", start=seg.end, end=seg.start, center=seg.center, cw=not bool(seg.cw))


def sample_loop(loop: Sequence[Segment], arc_step_deg: float = 8.0) -> List[Point]:
    points: List[Point] = []
    for seg in loop:
        if seg.kind == "line":
            if not points:
                points.append(seg.start)
            points.append(seg.end)
            continue

        if seg.center is None or seg.cw is None:
            continue

        cx, cy = seg.center
        sx, sy = seg.start
        ex, ey = seg.end
        r = math.hypot(sx - cx, sy - cy)
        a0 = math.atan2(sy - cy, sx - cx)
        a1 = math.atan2(ey - cy, ex - cx)

        if seg.cw:
            if a1 >= a0:
                a1 -= 2 * math.pi
            sweep = a1 - a0
        else:
            if a1 <= a0:
                a1 += 2 * math.pi
            sweep = a1 - a0

        n_steps = max(2, int(abs(math.degrees(sweep)) / arc_step_deg))

        if not points:
            points.append(seg.start)
        for i in range(1, n_steps + 1):
            a = a0 + sweep * (i / n_steps)
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    return points


def normalize_closed_points(points: Sequence[Point], tol: float = 1e-5) -> List[Point]:
    if not points:
        return []
    out = [points[0]]
    for p in points[1:]:
        if _distance(out[-1], p) > tol:
            out.append(p)
    if len(out) > 2 and _distance(out[0], out[-1]) <= tol:
        out.pop()
    return out


def polygon_area(points: Sequence[Point]) -> float:
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += (x1 * y2) - (x2 * y1)
    return 0.5 * area


@dataclass
class DrillTool:
    diameter_mm: float
    aper_function: str


def parse_excellon_mech_holes(
    drill_file: Path,
    mech_tools_override: Optional[Iterable[str]] = None,
) -> List[Tuple[float, float, float]]:
    """
    Returns list of (x_mm, y_mm, diameter_mm) for mechanical holes.
    """
    lines = _read_lines(drill_file)
    tool_re = re.compile(r"^T(\d+)C([0-9.]+)")
    xy_re = re.compile(r"^X(-?[0-9.]+)Y(-?[0-9.]+)")
    ta_re = re.compile(r"^;\s*#@!\s*TA\.AperFunction,(.+)$")

    tool_meta: Dict[str, DrillTool] = {}
    pending_aper_function = ""
    cur_tool: Optional[str] = None

    override_set = {t.strip().upper() for t in mech_tools_override or [] if t.strip()}

    for line in lines:
        s = line.strip()
        if not s:
            continue

        ta_m = ta_re.match(s)
        if ta_m:
            pending_aper_function = ta_m.group(1).strip()
            continue

        tm = tool_re.match(s)
        if tm:
            tnum = f"T{int(tm.group(1))}"
            tool_meta[tnum] = DrillTool(diameter_mm=float(tm.group(2)), aper_function=pending_aper_function)
            continue

        if s.startswith("T") and s[1:].isdigit():
            cur_tool = f"T{int(s[1:])}"
            continue

    holes: List[Tuple[float, float, float]] = []
    cur_tool = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("T") and s[1:].isdigit():
            cur_tool = f"T{int(s[1:])}"
            continue
        m = xy_re.match(s)
        if not m or cur_tool is None:
            continue

        if cur_tool not in tool_meta:
            continue
        meta = tool_meta[cur_tool]

        is_mechanical = False
        if override_set:
            is_mechanical = cur_tool.upper() in override_set
        else:
            af = meta.aper_function.upper()
            if "NPTH" in af or "NONPLATED" in af or "NON_PLATED" in af:
                is_mechanical = True

        if not is_mechanical:
            continue

        x = float(m.group(1))
        y = float(m.group(2))
        holes.append((x, y, meta.diameter_mm))

    return holes


def build_step(
    outline_points: Sequence[Point],
    mech_holes: Sequence[Tuple[float, float, float]],
    thickness_mm: float,
    out_step: Path,
) -> None:
    try:
        import cadquery as cq
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency 'cadquery'. Use a virtualenv, e.g.: "
            "python3 -m venv scripts/.venv && scripts/.venv/bin/pip install cadquery"
        ) from exc

    if len(outline_points) < 3:
        raise ValueError("Outline needs at least 3 points")

    solid = cq.Workplane("XY").polyline(list(outline_points)).close().extrude(thickness_mm)

    if mech_holes:
        # Cut cylinders through entire thickness.
        z0 = -0.1
        z1 = thickness_mm + 0.1
        for x, y, dia in mech_holes:
            r = dia / 2.0
            cutter = cq.Workplane("XY").center(x, y).circle(r).extrude(z1 - z0)
            cutter = cutter.translate((0.0, 0.0, z0))
            solid = solid.cut(cutter)

    cq.exporters.export(solid, str(out_step))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate STEP from Edge_Cuts Gerber + Excellon drill (mechanical holes only)"
    )
    p.add_argument("--edge-gerber", required=True, type=Path, help="Path to Edge_Cuts Gerber file")
    p.add_argument("--drill", required=True, type=Path, help="Path to Excellon drill file (.drl)")
    p.add_argument("--out", required=True, type=Path, help="Output STEP file path")
    p.add_argument("--thickness", type=float, default=1.6, help="Board thickness in mm (default: 1.6)")
    p.add_argument(
        "--mechanical-tools",
        default="",
        help="Optional comma-separated tool list to force as mechanical, e.g. T3,T4",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    try:
        outline = parse_gerber_outline(args.edge_gerber)
        tool_override = [x.strip() for x in args.mechanical_tools.split(",") if x.strip()]
        holes = parse_excellon_mech_holes(args.drill, mech_tools_override=tool_override)
        build_step(outline, holes, args.thickness, args.out)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote STEP: {args.out}")
    print(f"Mechanical holes cut: {len(holes)}")
    if not holes and not args.mechanical_tools.strip():
        print("Hint: No NPTH tools detected. Try --mechanical-tools Tn,...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
