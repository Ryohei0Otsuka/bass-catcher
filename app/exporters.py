from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.models import AnalysisResult, RootEvent


PAGE_BACKGROUND = colors.HexColor("#F7F8FA")
INK = colors.HexColor("#171A1F")
MUTED = colors.HexColor("#6B7280")
GRID = colors.HexColor("#A8B0BA")
ACCENT = colors.HexColor("#00A8B5")
LOW_CONFIDENCE = colors.HexColor("#C1268C")
MANUAL_EDIT = colors.HexColor("#087F5B")
HEADER_BACKGROUND = colors.HexColor("#071018")
HEADER_CYAN = colors.HexColor("#00DDE8")
HEADER_PINK = colors.HexColor("#FF48D7")

BEATS_PER_MEASURE = 4
MEASURES_PER_SYSTEM = 4
BEATS_PER_SYSTEM = BEATS_PER_MEASURE * MEASURES_PER_SYSTEM
LOW_CONFIDENCE_THRESHOLD = 0.45


NOTE_STEPS = {
    0: ("C", 0),
    1: ("C", 1),
    2: ("D", 0),
    3: ("D", 1),
    4: ("E", 0),
    5: ("F", 0),
    6: ("F", 1),
    7: ("G", 0),
    8: ("G", 1),
    9: ("A", 0),
    10: ("A", 1),
    11: ("B", 0),
}

DIATONIC_INDEX = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}


def export_session(result: AnalysisResult, output_path: str) -> None:
    Path(output_path).write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_session(input_path: str) -> AnalysisResult:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    return AnalysisResult.from_dict(payload)


def export_csv(result: AnalysisResult, output_path: str) -> None:
    with Path(output_path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "beat",
                "start_seconds",
                "end_seconds",
                "root",
                "midi",
                "confidence",
                "db",
                "source",
                "manually_edited",
            ]
        )
        for root in result.roots:
            writer.writerow(
                [
                    root.beat_index,
                    f"{root.start:.4f}",
                    f"{root.end:.4f}",
                    root.note_name,
                    "" if root.midi is None else root.midi,
                    f"{root.confidence:.4f}",
                    f"{root.db:.2f}",
                    root.source,
                    root.manually_edited,
                ]
            )


def export_pdf(result: AnalysisResult, output_path: str) -> None:
    """Export a readable bass-root chart in conventional score form.

    Each detected beat is rendered as a quarter note on a bass-clef staff.
    Four 4/4 measures are placed on each system. Root names remain visible
    above the notes so the chart is useful even to players who do not read
    standard notation fluently.
    """

    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    pdf.setTitle(f"Bass Catcher Root Score - {result.file_name}")
    pdf.setAuthor("Bass Catcher")

    margin_x = 34
    header_height = 72
    footer_height = 24
    system_height = 148
    system_gap = 8
    available_height = page_height - header_height - footer_height - 24
    systems_per_page = max(1, int((available_height + system_gap) // (system_height + system_gap)))
    beats_per_page = systems_per_page * BEATS_PER_SYSTEM

    roots = list(result.roots)
    total_beats = max(1, len(roots))
    total_pages = max(1, math.ceil(total_beats / beats_per_page))

    for page_index in range(total_pages):
        if page_index:
            pdf.showPage()

        pdf.setFillColor(PAGE_BACKGROUND)
        pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)

        _draw_score_header(
            pdf,
            result,
            page_width=page_width,
            page_height=page_height,
            margin=margin_x,
            page_index=page_index + 1,
            total_pages=total_pages,
        )

        page_start = page_index * beats_per_page
        page_roots = roots[page_start : page_start + beats_per_page]
        top_y = page_height - header_height - 13

        for system_index in range(systems_per_page):
            system_roots = page_roots[
                system_index * BEATS_PER_SYSTEM : (system_index + 1) * BEATS_PER_SYSTEM
            ]
            if not system_roots and roots:
                break

            system_y = top_y - (system_index + 1) * system_height - system_index * system_gap
            global_beat_offset = page_start + system_index * BEATS_PER_SYSTEM
            _draw_score_system(
                pdf,
                roots=system_roots,
                x=margin_x,
                y=system_y,
                width=page_width - margin_x * 2,
                height=system_height,
                global_beat_offset=global_beat_offset,
                show_time_signature=(page_index == 0 and system_index == 0),
            )

        _draw_score_footer(
            pdf,
            margin=margin_x,
            page_width=page_width,
            page_index=page_index + 1,
            total_pages=total_pages,
        )

    pdf.save()


def _draw_score_header(
    pdf: canvas.Canvas,
    result: AnalysisResult,
    page_width: float,
    page_height: float,
    margin: float,
    page_index: int,
    total_pages: int,
) -> None:
    pdf.setFillColor(HEADER_BACKGROUND)
    pdf.rect(0, page_height - 72, page_width, 72, fill=1, stroke=0)

    pdf.setFillColor(HEADER_CYAN)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(margin, page_height - 27, "BASS // CATCHER")

    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 11)
    title = _truncate_text(
        result.file_name,
        font_name="Helvetica-Bold",
        font_size=11,
        max_width=page_width - 390,
    )
    pdf.drawString(margin, page_height - 49, title)

    pdf.setFillColor(HEADER_PINK)
    pdf.setFont("Helvetica-Bold", 9.5)
    metadata = f"KEY {result.key_name}    BPM {result.tempo:.1f}    4/4"
    pdf.drawRightString(page_width - margin, page_height - 27, metadata)

    pdf.setFillColor(colors.HexColor("#A9B4BF"))
    pdf.setFont("Helvetica", 7.5)
    mode = _truncate_text(
        f"ROOT SCORE / {result.mode}",
        font_name="Helvetica",
        font_size=7.5,
        max_width=300,
    )
    pdf.drawRightString(page_width - margin, page_height - 48, mode)

    pdf.setFillColor(colors.HexColor("#768391"))
    pdf.setFont("Helvetica", 6.5)
    pdf.drawRightString(
        page_width - margin,
        page_height - 62,
        f"PAGE {page_index} / {total_pages}",
    )


