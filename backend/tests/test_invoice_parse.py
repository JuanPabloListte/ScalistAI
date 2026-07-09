"""Tests del parser de facturas (services/invoice_parse.py).

Genera PDFs sintéticos con texto de factura argentina y verifica la extracción
determinística de monto/fecha/CUIT/proveedor. Sin DB, corre como script:
    python tests/test_invoice_parse.py
"""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(40, y, ln)
        y -= 18
    c.save()
    return buf.getvalue()


def test_factura_electronica_ar():
    from app.services.invoice_parse import parse_invoice

    pdf = _pdf([
        "Ferretería Central SRL",
        "CUIT: 30-12345678-9",
        "Factura B N° 0001-00004567",
        "Fecha de emisión: 15/03/2026",
        "Cemento Loma Negra x50    10    18.500,00",
        "Hierro del 8            120     2.300,00",
        "Subtotal: 1.019.000,00",
        "IVA 21%: 214.000,00",
        "IMPORTE TOTAL: $ 1.234.567,89",
    ])
    r = parse_invoice(pdf)
    assert r["ok"] is True, r
    assert r["amount"] == 1234567.89, f"monto: {r['amount']}"
    assert r["date"] == "2026-03-15", f"fecha: {r['date']}"
    assert r["cuit"] == "30-12345678-9", f"cuit: {r['cuit']}"
    assert r["vendor"] == "Ferretería Central SRL", f"proveedor: {r['vendor']}"
    # ofrece candidatos por si el heurístico erró
    assert 1234567.89 in r["amount_candidates"]
    assert "2026-03-15" in r["date_candidates"]


def test_pdf_sin_texto_no_inventa():
    """Un PDF sin capa de texto (imagen) → ok=False, nunca fabrica un monto."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from app.services.invoice_parse import parse_invoice

    buf = BytesIO()
    canvas.Canvas(buf, pagesize=A4).save()  # PDF vacío, sin texto
    r = parse_invoice(buf.getvalue())
    assert r["ok"] is False and "amount" not in r


def test_total_preferido_sobre_maximo():
    """El monto etiquetado TOTAL gana aunque no sea el número más grande
    impreso (p. ej. un número de operación mayor)."""
    from app.services.invoice_parse import parse_invoice

    pdf = _pdf([
        "Corralón El Amigo",
        "Operación: 9.999.999",           # número grande que NO es plata (sin ,dd)
        "TOTAL: 45.800,00",
    ])
    r = parse_invoice(pdf)
    assert r["ok"] and r["amount"] == 45800.0, r["amount"]


def _image_pdf(lines: list[str]) -> bytes:
    """PDF que contiene la factura como IMAGEN (sin capa de texto): rasteriza un
    PDF de texto y re-embebe el PNG. Fuerza el camino OCR."""
    import fitz

    src = fitz.open(stream=_pdf(lines), filetype="pdf")
    pix = src.load_page(0).get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
    png = pix.tobytes("png")
    src.close()

    out = fitz.open()
    page = out.new_page(width=pix.width * 72 / 300, height=pix.height * 72 / 300)
    page.insert_image(page.rect, stream=png)
    data = out.tobytes()
    out.close()
    return data


def test_ocr_factura_escaneada():
    """Factura como imagen (sin texto) → se lee por OCR y se marca source=ocr.
    Se salta si tesseract no está instalado en el sistema."""
    import shutil

    from app.services.invoice_parse import parse_invoice

    if shutil.which("tesseract") is None:
        print("      (saltado: tesseract no instalado)")
        return

    pdf = _image_pdf([
        "Corralon Sur SA",
        "Fecha: 20/05/2026",
        "TOTAL: 532.100,00",
    ])
    # sanity: el PDF no tiene capa de texto
    import fitz
    d = fitz.open(stream=pdf, filetype="pdf")
    assert len("".join(p.get_text() for p in d).strip()) < 10
    d.close()

    r = parse_invoice(pdf)
    assert r["ok"] is True and r["source"] == "ocr", r
    # el OCR puede errar algún dígito; exigimos que haya extraído un monto y una
    # fecha plausibles (no que sean exactos).
    assert r["amount"] is not None and r["amount"] > 0, f"OCR no extrajo monto: {r}"
    assert r["date_candidates"], f"OCR no extrajo fecha: {r}"


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
