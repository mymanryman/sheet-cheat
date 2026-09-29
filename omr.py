"""Turn Audiveris' MusicXML output into note positions on the page.

Audiveris exports the layout of the scanned page (page size, margins, system
and staff distances, measure widths and each note's default-x) in MusicXML
"tenths" (one staff space = 10 tenths). We replay that layout to find where
every note head sits, as a fraction of the page width and height, so the
browser can draw the note name next to it on top of the original PDF page.
"""
from __future__ import annotations

import posixpath
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

STEPS = "CDEFGAB"
STAFF_HEIGHT = 40.0  # 5 lines, 4 spaces of 10 tenths each
DEFAULT_STAFF_DISTANCE = 60.0
DEFAULT_SYSTEM_DISTANCE = 100.0
HEAD_WIDTH = 12.0  # a black note head is about 1.2 staff spaces wide


def load_musicxml(path: Path) -> ET.Element:
    """Return the <score-partwise> root of a .mxl or plain MusicXML file."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = None
            if "META-INF/container.xml" in z.namelist():
                container = ET.fromstring(z.read("META-INF/container.xml"))
                for el in container.iter():
                    if el.tag.endswith("rootfile") and el.get("full-path"):
                        name = el.get("full-path")
                        break
            if name is None:
                candidates = [n for n in z.namelist()
                              if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF")]
                if not candidates:
                    raise ValueError(f"No MusicXML inside {path.name}")
                name = candidates[0]
            data = z.read(posixpath.normpath(name))
    else:
        data = path.read_bytes()
    root = ET.fromstring(data)
    if root.tag == "score-timewise":
        raise ValueError("Timewise MusicXML is not supported")
    return root


def _num(el: ET.Element | None, path: str, default: float | None = None) -> float | None:
    if el is None:
        return default
    found = el.find(path)
    if found is None or found.text is None or not found.text.strip():
        return default
    try:
        return float(found.text)
    except ValueError:
        return default


def _attr(el: ET.Element, name: str) -> float | None:
    value = el.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def diatonic(step: str, octave: int) -> int:
    return octave * 7 + STEPS.index(step)


def note_name(step: str, alter: int) -> str:
    if alter > 0:
        return step + "#" * alter
    if alter < 0:
        return step + "b" * (-alter)
    return step


class Layout:
    """Page/system/staff layout values, updated as <print> elements appear."""

    def __init__(self, defaults: ET.Element | None):
        page = defaults.find("page-layout") if defaults is not None else None
        margins = page.find("page-margins") if page is not None else None
        self.page_width = _num(page, "page-width")
        self.page_height = _num(page, "page-height")
        self.page_left = _num(margins, "left-margin", 0.0)
        self.page_top = _num(margins, "top-margin", 0.0)
        system = defaults.find("system-layout") if defaults is not None else None
        self.system_left = _num(system, "system-margins/left-margin", 0.0)
        self.system_right = _num(system, "system-margins/right-margin", 0.0)
        self.system_distance = _num(system, "system-distance", DEFAULT_SYSTEM_DISTANCE)
        self.top_system_distance = _num(system, "top-system-distance", 0.0)
        # staff-distance defaults, keyed by staff number (0 = any)
        self.staff_distance: dict[int, float] = {}
        if defaults is not None:
            for sl in defaults.findall("staff-layout"):
                d = _num(sl, "staff-distance")
                if d is not None:
                    self.staff_distance[int(sl.get("number", "0"))] = d

    def default_staff_distance(self, number: int) -> float:
        return self.staff_distance.get(number, self.staff_distance.get(0, DEFAULT_STAFF_DISTANCE))


class Clef:
    def __init__(self, sign: str = "G", line: int = 2, octave_change: int = 0):
        self.sign = sign
        self.line = line
        self.octave_change = octave_change

    def top_line_diatonic(self) -> int | None:
        base = {"G": diatonic("G", 4), "F": diatonic("F", 3), "C": diatonic("C", 4)}.get(self.sign)
        if base is None:
            return None
        return base + (5 - self.line) * 2 + 7 * self.octave_change


def _is_system_start(measure: ET.Element, index: int) -> tuple[bool, bool]:
    """(starts a new system, starts a new page) for a measure of the first part."""
    if index == 0:
        return True, True
    new_system = new_page = False
    for pr in measure.findall("print"):
        if pr.get("new-page") == "yes":
            new_page = new_system = True
        if pr.get("new-system") == "yes":
            new_system = True
    return new_system, new_page


def extract_notes(root: ET.Element) -> dict:
    """Return {"notes": [...], "space": ..} with coordinates as page fractions."""
    layout = Layout(root.find("defaults"))
    if not layout.page_width or not layout.page_height:
        raise ValueError("MusicXML has no page layout, cannot place notes on the page")

    parts = root.findall("part")
    if not parts:
        return {"notes": [], "space": 10.0 / layout.page_height}
    n_measures = min(len(p.findall("measure")) for p in parts)
    part_measures = [p.findall("measure")[:n_measures] for p in parts]

    # Group measure indices into systems, using the first part's breaks.
    systems: list[dict] = []
    for i, m in enumerate(part_measures[0]):
        new_system, new_page = _is_system_start(m, i)
        if new_system:
            systems.append({"measures": [], "new_page": new_page, "start": i})
        systems[-1]["measures"].append(i)

    # How many staves each part has (may change, but rarely does).
    staves_per_part = []
    for measures in part_measures:
        count = 1
        for m in measures:
            s = _num(m, "attributes/staves")
            if s:
                count = int(s)
                break
        staves_per_part.append(count)

    notes: list[dict] = []
    clefs = [dict() for _ in parts]  # part index -> {staff number: Clef}
    divisions = [1.0 for _ in parts]
    prev_bottom = None

    for sysinfo in systems:
        start = sysinfo["start"]
        first_measure = part_measures[0][start]

        # Layout overrides that come with this system.
        system_layout = None
        for pr in first_measure.findall("print"):
            if pr.find("system-layout") is not None:
                system_layout = pr.find("system-layout")
        left = layout.system_left
        top_distance = layout.top_system_distance
        distance = layout.system_distance
        if system_layout is not None:
            left = _num(system_layout, "system-margins/left-margin", left)
            top_distance = _num(system_layout, "top-system-distance", top_distance)
            distance = _num(system_layout, "system-distance", distance)

        if sysinfo["new_page"] or prev_bottom is None:
            system_top = layout.page_top + top_distance
        else:
            system_top = prev_bottom + distance

        # Top line of every staff of every part in this system.
        staff_tops: dict[tuple[int, int], float] = {}
        y = system_top
        first = True
        for p, measures in enumerate(part_measures):
            m = measures[start]
            overrides: dict[int, float] = {}
            for pr in m.findall("print"):
                for sl in pr.findall("staff-layout"):
                    d = _num(sl, "staff-distance")
                    if d is not None:
                        overrides[int(sl.get("number", "1"))] = d
            for s in range(1, staves_per_part[p] + 1):
                if not first:
                    y += STAFF_HEIGHT + overrides.get(s, layout.default_staff_distance(s))
                staff_tops[(p, s)] = y
                first = False
        prev_bottom = y + STAFF_HEIGHT

        # Horizontal position of each measure in this system (from the first part).
        system_left = layout.page_left + left
        widths = [_attr(part_measures[0][i], "width") for i in sysinfo["measures"]]
        known = sum(w for w in widths if w)
        missing = sum(1 for w in widths if not w)
        if missing:
            usable = layout.page_width - layout.page_left - left - layout.system_right - 20.0
            fill = max(usable - known, 0.0) / missing
            widths = [w if w else fill for w in widths]
        measure_x = {}
        x = system_left
        for i, w in zip(sysinfo["measures"], widths):
            measure_x[i] = (x, w)
            x += w

        for p, measures in enumerate(part_measures):
            for i in sysinfo["measures"]:
                mx, mw = measure_x[i]
                notes.extend(_measure_notes(measures[i], p, mx, mw, staff_tops,
                                            clefs[p], divisions, layout))

    return {"notes": notes, "space": 10.0 / layout.page_height}


def _measure_notes(measure, p, mx, mw, staff_tops, clefs, divisions, layout):
    out = []
    # Measure duration, for estimating x when a note has no default-x.
    time = 0.0
    total = 0.0
    events = []
    for el in measure:
        if el.tag == "attributes":
            d = _num(el, "divisions")
            if d:
                divisions[p] = d
            for c in el.findall("clef"):
                number = int(c.get("number", "1"))
                clefs[number] = Clef(
                    (c.findtext("sign") or "G").strip(),
                    int(_num(c, "line", 2)),
                    int(_num(c, "clef-octave-change", 0)),
                )
        elif el.tag == "backup":
            time -= _num(el, "duration", 0.0)
        elif el.tag == "forward":
            time += _num(el, "duration", 0.0)
        elif el.tag == "note":
            is_chord = el.find("chord") is not None
            duration = _num(el, "duration", 0.0)
            onset = events[-1][1] if is_chord and events else time
            events.append((el, onset, duration, dict(clefs)))
            if not is_chord:
                time += duration
        total = max(total, time)

    for el, onset, duration, clef_snapshot in events:
        pitch = el.find("pitch")
        if pitch is None or el.find("rest") is not None:
            continue
        step = (pitch.findtext("step") or "").strip().upper()
        if step not in STEPS:
            continue
        octave = int(_num(pitch, "octave", 4))
        alter = int(round(_num(pitch, "alter", 0.0)))
        staff = int(_num(el, "staff", 1))
        top = staff_tops.get((p, staff))
        if top is None:
            continue

        dx = _attr(el, "default-x")
        if dx is None:
            frac = onset / total if total else 0.0
            dx = 10.0 + frac * max(mw - 20.0, 0.0)
        x = mx + dx

        dy = _attr(el, "default-y")
        if dy is not None:
            y = top - dy
        else:
            clef = clef_snapshot.get(staff, Clef())
            top_line = clef.top_line_diatonic()
            if top_line is None:
                continue
            y = top + (top_line - diatonic(step, octave)) * 5.0

        head = HEAD_WIDTH * (0.7 if el.find("grace") is not None or el.find("cue") is not None else 1.0)
        out.append({
            "x": round(x / layout.page_width, 5),
            "y": round(y / layout.page_height, 5),
            "w": round(head / layout.page_width, 5),
            "step": step,
            "alter": alter,
            "octave": octave,
            "name": note_name(step, alter),
            "staff": staff,
            "part": p,
            "grace": el.find("grace") is not None,
        })
    return out


def notes_from_files(paths: list[Path]) -> dict:
    notes: list[dict] = []
    space = None
    for path in paths:
        result = extract_notes(load_musicxml(path))
        notes.extend(result["notes"])
        space = space or result["space"]
    return {"notes": notes, "space": space}


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(notes_from_files([Path(a) for a in sys.argv[1:]]), indent=1))
