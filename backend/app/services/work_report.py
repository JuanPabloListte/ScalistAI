"""Reporte ejecutivo de obra en PDF (Etapa 5).

Compone en un solo entregable lo que las Etapas 1-4 ya calculan —baseline,
avance físico, EVM ajustado por IPC y alertas anticipadas— con el formato de
marca del resto de la app. Pensado para imprimir/enviar al comitente: dice
dónde está la obra, cuánto se desvió (separando inflación de sobrecosto real)
y qué conviene mirar ya.

Función pura sobre dicts ya calculados (no toca la DB) → testeable con datos
sintéticos. El endpoint arma los dicts y hace el streaming.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_BRAND = colors.HexColor("#1B365D")
_MUTED = colors.HexColor("#666666")
_LINE = colors.HexColor("#E2E8F0")
_ZEBRA = colors.HexColor("#F8FAFC")

_SEVERITY_COLOR = {
    "alta": colors.HexColor("#C0392B"),
    "media": colors.HexColor("#E67E22"),
    "baja": colors.HexColor("#7F8C8D"),
}
_STATUS_COLOR = {
    "completa": colors.HexColor("#27AE60"),
    "en curso": colors.HexColor("#2980B9"),
    "atrasada": colors.HexColor("#C0392B"),
    "pendiente": colors.HexColor("#95A5A6"),
}
_SEVERITY_LABEL = {"alta": "ALTA", "media": "MEDIA", "baja": "BAJA"}
_ALERT_LABEL = {"retraso": "Retraso", "sobrecosto": "Sobrecosto",
                "pre_acopio": "Pre-acopio"}


def _fmt(n: float | None, prefix: str = "") -> str:
    """Formato argentino: miles con punto, decimales con coma."""
    if n is None:
        return "—"
    return f"{prefix}{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt0(n: float | None, prefix: str = "") -> str:
    if n is None:
        return "—"
    return f"{prefix}{n:,.0f}".replace(",", ".")


def _fmt_compact(n: float | None, prefix: str = "$") -> str:
    """Montos grandes en notación corta para que entren en las tarjetas KPI:
    -$11,0 M / $850 k / $420."""
    if n is None:
        return "—"
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1_000_000:
        val = f"{a / 1_000_000:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{sign}{prefix}{val} M"
    if a >= 1_000:
        return f"{sign}{prefix}{a / 1_000:,.0f} k".replace(",", ".")
    return f"{sign}{prefix}{a:,.0f}".replace(",", ".")


def _styles() -> dict:
    base = getSampleStyleSheet()

    def s(name, parent="Normal", **kw):
        return ParagraphStyle(name, parent=base[parent], **kw)

    return {
        "title": s("t", "Heading1", fontName="Helvetica-Bold", fontSize=20,
                   leading=24, textColor=_BRAND, spaceAfter=4),
        "sub": s("sub", fontName="Helvetica", fontSize=9.5, leading=13,
                 textColor=_MUTED, spaceAfter=16),
        "h2": s("h2", "Heading2", fontName="Helvetica-Bold", fontSize=12.5,
                leading=16, textColor=_BRAND, spaceBefore=14, spaceAfter=6),
        "body": s("b", fontName="Helvetica", fontSize=9, leading=12,
                  textColor=colors.HexColor("#333333")),
        "body_r": s("br", fontName="Helvetica", fontSize=9, leading=12,
                    textColor=colors.HexColor("#333333"), alignment=2),
        "hdr": s("h", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                 textColor=colors.white),
        "hdr_r": s("hr", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                   textColor=colors.white, alignment=2),
        "kpi_label": s("kl", fontName="Helvetica", fontSize=8, leading=10,
                       textColor=_MUTED),
        "kpi_value": s("kv", fontName="Helvetica-Bold", fontSize=15, leading=18,
                       textColor=_BRAND),
        "kpi_hint": s("kh", fontName="Helvetica", fontSize=7.5, leading=9,
                      textColor=_MUTED),
        "alert_t": s("at", fontName="Helvetica-Bold", fontSize=9, leading=12,
                     textColor=colors.HexColor("#222222")),
        "alert_d": s("ad", fontName="Helvetica", fontSize=8, leading=10.5,
                     textColor=_MUTED),
        "chip": s("chip", fontName="Helvetica-Bold", fontSize=7.5, leading=9,
                  textColor=colors.white, alignment=1),
    }


def _kpi_row(st: dict, totals: dict, evm: dict, inflation: dict | None) -> Table:
    """Fila de tarjetas KPI (avance, cronograma, costo, fin, desvío real)."""
    cpi = evm.get("cpi")
    spi = totals.get("spi")
    delay = totals.get("delay_days", 0)
    real_var = inflation.get("real_variance") if inflation else evm.get("cv")

    cards = [
        ("Avance físico", f"{totals.get('pct_fisico', 0)}%", "valor ganado / presupuesto"),
        ("Cronograma (SPI)", _fmt(spi) if spi is not None else "—",
         "≥1 en fecha" if spi is not None else "sin datos"),
        ("Costo (CPI)", _fmt(cpi) if cpi is not None else "—",
         "≥1 eficiente" if cpi is not None else "sin costos"),
        ("Fin proyectado", totals.get("projected_end", "—"),
         f"plan {totals.get('planned_end', '—')}" + (f" · +{delay}d" if delay else "")),
        ("Desvío real (s/IPC)", _fmt_compact(real_var) if real_var is not None else "—",
         "inflación aparte" if inflation else "nominal"),
    ]
    styles = _styles()
    data = [[
        Table([[Paragraph(lbl, styles["kpi_label"])],
               [Paragraph(val, styles["kpi_value"])],
               [Paragraph(hint, styles["kpi_hint"])]],
              style=TableStyle([
                  ("TOPPADDING", (0, 0), (-1, -1), 1),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                  ("LEFTPADDING", (0, 0), (-1, -1), 6),
                  ("RIGHTPADDING", (0, 0), (-1, -1), 6),
              ]))
        for (lbl, val, hint) in cards
    ]]
    t = Table(data, colWidths=[103] * 5)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _ZEBRA),
        ("BOX", (0, 0), (-1, -1), 0.5, _LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _table(header: list[str], rows: list[list], widths: list[float],
           aligns: list[int] | None = None) -> Table:
    """Tabla con encabezado de marca y zebra. `aligns`: 0=izq, 2=der por col."""
    styles = _styles()
    aligns = aligns or [0] * len(header)
    head = [Paragraph(h, styles["hdr_r"] if aligns[i] == 2 else styles["hdr"])
            for i, h in enumerate(header)]
    data = [head] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
    ]
    t.setStyle(TableStyle(style))
    return t


def build_work_report_pdf(project_name: str, plan: dict, progress: dict,
                          cost: dict, alerts: dict) -> bytes:
    """Arma el PDF ejecutivo. Todos los argumentos son dicts ya calculados:
    `plan`=serialize(WorkPlan), `progress`=plan_progress, `cost`=cost_summary,
    `alerts`=build_alerts. Devuelve los bytes del PDF."""
    styles = _styles()
    totals = progress.get("totals", {})
    evm = cost.get("evm", {})
    inflation = cost.get("inflation")
    assignee_by_id = {t["id"]: t.get("assignee_email") for t in plan.get("tasks", [])}

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=32, leftMargin=32,
                            topMargin=34, bottomMargin=32,
                            title=f"Reporte de obra — {project_name}")
    story: list = []

    # --- Encabezado ---
    status_es = {"active": "Baseline activo", "draft": "Borrador",
                 "superseded": "Reemplazado", "closed": "Cerrada"}.get(plan.get("status"), plan.get("status"))
    story.append(Paragraph("Reporte de obra", styles["title"]))
    story.append(Paragraph(
        f"<b>{project_name}</b> &nbsp;·&nbsp; Plan v{plan.get('version')} ({status_es}) "
        f"&nbsp;·&nbsp; Corte al {progress.get('as_of', datetime.now().date().isoformat())} "
        f"&nbsp;·&nbsp; Generado {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        styles["sub"]))

    # --- Resumen ejecutivo (KPIs) ---
    story.append(_kpi_row(plan, totals, evm, inflation))

    # --- Estado financiero (EVM + IPC) ---
    story.append(Paragraph("Estado financiero (valor ganado)", styles["h2"]))
    evm_rows = [[
        Paragraph("Presupuesto (BAC)", styles["body"]),
        Paragraph(_fmt(evm.get("bac"), "$"), styles["body_r"]),
        Paragraph("Valor ganado (EV)", styles["body"]),
        Paragraph(_fmt(evm.get("ev"), "$"), styles["body_r"]),
    ], [
        Paragraph("Costo real (AC)", styles["body"]),
        Paragraph(_fmt(evm.get("ac"), "$"), styles["body_r"]),
        Paragraph("Estimado al finalizar (EAC)", styles["body"]),
        Paragraph(_fmt(evm.get("eac"), "$"), styles["body_r"]),
    ], [
        Paragraph("Variación de costo (CV)", styles["body"]),
        Paragraph(_fmt(evm.get("cv"), "$"), styles["body_r"]),
        Paragraph("Sobre presupuesto proyectado", styles["body"]),
        Paragraph(_fmt(evm.get("over_budget_at_completion"), "$"), styles["body_r"]),
    ]]
    et = Table(evm_rows, colWidths=[150, 105, 165, 95])
    et.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (0, -1), _ZEBRA),
        ("BACKGROUND", (2, 0), (2, -1), _ZEBRA),
    ]))
    story.append(et)

    if inflation:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"<b>Ajuste por inflación (IPC INDEC):</b> el IPC acumuló "
            f"<b>{_fmt(inflation.get('accum_pct'))}%</b> desde el baseline "
            f"({inflation.get('ipc_base_date')} → {inflation.get('ipc_now_date')}). "
            f"De la diferencia contra lo gastado, {_fmt(inflation.get('inflation_gap'), '$')} "
            f"es atribuible a inflación y <b>{_fmt(inflation.get('real_variance'), '$')} "
            f"es desvío real</b> (tu gestión, no los precios).",
            styles["alert_d"]))
    else:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Ajuste por IPC no disponible (baseline reciente o sin serie INDEC cargada).",
            styles["alert_d"]))

    # --- Avance por etapa ---
    stages = progress.get("stages", [])
    if stages:
        story.append(Paragraph("Avance por etapa", styles["h2"]))
        rows = []
        for sgt in stages:
            delay = sgt.get("delay_days", 0)
            rows.append([
                Paragraph(sgt.get("stage", "—"), styles["body"]),
                Paragraph(f"{sgt.get('pct', 0)}%", styles["body_r"]),
                Paragraph(_fmt(sgt.get("cost_planned"), "$"), styles["body_r"]),
                Paragraph(str(sgt.get("n_tareas", 0)), styles["body_r"]),
                Paragraph(f"+{delay}d" if delay else "en fecha", styles["body_r"]),
            ])
        story.append(_table(
            ["Etapa", "Avance", "Presupuesto", "Tareas", "Atraso"],
            rows, [170, 70, 130, 65, 90], aligns=[0, 2, 2, 2, 2]))

    # --- Alertas ---
    alist = alerts.get("alerts", [])
    crit = alerts.get("critical_path", [])
    story.append(Paragraph("Alertas y anticipación", styles["h2"]))
    if crit:
        story.append(Paragraph(
            f"Camino crítico: <b>{len(crit)}</b> tareas encadenan la duración de obra "
            f"({alerts.get('project_duration', '—')} días). Un atraso en cualquiera "
            f"empuja la fecha final.", styles["alert_d"]))
        story.append(Spacer(1, 4))
    if not alist:
        story.append(Paragraph("Sin alertas: la obra está dentro de holgura y presupuesto.",
                               styles["body"]))
    else:
        rows = []
        for a in alist:
            sev = a.get("severity", "media")
            chip = Table([[Paragraph(_SEVERITY_LABEL.get(sev, sev.upper()), styles["chip"])]],
                         colWidths=[46], style=TableStyle([
                             ("BACKGROUND", (0, 0), (-1, -1), _SEVERITY_COLOR.get(sev, _MUTED)),
                             ("TOPPADDING", (0, 0), (-1, -1), 3),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                             ("ROUNDEDCORNERS", [3, 3, 3, 3]),
                         ]))
            body = Table([
                [Paragraph(f"[{_ALERT_LABEL.get(a.get('type'), a.get('type'))}] "
                           f"{a.get('title', '')}", styles["alert_t"])],
                [Paragraph(a.get("detail", ""), styles["alert_d"])],
            ], colWidths=[420], style=TableStyle([
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            rows.append([chip, body])
        at = Table(rows, colWidths=[54, 471])
        at.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LINE),
        ]))
        story.append(at)

    # --- Recalibración de rendimientos ---
    ys = alerts.get("yield_suggestions", [])
    if ys:
        story.append(Paragraph("Recalibración de rendimientos", styles["h2"]))
        story.append(Paragraph(
            "El rendimiento real observado difiere de la receta. Ajustá las recetas "
            "para planificar mejor la próxima obra:", styles["alert_d"]))
        story.append(Spacer(1, 4))
        rows = [[
            Paragraph(y.get("assembly", "—"), styles["body"]),
            Paragraph(_fmt(y.get("planned_yield")) + f" {y.get('unit','')}/d", styles["body_r"]),
            Paragraph(_fmt(y.get("real_yield")) + f" {y.get('unit','')}/d", styles["body_r"]),
            Paragraph(f"{'+' if (y.get('diff_pct') or 0) > 0 else ''}{y.get('diff_pct')}%",
                      styles["body_r"]),
        ] for y in ys]
        story.append(_table(["Receta", "Plan", "Real", "Desvío"],
                            rows, [230, 100, 100, 75], aligns=[0, 2, 2, 2]))

    # --- Detalle de tareas ---
    tasks = progress.get("tasks", [])
    if tasks:
        story.append(Paragraph("Detalle de tareas", styles["h2"]))
        rows = []
        for t in sorted(tasks, key=lambda x: (x.get("stage_order", 0), x.get("name", ""))):
            st = t.get("status", "pendiente")
            delay = t.get("delay_days", 0)
            resp = assignee_by_id.get(t.get("task_id")) or "—"
            resp = resp.split("@")[0] if resp != "—" else "—"
            rows.append([
                Paragraph(t.get("name", "—"), styles["body"]),
                Paragraph(t.get("stage", "—"), styles["body"]),
                Paragraph(f"<b>{st}</b>", ParagraphStyle(
                    "s", parent=styles["body"],
                    textColor=_STATUS_COLOR.get(st, _MUTED))),
                Paragraph(f"{t.get('pct', 0)}%", styles["body_r"]),
                Paragraph(resp, styles["body"]),
                Paragraph(t.get("projected_end", "—") + (f" (+{delay}d)" if delay else ""),
                          styles["body_r"]),
            ])
        story.append(_table(
            ["Tarea", "Etapa", "Estado", "%", "Responsable", "Fin proyectado"],
            rows, [150, 90, 70, 40, 85, 90], aligns=[0, 0, 0, 2, 0, 2]))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "Generado por ScalistAI · Métricas derivadas del baseline persistido y de "
        "registros reales de avance y costo (EVM ajustado por IPC INDEC).",
        styles["kpi_hint"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
