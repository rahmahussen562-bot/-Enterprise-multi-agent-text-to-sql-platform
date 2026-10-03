"""
SentinelSQL Enterprise Documentation PDF Generator
Compiles Markdown technical documentation into publication-ready,
executive-grade PDF documents (English and Arabic) with corporate styling.
"""
import os
import re
import sys
from pathlib import Path

# PDF & Formatting Libraries
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Preformatted,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Text Shaping for Arabic RTL
import arabic_reshaper
from bidi.algorithm import get_display

# -----------------------------------------------------------------------------
# Font Registration & Typography
# -----------------------------------------------------------------------------
FONT_CONFIGS = [
    ("Arial", "C:/Windows/Fonts/arial.ttf"),
    ("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"),
    ("Arial-Italic", "C:/Windows/Fonts/ariali.ttf"),
    ("Arial-BoldItalic", "C:/Windows/Fonts/arialbi.ttf"),
    ("Consolas", "C:/Windows/Fonts/consola.ttf"),
]

PRIMARY_FONT = "Helvetica"
PRIMARY_BOLD = "Helvetica-Bold"
MONO_FONT = "Courier"

for font_name, font_path in FONT_CONFIGS:
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            if font_name == "Arial":
                PRIMARY_FONT = "Arial"
            elif font_name == "Arial-Bold":
                PRIMARY_BOLD = "Arial-Bold"
            elif font_name == "Consolas":
                MONO_FONT = "Consolas"
        except Exception as e:
            print(f"Warning: Could not register font {font_name}: {e}")

# Register font family if Arial is present
try:
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily(
        "Arial",
        normal="Arial",
        bold="Arial-Bold",
        italic="Arial-Italic",
        boldItalic="Arial-BoldItalic"
    )
except Exception:
    pass


# -----------------------------------------------------------------------------
# Corporate Palette Definition
# -----------------------------------------------------------------------------
COLOR_PRIMARY_DARK = colors.HexColor("#0f172a")    # Slate 900
COLOR_SECONDARY_DARK = colors.HexColor("#1e293b")  # Slate 800
COLOR_ACCENT_CYAN = colors.HexColor("#0284c7")     # Sky 600 / Cyan
COLOR_LIGHT_BG = colors.HexColor("#f8fafc")        # Slate 50
COLOR_ALT_ROW = colors.HexColor("#f1f5f9")         # Slate 100
COLOR_BORDER = colors.HexColor("#cbd5e1")          # Slate 300
COLOR_TEXT_DARK = colors.HexColor("#0f172a")       # Slate 900
COLOR_TEXT_MUTED = colors.HexColor("#64748b")      # Slate 500
COLOR_WHITE = colors.HexColor("#ffffff")


# -----------------------------------------------------------------------------
# Numbered Canvas for Two-Pass Page Count
# -----------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that writes total page count in the footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.doc_title = "SentinelSQL Enterprise Technical Documentation"
        self.is_arabic = False

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        page_w, page_h = letter
        margin = 36

        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.setFont(PRIMARY_FONT, 8)
            self.setFillColor(COLOR_TEXT_MUTED)
            if self.is_arabic:
                header_text = get_display(arabic_reshaper.reshape("منصة SentinelSQL للمؤسسات — التوثيق الهندسي والمعماري"))
                self.drawRightString(page_w - margin, page_h - 26, header_text)
            else:
                self.drawString(margin, page_h - 26, self.doc_title)

            self.setStrokeColor(COLOR_BORDER)
            self.setLineWidth(0.5)
            self.line(margin, page_h - 30, page_w - margin, page_h - 30)

        # Footer (All pages)
        self.setStrokeColor(COLOR_BORDER)
        self.setLineWidth(0.5)
        self.line(margin, 38, page_w - margin, 38)

        self.setFont(PRIMARY_FONT, 8)
        self.setFillColor(COLOR_TEXT_MUTED)

        if self.is_arabic:
            footer_left = "SentinelSQL Enterprise Platform | Confidential / Restricted"
            page_str = get_display(arabic_reshaper.reshape(f"صفحة {self._pageNumber} من {total_pages}"))
            self.drawString(margin, 26, footer_left)
            self.drawRightString(page_w - margin, 26, page_str)
        else:
            footer_left = "SentinelSQL Enterprise Platform | T-SQL Gateway & Hallucination Defense"
            page_str = f"Page {self._pageNumber} of {total_pages}"
            self.drawString(margin, 26, footer_left)
            self.drawRightString(page_w - margin, 26, page_str)

        self.restoreState()


