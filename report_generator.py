from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

DARK_BLUE = "1E3A5F"
WHITE = "FFFFFF"
ROW_ALT = "EEF2F7"
RED_LIGHT = "FFCCCC"
ORANGE_LIGHT = "FFE5CC"
YELLOW_LIGHT = "FFFACC"

SEVERITY_BG = {"high": RED_LIGHT, "medium": ORANGE_LIGHT, "low": YELLOW_LIGHT}
SEVERITY_LABEL = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}


def _thin_border() -> Border:
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def _header_style(cell: object, bg: str = DARK_BLUE, fg: str = WHITE) -> None:
    cell.font = Font(bold=True, color=fg, size=11, name="Arial")
    cell.fill = PatternFill(fill_type="solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _thin_border()


def _auto_width(ws) -> None:
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col_letter].width = min(max_len + 4, 45)


def _title_row(ws, text: str, span: str, row: int = 1) -> None:
    ws.merge_cells(span)
    cell = ws[span.split(":")[0]]
    cell.value = text
    cell.font = Font(bold=True, size=14, color=WHITE, name="Arial")
    cell.fill = PatternFill(fill_type="solid", fgColor=DARK_BLUE)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 32


def generate_report(analysis: dict, output_path: str) -> None:
    wb = Workbook()
    _sheet_summary(wb, analysis)
    _sheet_categories(wb, analysis)
    _sheet_transactions(wb, analysis)
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    wb.save(output_path)


# ── Sheet 1: Executive summary ────────────────────────────────────────────────

def _sheet_summary(wb: Workbook, analysis: dict) -> None:
    ws = wb.create_sheet("סיכום מנהלים", 0)
    ws.sheet_view.rightToLeft = True

    _title_row(ws, "דוח ניתוח פיננסי – סיכום מנהלים", "A1:E1", 1)

    ws["A3"] = "סיכום ממצאים:"
    ws["A3"].font = Font(bold=True, size=11, name="Arial")

    ws.merge_cells("A4:E4")
    ws["A4"] = analysis.get("summary", "")
    ws["A4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[4].height = 70

    suspicious = analysis.get("suspicious", [])
    ws["A6"] = f"תנועות חשודות ({len(suspicious)} ממצאים):"
    ws["A6"].font = Font(bold=True, size=11, color="C0392B", name="Arial")

    for col, h in enumerate(["חומרה", "סוג", "תיאור", "סכום (₪)", "תאריך"], 1):
        _header_style(ws.cell(row=7, column=col, value=h))

    for r, item in enumerate(suspicious, 8):
        sev = item.get("severity", "low")
        bg = SEVERITY_BG.get(sev, WHITE)
        for col, v in enumerate(
            [
                SEVERITY_LABEL.get(sev, sev),
                item.get("type", ""),
                item.get("description", ""),
                item.get("amount", ""),
                item.get("date", ""),
            ],
            1,
        ):
            cell = ws.cell(row=r, column=col, value=v)
            cell.fill = PatternFill(fill_type="solid", fgColor=bg)
            cell.border = _thin_border()
            cell.alignment = Alignment(wrap_text=True, vertical="center")

    _auto_width(ws)


# ── Sheet 2: Categories ───────────────────────────────────────────────────────

def _sheet_categories(wb: Workbook, analysis: dict) -> None:
    ws = wb.create_sheet("הוצאות לפי קטגוריה", 1)
    ws.sheet_view.rightToLeft = True

    _title_row(ws, "הוצאות חודשיות לפי קטגוריה", "A1:C1", 1)

    for col, h in enumerate(["קטגוריה", "חודש", "סכום (₪)"], 1):
        _header_style(ws.cell(row=3, column=col, value=h))

    row = 4
    for cat_name, cat_data in analysis.get("categories", {}).items():
        months = cat_data.get("months", {})
        entries = list(months.items()) if months else [("סה\"כ", cat_data.get("total", 0))]
        for month, amount in entries:
            bg = ROW_ALT if row % 2 == 0 else WHITE
            for col, v in enumerate([cat_name, month, amount], 1):
                cell = ws.cell(row=row, column=col, value=v)
                cell.fill = PatternFill(fill_type="solid", fgColor=bg)
                cell.border = _thin_border()
            row += 1

    _auto_width(ws)


# ── Sheet 3: All transactions ─────────────────────────────────────────────────

def _sheet_transactions(wb: Workbook, analysis: dict) -> None:
    ws = wb.create_sheet("כל התנועות", 2)
    ws.sheet_view.rightToLeft = True

    _title_row(ws, "רשימת כל התנועות", "A1:D1", 1)

    for col, h in enumerate(["תאריך", "תיאור", "סכום (₪)", "קטגוריה"], 1):
        _header_style(ws.cell(row=3, column=col, value=h))

    for r, tx in enumerate(analysis.get("transactions", []), 4):
        bg = ROW_ALT if r % 2 == 0 else WHITE
        for col, v in enumerate(
            [tx.get("date", ""), tx.get("description", ""), tx.get("amount", ""), tx.get("category", "")],
            1,
        ):
            cell = ws.cell(row=r, column=col, value=v)
            cell.fill = PatternFill(fill_type="solid", fgColor=bg)
            cell.border = _thin_border()

    _auto_width(ws)