def _draw_score_system(
    pdf: canvas.Canvas,
    roots: list[RootEvent],
    x: float,
    y: float,
    width: float,
    height: float,
    global_beat_offset: int,
    show_time_signature: bool,
) -> None:
    pdf.setFillColor(colors.white)
    pdf.setStrokeColor(colors.HexColor("#D9DEE4"))
    pdf.setLineWidth(0.6)
    pdf.roundRect(x, y, width, height, 5, fill=1, stroke=1)

    staff_space = 10.0
    staff_bottom = y + 66
    clef_width = 42
    time_width = 25 if show_time_signature else 9
    music_x = x + clef_width + time_width
    music_width = width - clef_width - time_width - 10
    measure_width = music_width / MEASURES_PER_SYSTEM
    beat_width = measure_width / BEATS_PER_MEASURE

    _draw_bass_clef(pdf, x + 11, staff_bottom, staff_space)
    if show_time_signature:
        _draw_time_signature(pdf, x + clef_width - 3, staff_bottom, staff_space)

    # Staff lines.
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.65)
    for line_index in range(5):
        line_y = staff_bottom + line_index * staff_space
        pdf.line(music_x, line_y, music_x + music_width, line_y)

    # Measure and beat guides.
    for measure_index in range(MEASURES_PER_SYSTEM + 1):
        bar_x = music_x + measure_index * measure_width
        pdf.setStrokeColor(INK)
        pdf.setLineWidth(1.25 if measure_index not in {0, MEASURES_PER_SYSTEM} else 1.8)
        pdf.line(bar_x, staff_bottom, bar_x, staff_bottom + 4 * staff_space)

        if measure_index < MEASURES_PER_SYSTEM:
            measure_number = global_beat_offset // BEATS_PER_MEASURE + measure_index + 1
            pdf.setFillColor(MUTED)
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawString(bar_x + 4, staff_bottom + 4 * staff_space + 13, str(measure_number))

            for beat_index in range(1, BEATS_PER_MEASURE):
                guide_x = bar_x + beat_index * beat_width
                pdf.setStrokeColor(colors.HexColor("#E6E9ED"))
                pdf.setLineWidth(0.3)
                pdf.setDash(1.5, 2.5)
                pdf.line(guide_x, staff_bottom - 8, guide_x, staff_bottom + 4 * staff_space + 8)
                pdf.setDash()

    # Notes and labels.
    for local_index in range(BEATS_PER_SYSTEM):
        root = roots[local_index] if local_index < len(roots) else None
        note_x = music_x + local_index * beat_width + beat_width / 2

        pdf.setFillColor(colors.HexColor("#929AA4"))
        pdf.setFont("Helvetica", 6)
        beat_number = local_index % BEATS_PER_MEASURE + 1
        pdf.drawCentredString(note_x, staff_bottom - 19, str(beat_number))

        if root is None:
            continue

        if root.midi is None:
            _draw_quarter_rest(pdf, note_x, staff_bottom + 2 * staff_space, INK)
            _draw_root_label(pdf, root, note_x, staff_bottom + 4 * staff_space + 27)
            continue

        note_y, letter, accidental = _midi_to_staff_position(root.midi, staff_bottom, staff_space)
        note_color = _root_color(root)
        _draw_ledger_lines(pdf, note_x, note_y, staff_bottom, staff_space)
        _draw_notehead_and_stem(
            pdf,
            x=note_x,
            y=note_y,
            staff_middle=staff_bottom + 2 * staff_space,
            color=note_color,
            hollow=root.confidence < LOW_CONFIDENCE_THRESHOLD,
        )

        if accidental:
            pdf.setFillColor(note_color)
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawRightString(note_x - 8, note_y - 3, "#")

        _draw_root_label(pdf, root, note_x, staff_bottom + 4 * staff_space + 27)

    # A strong final bar line makes the system read like actual notation.
    final_x = music_x + music_width
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.8)
    pdf.line(final_x - 4, staff_bottom, final_x - 4, staff_bottom + 4 * staff_space)
    pdf.setLineWidth(2.2)
    pdf.line(final_x, staff_bottom, final_x, staff_bottom + 4 * staff_space)


