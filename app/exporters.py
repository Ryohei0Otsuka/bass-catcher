from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.models import AnalysisResult, RootEvent


PAGE_BACKGROUND = colors.HexColor("#F6F7F9")
INK = colors.HexColor("#171A1F")
MUTED = colors.HexColor("#66717E")
LIGHT = colors.HexColor("#D8DEE5")
GUIDE = colors.HexColor("#ADB6C0")
LOW_CONFIDENCE = colors.HexColor("#C1268C")
MANUAL_EDIT = colors.HexColor("#087F5B")
HEADER_BACKGROUND = colors.HexColor("#071018")
HEADER_CYAN = colors.HexColor("#00DDE8")
HEADER_PINK = colors.HexColor("#FF48D7")

BEATS_PER_MEASURE = 4
MEASURES_PER_SYSTEM = 4
BEATS_PER_SYSTEM = BEATS_PER_MEASURE * MEASURES_PER_SYSTEM
LOW_CONFIDENCE_THRESHOLD = 0.45

PDF_FONT = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"


def _register_pdf_fonts() -> None:
    """Use a Unicode-capable system font when one is available."""

    global PDF_FONT, PDF_FONT_BOLD

    regular_candidates = [
        Path(r"C:\Windows\Fonts\YuGothR.ttc"),
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        Path(r"C:\Windows\Fonts\YuGothB.ttc"),
        Path(r"C:\Windows\Fonts\meiryob.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]

    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), None)

    if regular is not None:
        try:
            pdfmetrics.registerFont(TTFont("BassCatcherPDF", str(regular), subfontIndex=0))
            PDF_FONT = "BassCatcherPDF"

            if bold is not None:
                try:
                    pdfmetrics.registerFont(
                        TTFont("BassCatcherPDF-Bold", str(bold), subfontIndex=0)
                    )
                    PDF_FONT_BOLD = "BassCatcherPDF-Bold"
                except Exception:
                    PDF_FONT_BOLD = PDF_FONT
            else:
                PDF_FONT_BOLD = PDF_FONT
            return
        except Exception:
            pass

    # Portable fallback for Japanese file names. This uses a standard PDF CJK
    # font mapping and avoids square glyphs when no suitable TTF/TTC is found.
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        PDF_FONT = "HeiseiKakuGo-W5"
        PDF_FONT_BOLD = "HeiseiKakuGo-W5"
    except Exception:
        PDF_FONT = "Helvetica"
        PDF_FONT_BOLD = "Helvetica-Bold"


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
    """Export a staff-less rhythm chart for rehearsal use.

    The PDF intentionally avoids both spreadsheet-style cells and a five-line
    staff. Measures flow horizontally like a band chord chart. Each beat is
    represented by a rhythm slash, while root names are printed above changes.
    Rests are shown as N.C. with a rest mark.
    """

    _register_pdf_fonts()

    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    pdf.setTitle(f"Bass Catcher Root Chart - {result.file_name}")
    pdf.setAuthor("Bass Catcher")

    margin_x = 38
    header_height = 76
    footer_height = 24
    system_height = 86
    system_gap = 14
    top_y = page_height - header_height - 24
    available_height = top_y - footer_height - 12
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

        _draw_chart_header(
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

        for system_index in range(systems_per_page):
            system_roots = page_roots[
                system_index * BEATS_PER_SYSTEM : (system_index + 1) * BEATS_PER_SYSTEM
            ]
            if not system_roots and roots:
                break

            system_top = top_y - system_index * (system_height + system_gap)
            global_beat_offset = page_start + system_index * BEATS_PER_SYSTEM
            previous_root = roots[global_beat_offset - 1] if global_beat_offset > 0 else None

            _draw_rhythm_system(
                pdf,
                roots=system_roots,
                x=margin_x,
                top_y=system_top,
                width=page_width - margin_x * 2,
                height=system_height,
                global_beat_offset=global_beat_offset,
                previous_root=previous_root,
                show_time_signature=(page_index == 0 and system_index == 0),
            )

        _draw_chart_footer(
            pdf,
            margin=margin_x,
            page_width=page_width,
            page_index=page_index + 1,
            total_pages=total_pages,
        )

    pdf.save()


def _draw_chart_header(
    pdf: canvas.Canvas,
    result: AnalysisResult,
    page_width: float,
    page_height: float,
    margin: float,
    page_index: int,
    total_pages: int,
) -> None:
    pdf.setFillColor(HEADER_BACKGROUND)
    pdf.rect(0, page_height - 76, page_width, 76, fill=1, stroke=0)

    pdf.setFillColor(HEADER_CYAN)
    pdf.setFont(PDF_FONT_BOLD, 17)
    pdf.drawString(margin, page_height - 28, "BASS // CATCHER")

    pdf.setFillColor(colors.white)
    pdf.setFont(PDF_FONT_BOLD, 10.5)
    title = _truncate_text(
        result.file_name,
        font_name=PDF_FONT_BOLD,
        font_size=10.5,
        max_width=page_width - 370,
    )
    pdf.drawString(margin, page_height - 51, title)

    pdf.setFillColor(HEADER_PINK)
    pdf.setFont(PDF_FONT_BOLD, 9.5)
    pdf.drawRightString(
        page_width - margin,
        page_height - 29,
        f"ROOT CHART    KEY {result.key_name}    BPM {result.tempo:.1f}    4/4",
    )

    pdf.setFillColor(colors.HexColor("#A9B4BF"))
    pdf.setFont(PDF_FONT, 7.2)
    mode = _truncate_text(
        result.mode,
        font_name=PDF_FONT,
        font_size=7.2,
        max_width=310,
    )
    pdf.drawRightString(page_width - margin, page_height - 50, mode)

    pdf.setFillColor(colors.HexColor("#768391"))
    pdf.setFont(PDF_FONT, 6.5)
    pdf.drawRightString(
        page_width - margin,
        page_height - 64,
        f"PAGE {page_index} / {total_pages}",
    )


def _draw_rhythm_system(
    pdf: canvas.Canvas,
    roots: list[RootEvent],
    x: float,
    top_y: float,
    width: float,
    height: float,
    global_beat_offset: int,
    previous_root: RootEvent | None,
    show_time_signature: bool,
) -> None:
    content_bottom = top_y - height
    rhythm_y = content_bottom + 29
    symbol_y = content_bottom + 57

    time_width = 32 if show_time_signature else 10
    music_x = x + time_width
    music_width = width - time_width
    measure_width = music_width / MEASURES_PER_SYSTEM
    beat_width = measure_width / BEATS_PER_MEASURE

    if show_time_signature:
        pdf.setFillColor(INK)
        pdf.setFont(PDF_FONT_BOLD, 15)
        pdf.drawCentredString(x + 12, rhythm_y + 9, "4")
        pdf.drawCentredString(x + 12, rhythm_y - 10, "4")

    # A light guide gives the chart a score-like horizontal flow without
    # becoming a grid or a five-line staff.
    pdf.setStrokeColor(LIGHT)
    pdf.setLineWidth(0.65)
    pdf.line(music_x, rhythm_y, music_x + music_width, rhythm_y)

    for measure_index in range(MEASURES_PER_SYSTEM + 1):
        bar_x = music_x + measure_index * measure_width
        is_outer = measure_index in {0, MEASURES_PER_SYSTEM}

        pdf.setStrokeColor(INK)
        pdf.setLineWidth(1.7 if is_outer else 1.1)
        pdf.line(bar_x, rhythm_y - 20, bar_x, rhythm_y + 21)

        if measure_index < MEASURES_PER_SYSTEM:
            measure_number = global_beat_offset // BEATS_PER_MEASURE + measure_index + 1
            pdf.setFillColor(MUTED)
            pdf.setFont(PDF_FONT_BOLD, 6.5)
            pdf.drawString(bar_x + 4, top_y - 5, str(measure_number))

    for local_index in range(BEATS_PER_SYSTEM):
        root = roots[local_index] if local_index < len(roots) else None
        beat_x = music_x + local_index * beat_width + beat_width / 2
        beat_in_measure = local_index % BEATS_PER_MEASURE

        if root is None:
            pdf.setStrokeColor(GUIDE)
            pdf.setLineWidth(2.0)
            pdf.line(beat_x - 5, rhythm_y - 8, beat_x + 5, rhythm_y + 8)
            continue

        previous = roots[local_index - 1] if local_index > 0 else previous_root
        must_label = (
            beat_in_measure == 0
            or previous is None
            or previous.midi != root.midi
            or root.manually_edited
            or root.confidence < LOW_CONFIDENCE_THRESHOLD
        )

        if root.midi is None:
            _draw_rest_mark(pdf, beat_x, rhythm_y, _root_color(root))
            if must_label:
                _draw_chart_symbol(pdf, root, beat_x, symbol_y)
            continue

        # Rhythm slash: this is the musical pulse, not a table cell.
        pdf.setStrokeColor(_root_color(root))
        pdf.setLineWidth(2.0)
        pdf.line(beat_x - 5, rhythm_y - 8, beat_x + 5, rhythm_y + 8)

        if must_label:
            _draw_chart_symbol(pdf, root, beat_x, symbol_y)

    # Traditional double bar at the end of each system.
    final_x = music_x + music_width
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.8)
    pdf.line(final_x - 4, rhythm_y - 20, final_x - 4, rhythm_y + 21)
    pdf.setLineWidth(2.2)
    pdf.line(final_x, rhythm_y - 20, final_x, rhythm_y + 21)