# -----------------------------------------------------------------------------
# Text Formatting Helpers
# -----------------------------------------------------------------------------
def format_text_en(text: str) -> str:
    """Format markdown for English LTR paragraphs with valid XML tags."""
    # 1. Protect code spans `...`
    code_spans = []
    def code_repl(m):
        code_spans.append(m.group(1))
        return f"__CODESPAN_{len(code_spans)-1}__"

    t = re.sub(r"`([^`]+)`", code_repl, text)

    # 2. Clean LaTeX math formatting
    t = re.sub(r"\\text\{([^}]+)\}", r"\1", t)
    t = t.replace(r"\sum", "SUM").replace(r"\times", "*")
    t = re.sub(r"\$([^$]+)\$", r"<i>\1</i>", t)

    # 3. Escape XML special characters
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 4. Convert **bold**
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)

    # 5. Convert *italic* (only words, avoiding wildcards like *.db)
    t = re.sub(r"(?<![\w*])\*([^*]+)\*(?![\w*])", r"<i>\1</i>", t)

    # 6. Restore code spans cleanly
    for idx, code_val in enumerate(code_spans):
        safe_code = code_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = t.replace(f"__CODESPAN_{idx}__", f'<font name="Courier" color="#0369a1">{safe_code}</font>')

    return t


def format_text_ar(text: str) -> str:
    """Format markdown for Arabic RTL paragraphs with proper BiDi shaping."""
    # Strip markdown syntax markers to ensure pure plain text before BiDi layout
    t = re.sub(r"\\text\{([^}]+)\}", r"\1", text)
    t = t.replace(r"\sum", "SUM").replace(r"\times", "*")
    t = re.sub(r"\$([^$]+)\$", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)

    # Escape XML characters for ReportLab safety
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Reshape Arabic characters and apply BiDi display ordering
    reshaped = arabic_reshaper.reshape(t)
    return get_display(reshaped)


def format_text(text: str, is_arabic: bool = False) -> str:
    if is_arabic:
        return format_text_ar(text)
    return format_text_en(text)