def _draw_bass_clef(
    pdf: canvas.Canvas,
    x: float,
    staff_bottom: float,
    staff_space: float,
) -> None:
    """Draw a compact bass clef without depending on a music font."""

    center_y = staff_bottom + 2.45 * staff_space
    pdf.saveState()
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(3.0)
    path = pdf.beginPath()
    path.moveTo(x + 8, center_y + 10)
    path.curveTo(x + 25, center_y + 18, x + 28, center_y - 10, x + 9, center_y - 20)
    path.curveTo(x + 17, center_y - 10, x + 18, center_y + 2, x + 8, center_y + 6)
    pdf.drawPath(path, fill=0, stroke=1)

    pdf.setFillColor(INK)
    dot_x = x + 28
    pdf.circle(dot_x, staff_bottom + 3 * staff_space, 1.7, fill=1, stroke=0)
    pdf.circle(dot_x, staff_bottom + 2 * staff_space, 1.7, fill=1, stroke=0)
    pdf.restoreState()


def _draw_time_signature(
    pdf: canvas.Canvas,
    x: float,
    staff_bottom: float,
    staff_space: float,
) -> None:
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(x + 10, staff_bottom + 2.3 * staff_space, "4")
    pdf.drawCentredString(x + 10, staff_bottom + 0.25 * staff_space, "4")


def _midi_to_staff_position(
    midi: int,
    staff_bottom: float,
    staff_space: float,
) -> tuple[float, str, int]:
    pitch_class = midi % 12
    octave = midi // 12 - 1
    letter, accidental = NOTE_STEPS[pitch_class]

    # Bottom line of bass clef is G2.
    note_diatonic = octave * 7 + DIATONIC_INDEX[letter]
    bottom_line_diatonic = 2 * 7 + DIATONIC_INDEX["G"]
    diatonic_steps = note_diatonic - bottom_line_diatonic
    note_y = staff_bottom + diatonic_steps * (staff_space / 2)
    return note_y, letter, accidental


def _draw_ledger_lines(
    pdf: canvas.Canvas,
    note_x: float,
    note_y: float,
    staff_bottom: float,
    staff_space: float,
) -> None:
    top_line = staff_bottom + 4 * staff_space
    ledger_half_width = 10

    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.65)

    if note_y < staff_bottom - 0.1:
        ledger_y = staff_bottom - staff_space
        while ledger_y >= note_y - 0.1:
            pdf.line(note_x - ledger_half_width, ledger_y, note_x + ledger_half_width, ledger_y)
            ledger_y -= staff_space
    elif note_y > top_line + 0.1:
        ledger_y = top_line + staff_space
        while ledger_y <= note_y + 0.1:
            pdf.line(note_x - ledger_half_width, ledger_y, note_x + ledger_half_width, ledger_y)
            ledger_y += staff_space


def _draw_notehead_and_stem(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    staff_middle: float,
    color: colors.Color,
    hollow: bool,
) -> None:
    pdf.saveState()
    pdf.translate(x, y)
    pdf.rotate(-18)
    pdf.setStrokeColor(color)
    pdf.setFillColor(colors.white if hollow else color)
    pdf.setLineWidth(1.15)
    pdf.ellipse(-5.6, -3.5, 5.6, 3.5, fill=1, stroke=1)
    pdf.restoreState()

    stem_up = y <= staff_middle
    pdf.setStrokeColor(color)
    pdf.setLineWidth(1.05)
    if stem_up:
        pdf.line(x + 5, y, x + 5, y + 28)
    else:
        pdf.line(x - 5, y, x - 5, y - 28)