def _draw_rest_mark(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    color: colors.Color,
) -> None:
    pdf.saveState()
    pdf.setStrokeColor(color)
    pdf.setFillColor(color)
    pdf.setLineWidth(1.6)
    path = pdf.beginPath()
    path.moveTo(x + 2, y + 10)
    path.lineTo(x - 3, y + 3)
    path.lineTo(x + 3, y - 2)
    path.lineTo(x - 2, y - 9)
    pdf.drawPath(path, fill=0, stroke=1)
    pdf.circle(x, y - 12, 1.8, fill=1, stroke=0)
    pdf.restoreState()


def _draw_chart_symbol(
    pdf: canvas.Canvas,
    root: RootEvent,
    x: float,
    y: float,
) -> None:
    color = _root_color(root)
    label = "N.C." if root.midi is None else root.pitch_class

    if root.confidence < LOW_CONFIDENCE_THRESHOLD and not root.manually_edited:
        label += " ?"

    pdf.setFillColor(color)
    pdf.setFont(PDF_FONT_BOLD, 13)
    pdf.drawCentredString(x, y, label)

    if root.manually_edited:
        pdf.setFillColor(MANUAL_EDIT)
        pdf.setFont(PDF_FONT_BOLD, 5.5)
        pdf.drawCentredString(x, y - 9, "EDIT")
    elif root.confidence < LOW_CONFIDENCE_THRESHOLD:
        pdf.setFillColor(LOW_CONFIDENCE)
        pdf.setFont(PDF_FONT, 5.5)
        pdf.drawCentredString(x, y - 9, f"{root.confidence * 100:.0f}%")


def _root_color(root: RootEvent) -> colors.Color:
    if root.manually_edited:
        return MANUAL_EDIT
    if root.confidence < LOW_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE
    return INK


def _draw_chart_footer(
    pdf: canvas.Canvas,
    margin: float,
    page_width: float,
    page_index: int,
    total_pages: int,
) -> None:
    footer_y = 13
    pdf.setFillColor(MUTED)
    pdf.setFont(PDF_FONT, 6.3)
    pdf.drawString(
        margin,
        footer_y,
        "Root name: change or measure head   /: beat   N.C.: rest   ?: low confidence   EDIT: corrected",
    )
    pdf.drawRightString(
        page_width - margin,
        footer_y,
        f"Confirm by ear before rehearsal or performance.  {page_index}/{total_pages}",
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