# -----------------------------------------------------------------------------
# Markdown Parser & Document Builder
# -----------------------------------------------------------------------------
def build_pdf_from_markdown(md_path: Path, output_pdf: Path, is_arabic: bool = False):
    """Parse a Markdown document and render a polished corporate PDF."""
    print(f"Compiling {md_path.name} -> {output_pdf.name} (is_arabic={is_arabic})...")
    
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=46,
        bottomMargin=46,
    )

    styles = getSampleStyleSheet()

    # Base typography styles
    align_body = 2 if is_arabic else 0  # 2 = Right-align for Arabic, 0 = Left-align for English
    align_h1 = 2 if is_arabic else 0
    font_body = PRIMARY_FONT
    font_bold = PRIMARY_BOLD

    style_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=18,
        leading=22,
        textColor=COLOR_PRIMARY_DARK,
        alignment=align_h1,
        spaceAfter=4,
    )
    style_subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=10,
        leading=14,
        textColor=COLOR_ACCENT_CYAN,
        alignment=align_h1,
        spaceAfter=10,
    )
    style_h1 = ParagraphStyle(
        "SectionH1",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=12.5,
        leading=16,
        textColor=COLOR_PRIMARY_DARK,
        alignment=align_h1,
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
    )
    style_h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=10.5,
        leading=14,
        textColor=COLOR_SECONDARY_DARK,
        alignment=align_h1,
        spaceBefore=9,
        spaceAfter=3,
        keepWithNext=True,
    )
    style_body = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=8.5,
        leading=12.5,
        textColor=COLOR_TEXT_DARK,
        alignment=align_body,
        spaceAfter=5,
    )
    style_bullet = ParagraphStyle(
        "BulletText",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=8.5,
        leading=12,
        textColor=COLOR_TEXT_DARK,
        alignment=align_body,
        leftIndent=0 if is_arabic else 14,
        rightIndent=14 if is_arabic else 0,
        spaceAfter=3,
    )
    style_code_block = ParagraphStyle(
        "CodeBlockStyle",
        parent=styles["Normal"],
        fontName=MONO_FONT,
        fontSize=6.5,
        leading=8.5,
        textColor=colors.HexColor("#0f172a"),
        alignment=0,  # Code is always LTR
    )
    style_table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=font_body,
        fontSize=7.5,
        leading=10.5,
        textColor=COLOR_TEXT_DARK,
        alignment=align_body,
    )
    style_table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=7.5,
        leading=10.5,
        textColor=COLOR_WHITE,
        alignment=align_body,
    )

    story = []

    lines = md_text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # Blank line
        if not line:
            i += 1
            continue

        # Horizontal Rule
        if line.startswith("---") or line.startswith("***"):
            story.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER, spaceBefore=5, spaceAfter=6))
            i += 1
            continue

        # Code block / Diagram
        if line.startswith("```"):
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # Skip closing ```
            code_content = "\n".join(code_lines)
            
            # Render inside styled table box
            p_code = Preformatted(code_content, style_code_block)
            code_table = Table([[p_code]], colWidths=[540])
            code_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_LIGHT_BG),
                ("BOX", (0, 0), (-1, -1), 0.75, COLOR_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(KeepTogether([code_table, Spacer(1, 5)]))
            continue

        # Markdown Table
        if line.startswith("|") and line.endswith("|"):
            table_raw_rows = []
            while i < n and lines[i].strip().startswith("|"):
                row_line = lines[i].strip()
                # Skip markdown separator row like | :--- | :--- |
                if not re.match(r"^\|(\s*:?-+:?\s*\|)+$", row_line):
                    # Split cells by pipe
                    cells = [c.strip() for c in row_line.split("|")[1:-1]]
                    table_raw_rows.append(cells)
                i += 1

            if table_raw_rows:
                num_cols = len(table_raw_rows[0])
                total_w = 540

                # Adaptive column widths based on table structure
                if num_cols == 2:
                    col_widths = [160, 380]
                elif num_cols == 3:
                    if is_arabic:
                        col_widths = [190, 190, 160]
                    else:
                        col_widths = [140, 200, 200]
                elif num_cols == 4:
                    if is_arabic:
                        col_widths = [80, 200, 140, 120]
                    else:
                        col_widths = [110, 130, 220, 80]
                else:
                    col_widths = [total_w / num_cols] * num_cols

                table_data = []
                for row_idx, r in enumerate(table_raw_rows):
                    row_cells = []
                    is_header = (row_idx == 0)
                    cell_style = style_table_header if is_header else style_table_cell

                    for c in r:
                        c_formatted = format_text(c, is_arabic=is_arabic)
                        row_cells.append(Paragraph(c_formatted, cell_style))
                    table_data.append(row_cells)

                t = Table(table_data, colWidths=col_widths)
                t_style = [
                    ("BACKGROUND", (0, 0), (-1, 0), COLOR_SECONDARY_DARK),
                    ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
                # Alternate row shading
                for r_i in range(1, len(table_data)):
                    bg = COLOR_ALT_ROW if r_i % 2 == 1 else COLOR_WHITE
                    t_style.append(("BACKGROUND", (0, r_i), (-1, r_i), bg))

                t.setStyle(TableStyle(t_style))
                story.append(KeepTogether([t, Spacer(1, 5)]))
            continue

        # Headings
        if line.startswith("# "):
            title_text = format_text(line[2:].strip(), is_arabic=is_arabic)
            story.append(Paragraph(title_text, style_title))
            i += 1
            continue
        elif line.startswith("## "):
            h1_text = format_text(line[3:].strip(), is_arabic=is_arabic)
            story.append(Paragraph(h1_text, style_h1))
            i += 1
            continue
        elif line.startswith("### "):
            h2_text = format_text(line[4:].strip(), is_arabic=is_arabic)
            story.append(Paragraph(h2_text, style_h2))
            i += 1
            continue
        elif line.startswith("#### "):
            h3_text = format_text(line[5:].strip(), is_arabic=is_arabic)
            story.append(Paragraph(h3_text, style_h2))
            i += 1
            continue

        # Bullet List Items
        if re.match(r"^[-*]\s+", line):
            content = re.sub(r"^[-*]\s+", "", line)
            bullet_sym = "• "
            formatted_bullet = format_text(f"{bullet_sym}{content}", is_arabic=is_arabic)
            story.append(Paragraph(formatted_bullet, style_bullet))
            i += 1
            continue

        # Numbered List Items
        num_match = re.match(r"^(\d+)\.\s+(.+)$", line)
        if num_match:
            num_str, content = num_match.groups()
            formatted_num = format_text(f"{num_str}. {content}", is_arabic=is_arabic)
            story.append(Paragraph(formatted_num, style_bullet))
            i += 1
            continue

        # Regular Paragraph
        para_lines = [line]
        i += 1
        while i < n:
            next_line = lines[i].strip()
            if (
                not next_line
                or next_line.startswith("#")
                or next_line.startswith("---")
                or next_line.startswith("```")
                or next_line.startswith("|")
                or re.match(r"^[-*]\s+", next_line)
                or re.match(r"^\d+\.\s+", next_line)
            ):
                break
            para_lines.append(next_line)
            i += 1

        full_para_text = " ".join(para_lines)
        if full_para_text.startswith("*") and full_para_text.endswith("*") and not full_para_text.startswith("**"):
            p_style = style_subtitle
        else:
            p_style = style_body

        formatted_para = format_text(full_para_text, is_arabic=is_arabic)
        story.append(Paragraph(formatted_para, p_style))

    # Canvas setup with custom header/footer
    def canvas_maker(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.is_arabic = is_arabic
        if is_arabic:
            c.doc_title = "وثيقة التوثيق الهندسي والمعماري لمنصة SentinelSQL"
        else:
            c.doc_title = "SentinelSQL Enterprise Technical Documentation"
        return c

    doc.build(story, canvasmaker=canvas_maker)
    print(f"Successfully generated: {output_pdf} (Size: {os.path.getsize(output_pdf)} bytes)")


# -----------------------------------------------------------------------------
# Main Execution Entrypoint
# -----------------------------------------------------------------------------
def main():
    workspace_root = Path(__file__).resolve().parent.parent
    docs_dir = workspace_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    en_md = docs_dir / "DOCUMENTATION_EN.md"
    ar_md = docs_dir / "DOCUMENTATION_AR.md"

    en_pdf = docs_dir / "SentinelSQL_Enterprise_Documentation_EN.pdf"
    ar_pdf = docs_dir / "SentinelSQL_Enterprise_Documentation_AR.pdf"

    if not en_md.exists():
        print(f"Error: English Markdown file not found at {en_md}")
        sys.exit(1)

    if not ar_md.exists():
        print(f"Error: Arabic Markdown file not found at {ar_md}")
        sys.exit(1)

    # 1. Compile English Documentation PDF
    build_pdf_from_markdown(en_md, en_pdf, is_arabic=False)

    # 2. Compile Arabic Documentation PDF
    build_pdf_from_markdown(ar_md, ar_pdf, is_arabic=True)

    print("\nDocumentation PDF Compilation Complete!")
    print(f"  English PDF: {en_pdf} ({en_pdf.stat().st_size:,} bytes)")
    print(f"  Arabic PDF:  {ar_pdf} ({ar_pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
