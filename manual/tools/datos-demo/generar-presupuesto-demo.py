"""Genera el presupuesto de proveedor FICTICIO que usa el manual.

Corre dentro del contenedor backend del manual (tiene reportlab):
    docker compose -p scalist-manual exec -T backend python - < manual/tools/datos-demo/generar-presupuesto-demo.py
Escribe /app/storage/demo/presupuesto-corralon-demo.pdf (= manual/tools/datos-demo/storage/demo/).

Proveedor, CUIT, productos y precios son inventados. El layout imita un
presupuesto real de corralón (formato 1.234,56, precios con IVA, total al pie)
para que el lector lo procese igual que uno de verdad.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# (código, descripción, cantidad, precio unitario con IVA)
LINEAS = [
    ("10001", "LADRILLO CERAMICO PORTANTE 12X19X33 C/U", 1, 1180.00),
    ("10002", "LADRILLO CERAMICO PORTANTE 18X19X33 C/U", 1, 1650.00),
    ("20001", "CEMENTO PORTLAND CPC40 X 25 KG BOLSA", 1, 7350.00),
    ("20002", "CAL HIDRATADA X 25 KG BOLSA", 1, 5480.00),
    ("20003", "PEGAMENTO CERAMICO X 30 KG BOLSA", 1, 9200.00),
    ("30001", "ARENA GRUESA CAMION 6 M3", 1, 198000.00),
    ("30002", "ARENA FINA CAMION 6 M3", 1, 215000.00),
    ("30003", "PIEDRA PARTIDA 6/20 CAMION 6 M3", 1, 385000.00),
    ("40001", "LADRILLO DE LOSA CERAMICO 25X38 C/U", 1, 1420.00),
    ("50001", "HIERRO ADN 420 8 MM X 12 MTS", 1, 9850.00),
    ("50002", "HIERRO ADN 420 10 MM X 12 MTS", 1, 15400.00),
    ("50003", "HIERRO ADN 420 12 MM X 12 MTS", 1, 22100.00),
    ("50004", "ALAMBRE NEGRO RECOCIDO N 17 X 1 KG", 1, 4900.00),
]


def ar(n: float) -> str:
    s = f"{n:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> None:
    out = Path("/app/storage/demo/presupuesto-corralon-demo.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out), pagesize=A4)
    w, h = A4

    # Marca de agua debajo de la tabla: si cruza los renglones, el lector la
    # toma como parte de la descripción.
    c.saveState()
    c.setFont("Helvetica-Bold", 54)
    c.setFillGray(0.88)
    c.drawCentredString(w / 2, 280, "DOCUMENTO FICTICIO")
    c.restoreState()

    c.setFont("Helvetica-Bold", 14)
    c.drawString(36, 800, "CORRALON DEMO S.A.")
    c.setFont("Helvetica", 8)
    c.drawString(36, 786, "C.U.I.T. Nº: 30-00000001-0 · Av. Siempreviva 742 · Córdoba")
    c.drawString(36, 774, "ventas@corralon.demo")
    c.drawString(430, 800, "PRESUPUESTO Nº 0001-00000042")
    c.drawString(479, 786, "15/10/2026")

    y = 740
    c.setFont("Helvetica-Bold", 8)
    for x, t in [(28, "Código"), (79, "Artículo"), (404, "Cantidad"), (463, "P. Unitario"), (534, "P. Total")]:
        c.drawString(x, y, t)
    c.setFont("Helvetica", 8)
    total = 0.0
    for code, desc, qty, pu in LINEAS:
        y -= 15
        tot = qty * pu
        total += tot
        c.drawString(28, y, code)
        c.drawString(79, y, desc)
        c.drawString(425, y, ar(qty))
        c.drawString(461, y, "$")
        c.drawString(468, y, ar(pu))
        c.drawString(524, y, "$")
        c.drawString(532, y, ar(tot))
    y -= 25
    c.setFont("Helvetica-Bold", 8)
    c.drawString(340, y, "TOTAL CON I.V.A.:")
    c.drawString(470, y, f"$ {ar(total)}")
    c.setFont("Helvetica", 7)
    c.drawString(36, 60, "Precios con IVA incluido. Validez de la oferta: 7 días. Documento ficticio para el manual de ScalistAI.")
    c.save()
    print(out)


main()
