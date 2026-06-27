"""Genera el XLSX de 4 hojas del Motor de Inteligencia de Costos (Módulo 5).

Toma estructuras de datos planas (dicts/listas, no objetos de dominio) → es
fácil de testear y desacoplado. Hojas:
  1. Presupuesto      — totales (materiales, MO, duración, total)
  2. Escenarios       — comparativa de recetas alternativas (Δ$ y días)
  3. Proyección       — costo proyectado a futuro (IPC real)
  4. Detalle materiales — cantidades y costos por material
"""
from __future__ import annotations

from io import BytesIO
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14)
_TOTAL_FONT = Font(bold=True)
_MONEY_FMT = '#,##0.00 "ARS"'
_PCT_FMT = '+0.0"%";-0.0"%"'


def _header_row(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _autosize(ws: Worksheet, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def build_workbook(sim: dict, scenarios: Iterable[dict], projections: Iterable[dict]) -> bytes:
    wb = Workbook()
    totals = sim["totals"]
    total_obra = totals["materials"] + totals["labor_cost"]

    # --- Hoja 1: Presupuesto ---
    ws = wb.active
    ws.title = "Presupuesto"
    ws["A1"] = sim.get("name") or "Presupuesto"
    ws["A1"].font = _TITLE_FONT
    _header_row(ws, 3, ["Rubro", "Monto"])
    data = [
        ("Materiales", totals["materials"]),
        ("Mano de obra", totals["labor_cost"]),
        ("TOTAL OBRA", total_obra),
        ("Horas hombre", totals["labor_hours"]),
        ("Duración estimada (días)", totals["duration_days"]),
    ]
    for i, (label, value) in enumerate(data, start=4):
        ws.cell(row=i, column=1, value=label)
        c = ws.cell(row=i, column=2, value=round(value, 2))
        if label not in ("Horas hombre", "Duración estimada (días)"):
            c.number_format = _MONEY_FMT
        if label == "TOTAL OBRA":
            ws.cell(row=i, column=1).font = _TOTAL_FONT
            c.font = _TOTAL_FONT
    _autosize(ws, [28, 22])

    # --- Hoja 2: Escenarios ---
    ws2 = wb.create_sheet("Escenarios")
    ws2["A1"] = "Comparativa de sistemas alternativos"
    ws2["A1"].font = _TITLE_FONT
    _header_row(ws2, 3, ["Entidad", "Sistema base", "Alternativa",
                         "Δ Materiales", "Δ Mano de obra", "Días ahorrados"])
    r = 4
    for s in scenarios:
        ws2.cell(row=r, column=1, value=s["entity"])
        ws2.cell(row=r, column=2, value=s["base"])
        ws2.cell(row=r, column=3, value=s["alternative"])
        ws2.cell(row=r, column=4, value=round(s["material_diff"], 2)).number_format = _MONEY_FMT
        ws2.cell(row=r, column=5, value=round(s["labor_diff"], 2)).number_format = _MONEY_FMT
        ws2.cell(row=r, column=6, value=round(s["time_saved"], 1))
        r += 1
    if r == 4:
        ws2.cell(row=4, column=1, value="(sin entidades con alternativas en este plano)")
    _autosize(ws2, [16, 30, 30, 18, 18, 16])

    # --- Hoja 3: Proyección ---
    ws3 = wb.create_sheet("Proyección")
    ws3["A1"] = "Proyección de costo (inflación IPC)"
    ws3["A1"].font = _TITLE_FONT
    _header_row(ws3, 3, ["Horizonte", "Costo proyectado", "Variación"])
    ws3.cell(row=4, column=1, value="Hoy")
    ws3.cell(row=4, column=2, value=round(total_obra, 2)).number_format = _MONEY_FMT
    r = 5
    for p in projections:
        ws3.cell(row=r, column=1, value=f"{p['horizon_months']} meses")
        ws3.cell(row=r, column=2, value=round(p["projected_cost"], 2)).number_format = _MONEY_FMT
        ws3.cell(row=r, column=3, value=round(p["variation"], 1)).number_format = _PCT_FMT
        r += 1
    if r == 5:
        ws3.cell(row=5, column=1, value="(sin índice de inflación cargado)")
    _autosize(ws3, [16, 22, 14])

    # --- Hoja 4: Detalle materiales ---
    ws4 = wb.create_sheet("Detalle materiales")
    ws4["A1"] = "Detalle de materiales"
    ws4["A1"].font = _TITLE_FONT
    _header_row(ws4, 3, ["Material", "Cantidad", "Unidad", "Precio unit.", "Total"])
    r = 4
    for ln in sim["lines"]:
        ws4.cell(row=r, column=1, value=ln["material_name"])
        ws4.cell(row=r, column=2, value=round(ln["quantity"], 2))
        ws4.cell(row=r, column=3, value=ln["unit"])
        ws4.cell(row=r, column=4, value=round(ln["unit_cost"], 2)).number_format = _MONEY_FMT
        ws4.cell(row=r, column=5, value=round(ln["total"], 2)).number_format = _MONEY_FMT
        r += 1
    _autosize(ws4, [34, 12, 10, 16, 18])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