def _draw_quarter_rest(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    color: colors.Color,
) -> None:
    pdf.saveState()
    pdf.setStrokeColor(color)
    pdf.setFillColor(color)
    pdf.setLineWidth(1.7)
    path = pdf.beginPath()
    path.moveTo(x + 2, y + 15)
    path.lineTo(x - 3, y + 6)
    path.lineTo(x + 3, y + 1)
    path.lineTo(x - 2, y - 8)
    pdf.drawPath(path, fill=0, stroke=1)
    pdf.circle(x, y - 11, 2.2, fill=1, stroke=0)
    pdf.restoreState()


def _draw_root_label(
    pdf: canvas.Canvas,
    root: RootEvent,
    x: float,
    y: float,
) -> None:
    color = _root_color(root)
    label = "REST" if root.midi is None else root.note_name
    if root.confidence < LOW_CONFIDENCE_THRESHOLD and not root.manually_edited:
        label += " ?"

    pdf.setFillColor(color)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawCentredString(x, y, label)

    if root.manually_edited:
        pdf.setFillColor(MANUAL_EDIT)
        pdf.setFont("Helvetica-Bold", 5.5)
        pdf.drawCentredString(x, y - 8, "EDIT")
    elif root.confidence < LOW_CONFIDENCE_THRESHOLD:
        pdf.setFillColor(LOW_CONFIDENCE)
        pdf.setFont("Helvetica", 5.5)
        pdf.drawCentredString(x, y - 8, f"{root.confidence * 100:.0f}%")


def _root_color(root: RootEvent) -> colors.Color:
    if root.manually_edited:
        return MANUAL_EDIT
    if root.confidence < LOW_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE
    return INK


def _draw_score_footer(
    pdf: canvas.Canvas,
    margin: float,
    page_width: float,
    page_index: int,
    total_pages: int,
) -> None:
    footer_y = 13
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(
        margin,
        footer_y,
        "Black: detected root   Pink + ?: low confidence   Green + EDIT: manually corrected",
    )
    pdf.drawRightString(
        page_width - margin,
        footer_y,
        f"Confirm all roots by ear before rehearsal or performance.  {page_index}/{total_pages}",
    )


def _truncate_text(
    text: str,
    font_name: str,
    font_size: float,
    max_width: float,
) -> str:
    if stringWidth(text, font_name, font_size) <= max_width:
        return text

    shortened = text
    while len(shortened) > 4:
        shortened = shortened[:-1]
        candidate = shortened.rstrip() + "..."
        if stringWidth(candidate, font_name, font_size) <= max_width:
            return candidate
    return "..."


def export_musicxml(result: AnalysisResult, output_path: str) -> None:
    measures: list[str] = []
    roots = result.roots

    for measure_index in range(0, len(roots), 4):
        notes = roots[measure_index : measure_index + 4]
        note_xml = "\n".join(_root_to_musicxml(root) for root in notes)
        while len(notes) < 4:
            note_xml += "\n" + _rest_musicxml()
            notes.append(
                RootEvent(
                    beat_index=0,
                    start=0,
                    end=0,
                    midi=None,
                    confidence=0,
                    db=-80,
                )
            )

        attributes = ""
        if measure_index == 0:
            attributes = """
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>F</sign><line>4</line></clef>
      </attributes>
      <direction placement="above">
        <direction-type><words>Bass Catcher root chart</words></direction-type>
        <sound tempo="{tempo:.2f}"/>
      </direction>""".format(tempo=result.tempo)

        measures.append(
            f"""    <measure number="{measure_index // 4 + 1}">
{attributes}
{note_xml}
    </measure>"""
        )

    title = html.escape(result.file_name)
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE score-partwise PUBLIC
    "-//Recordare//DTD MusicXML 4.0 Partwise//EN"
    "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work><work-title>{title}</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Bass</part-name></score-part>
  </part-list>
  <part id="P1">
{chr(10).join(measures)}
  </part>
</score-partwise>
"""
    Path(output_path).write_text(xml, encoding="utf-8")


def _root_to_musicxml(root: RootEvent) -> str:
    if root.midi is None:
        return _rest_musicxml()

    pitch_class = root.midi % 12
    octave = root.midi // 12 - 1
    step_map = {
        0: ("C", None),
        1: ("C", 1),
        2: ("D", None),
        3: ("D", 1),
        4: ("E", None),
        5: ("F", None),
        6: ("F", 1),
        7: ("G", None),
        8: ("G", 1),
        9: ("A", None),
        10: ("A", 1),
        11: ("B", None),
    }
    step, alter = step_map[pitch_class]
    alter_xml = "" if alter is None else f"<alter>{alter}</alter>"

    return f"""      <note>
        <pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>
        <duration>1</duration><voice>1</voice><type>quarter</type>
      </note>"""


def _rest_musicxml() -> str:
    return """      <note>
        <rest/><duration>1</duration><voice>1</voice><type>quarter</type>
      </note>"""
