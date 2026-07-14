from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.models import AnalysisResult, RootEvent


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
    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    pdf.setTitle(f"Bass Catcher - {result.file_name}")

    margin = 34
    header_height = 78
    footer_height = 28
    measures_per_row = 4
    beats_per_measure = 4
    cells_per_row = measures_per_row * beats_per_measure
    row_height = 66
    available_height = page_height - margin * 2 - header_height - footer_height
    rows_per_page = max(1, int(available_height // row_height))

    roots = result.roots
    page_index = 0

    for offset in range(0, max(1, len(roots)), cells_per_row * rows_per_page):
        if page_index:
            pdf.showPage()
        page_index += 1

        _draw_pdf_header(pdf, result, page_width, page_height, margin, page_index)

        page_roots = roots[offset : offset + cells_per_row * rows_per_page]
        start_y = page_height - margin - header_height

        for row_index in range(rows_per_page):
            chunk = page_roots[
                row_index * cells_per_row : (row_index + 1) * cells_per_row
            ]
            if not chunk:
                break

            y = start_y - row_index * row_height
            _draw_root_row(
                pdf,
                chunk,
                x=margin,
                y=y,
                width=page_width - margin * 2,
                height=row_height - 10,
                beats_per_measure=beats_per_measure,
            )

        pdf.setFillColor(colors.HexColor("#5B6470"))
        pdf.setFont("Helvetica", 7)
        pdf.drawString(
            margin,
            margin - 4,
            "Auto-detected roots are suggestions. Confirm by ear before rehearsal or performance.",
        )

    pdf.save()


def _draw_pdf_header(
    pdf: canvas.Canvas,
    result: AnalysisResult,
    page_width: float,
    page_height: float,
    margin: float,
    page_index: int,
) -> None:
    pdf.setFillColor(colors.HexColor("#071018"))
    pdf.rect(0, page_height - 92, page_width, 92, fill=1, stroke=0)

    pdf.setFillColor(colors.HexColor("#00DDE8"))
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawString(margin, page_height - 38, "BASS // CATCHER")

    pdf.setFillColor(colors.HexColor("#FFFFFF"))
    pdf.setFont("Helvetica-Bold", 12)
    title = result.file_name
    max_width = page_width - 360
    while stringWidth(title, "Helvetica-Bold", 12) > max_width and len(title) > 6:
        title = title[:-4] + "..."
    pdf.drawString(margin, page_height - 61, title)

    pdf.setFillColor(colors.HexColor("#FF48D7"))
    pdf.setFont("Helvetica-Bold", 10)
    metadata = f"KEY {result.key_name}    BPM {result.tempo:.1f}    MODE {result.mode}"
    pdf.drawRightString(page_width - margin, page_height - 39, metadata)

    pdf.setFillColor(colors.HexColor("#71808E"))
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(page_width - margin, page_height - 61, f"ROOT CHART / PAGE {page_index}")


def _draw_root_row(
    pdf: canvas.Canvas,
    roots: list[RootEvent],
    x: float,
    y: float,
    width: float,
    height: float,
    beats_per_measure: int,
) -> None:
    cell_width = width / 16

    pdf.setStrokeColor(colors.HexColor("#6E7B86"))
    pdf.setLineWidth(0.7)
    pdf.rect(x, y - height, width, height, fill=0, stroke=1)

    for index in range(1, 16):
        cell_x = x + cell_width * index
        is_measure = index % beats_per_measure == 0
        pdf.setStrokeColor(
            colors.HexColor("#00A6AF") if is_measure else colors.HexColor("#C7CDD2")
        )
        pdf.setLineWidth(1.5 if is_measure else 0.35)
        pdf.line(cell_x, y, cell_x, y - height)

    for index in range(16):
        root = roots[index] if index < len(roots) else None
        cell_x = x + cell_width * index
        measure = index // beats_per_measure + 1
        beat = index % beats_per_measure + 1

        pdf.setFillColor(colors.HexColor("#7D8790"))
        pdf.setFont("Helvetica", 6)
        pdf.drawCentredString(cell_x + cell_width / 2, y - 11, f"{measure}.{beat}")

        note = root.note_name if root else ""
        confidence = root.confidence if root else 0.0

        pdf.setFillColor(
            colors.HexColor("#181A1F") if confidence >= 0.45 else colors.HexColor("#A72882")
        )
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawCentredString(cell_x + cell_width / 2, y - 34, note)

        if root:
            pdf.setFillColor(colors.HexColor("#7D8790"))
            pdf.setFont("Helvetica", 6)
            pdf.drawCentredString(
                cell_x + cell_width / 2,
                y - 47,
                f"{confidence * 100:.0f}%",
            )


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
