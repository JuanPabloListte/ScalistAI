"""Tests del lector de listas de precios (services/price_list_parse.py).

Sin DB, corre como script: python tests/test_price_list_parse.py

Los PDFs/Excel sintéticos replican el layout de dos proveedores reales
(formato 1,234.56 sin IVA y formato 1.234,56 con IVA). Si existen los
archivos reales en storage/fixtures/price_lists/ (gitignored: son
presupuestos de clientes) también se verifican contra ellos.
"""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent.parent / "storage" / "fixtures" / "price_lists"


def _pdf(rows: list[list[tuple[float, str]]], y0: float = 800, dy: float = 15) -> bytes:
    """Cada fila es una lista de (x, texto) dibujados a la misma altura."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 8)
    y = y0
    for row in rows:
        for x, text in row:
            c.drawString(x, y, text)
        y -= dy
    c.save()
    return buf.getvalue()


def _digimat_like() -> bytes:
    """Sin IVA, 1,234.56, código pegado a la descripción, IVA en el pie."""
    return _pdf([
        [(320, "ventas@digimat.com.ar")],
        [(400, "Fecha:"), (534, "30/09/2026")],
        [(16, "Cantidad"), (69, "Descripción"), (379, "P. Unitario"), (440, "Dto."), (561, "Total")],
        [(17, "2.00"), (66, "CVH00520-CEMENTO HOLCIM CPC30 - 25 KG, HOLCIM"),
         (387, "5,913.120"), (545, "11,826.240")],
        [(17, "1.00"), (66, "AVV00005-ARENA GRUESA CAMION 6M3, Varios"),
         (378, "159,814.049"), (536, "159,814.049")],
        [(17, "1.00"), (66, "HVS00003-HIERRO CONSTRUCCION DOBLADO 12 MTS - 8 MM,"),
         (387, "8,060.099"), (545, "8,060.099")],
        [(66, "Varios")],
        [(400, "Sub Total"), (520, "179,700.388")],
        [(400, "Iva 21%"), (520, "37,737.081")],
        [(400, "Total"), (520, "217,437.47")],
    ])


def _zarate_like() -> bytes:
    """Con IVA, 1.234,56, columna Código separada, '$' delante de precios."""
    return _pdf([
        [(36, "C.U.I.T. Nº: 30-70457852-7"), (479, "30/09/2026")],
        [(28, "Código"), (149, "Artículo"), (404, "Cantidad"), (463, "P. Unitario"), (534, "P. Total")],
        [(28, "209700"), (79, "LAD.CERAM.PORTANTE 12X19X33 PALMAR C/U"), (425, "10,00"),
         (461, "$"), (468, "1.102,460"), (524, "$"), (532, "11.024,60")],
        [(28, "202226"), (79, "HIERRO 8 C/U"), (425, "1,00"),
         (461, "$"), (468, "9.498,170"), (524, "$"), (532, "9.498,17")],
        [(28, "100004077"), (79, "CAL HIDRATADA BLANCALEY X 20 KG BOLSA"), (425, "1,00"),
         (461, "$"), (468, "5.089,330"), (524, "$"), (532, "5.089,33")],
        [(340, "TOTAL CON I.V.A.:"), (470, "$ 25.612,10")],
        [(36, "CASA CENTRAL: Tel: 0351-4778598 - 4778594"), (480, "HOJA: 1 de 2")],
    ])


def test_formato_sin_iva_punto_decimal():
    from app.services.price_list_parse import parse_price_list

    r = parse_price_list("p.pdf", _digimat_like())
    assert r["number_format"] == "1,234.56"
    assert r["iva"]["included"] is False, r["iva"]
    assert r["supplier"] == "Digimat"
    assert r["document_date"] == "2026-09-30"
    assert [ln["code"] for ln in r["lines"]] == ["CVH00520", "AVV00005", "HVS00003"]
    cem, arena, hierro = r["lines"]
    assert cem["quantity"] == 2.0 and cem["unit_price_net"] == 5913.12
    assert cem["presentation"]["amount"] == 25 and cem["presentation"]["unit"] == "kg"
    assert arena["presentation"] == {"amount": 6.0, "unit": "m3", "attrs": {}}
    # La continuación "Varios" se pega a la descripción del renglón anterior.
    assert hierro["description"].endswith("Varios"), hierro["description"]
    assert hierro["presentation"]["unit"] == "m" and hierro["presentation"]["amount"] == 12
    assert hierro["presentation"]["attrs"]["diameter_mm"] == 8
    assert r["totals"]["check"] == "ok"
    assert r["warnings"] == []


def test_formato_con_iva_coma_decimal():
    from app.services.price_list_parse import parse_price_list

    r = parse_price_list("p.pdf", _zarate_like())
    assert r["number_format"] == "1.234,56"
    assert r["iva"]["included"] is True, r["iva"]
    # El pie (teléfono, "HOJA 1 de 2") NO se lee como renglón.
    assert len(r["lines"]) == 3, [ln["description"] for ln in r["lines"]]
    lad, hierro, cal = r["lines"]
    assert lad["code"] == "209700" and lad["quantity"] == 10.0
    assert lad["unit_price_net"] == round(1102.46 / 1.21, 2)
    assert lad["presentation"]["attrs"]["dims"] == [12.0, 19.0, 33.0]
    assert hierro["presentation"]["attrs"]["diameter_mm"] == 8.0
    assert cal["presentation"]["amount"] == 20 and cal["presentation"]["unit"] == "kg"
    assert r["totals"]["check"] == "ok"


def test_iva_forzado_por_usuario():
    from app.services.price_list_parse import parse_price_list

    r = parse_price_list("p.pdf", _zarate_like(), iva_included=False)
    assert r["iva"]["included"] is False
    assert r["lines"][1]["unit_price_net"] == 9498.17


def test_excel_detecta_columnas_y_iva_en_encabezado():
    import openpyxl

    from app.services.price_list_parse import parse_price_list

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Lista de precios octubre"])
    ws.append([])
    ws.append(["ID_SISTEMA", "TIPO_ITEM", "ARTICULO_NOMBRE", "MEDIDA", "PRECIO_NETO_SIN_IVA"])
    ws.append(["SYS-99", "Estructura", "Hormigón Elaborado H25", "m3", 95000])
    ws.append(["SYS-310", "Pisos", "Pegamento Impermeable Flex", "bolsa 30kg", "12.000,50"])
    ws.append([None, None, None, None, None])
    buf = BytesIO()
    wb.save(buf)

    r = parse_price_list("lista.xlsx", buf.getvalue())
    assert r["iva"]["included"] is False and "encabezado" in r["iva"]["method"]
    assert [ln["description"] for ln in r["lines"]] == [
        "Hormigón Elaborado H25", "Pegamento Impermeable Flex"]
    hormigon, pegamento = r["lines"]
    # "H25" + unidad "m3" no debe leerse como 25 m3.
    assert hormigon["presentation"]["amount"] == 1 and hormigon["presentation"]["unit"] == "m3"
    assert pegamento["unit_price_net"] == 12000.5
    assert pegamento["presentation"]["amount"] == 30 and pegamento["presentation"]["unit"] == "kg"


def test_formato_no_soportado():
    from app.services.price_list_parse import parse_price_list

    try:
        parse_price_list("foto.jpg", b"...")
        raise AssertionError("debería rechazar .jpg")
    except ValueError:
        pass


def test_pdf_sin_tabla_avisa():
    from app.services.price_list_parse import parse_price_list

    r = parse_price_list("x.pdf", _pdf([[(40, "Hola, esto no es un presupuesto")]]))
    assert r["lines"] == []
    assert r["warnings"], "debería avisar que no encontró la tabla"


def _jpeg() -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    return buf.getvalue()


def _zip_sin_libro() -> bytes:
    import zipfile

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hola.txt", "no soy un Excel")
    return buf.getvalue()


def _rechaza(filename: str, data: bytes, fragmento: str) -> None:
    from app.services.price_list_parse import parse_price_list

    try:
        parse_price_list(filename, data)
    except ValueError as exc:
        assert fragmento in str(exc), (filename, str(exc))
        return
    raise AssertionError(f"{filename} debería rechazarse con ValueError")


def test_archivo_vacio_rechaza():
    for name in ("p.pdf", "p.xlsx", "p.csv"):
        _rechaza(name, b"", "El archivo está vacío.")
    _rechaza("p.csv", b"  \r\n \n", "El archivo está vacío.")


def test_archivo_danado_o_de_otro_tipo_rechaza():
    pdf_msg = "No se pudo leer el PDF: está dañado o no es un PDF."
    xlsx_msg = "No se pudo leer el Excel: está dañado o no es un .xlsx."
    _rechaza("foto.pdf", _jpeg(), pdf_msg)                 # imagen renombrada
    _rechaza("roto.pdf", b"%PDF-1.4 basura sin objetos", pdf_msg)
    _rechaza("roto.pdf", _digimat_like()[:300], pdf_msg)   # PDF cortado
    _rechaza("roto.xlsx", b"esto no es un zip", xlsx_msg)
    _rechaza("roto.xlsx", _zip_sin_libro(), xlsx_msg)
    _rechaza("foto.xlsx", _jpeg(), xlsx_msg)
    _rechaza("foto.csv", _jpeg() + b"\x00\x00", "No se pudo leer el CSV")


def test_csv_sin_columnas_de_precio_avisa():
    from app.services.price_list_parse import parse_price_list

    # Una sola columna (el Sniffer no encuentra separador): no revienta.
    r = parse_price_list("x.csv", b"hola\nesto no es\nun presupuesto\n")
    assert r["lines"] == [] and r["warnings"], r
    r = parse_price_list("x.csv", "nombre;color\nladrillo;rojo\n".encode())
    assert r["lines"] == [] and "encabezado" in r["warnings"][0], r["warnings"]
    # Encabezado bien pero sin precios válidos.
    r = parse_price_list("x.csv", "descripcion;precio\ncemento;consultar\n".encode())
    assert r["lines"] == [] and r["warnings"] == [
        "No se encontraron renglones con descripción y precio en el CSV."], r["warnings"]
    # Latin-1 (Excel en Windows) se lee sin caracteres rotos.
    r = parse_price_list("x.csv", "descripción;precio\nCaño ½;1.234,50\n".encode("cp1252"))
    assert r["lines"][0]["description"] == "Caño ½" and r["lines"][0]["unit_price"] == 1234.5


def test_aviso_de_totales_es_ar_y_sin_contradiccion():
    from app.services.price_list_parse import _money, parse_price_list

    assert _money(876530) == "$ 876.530,00"
    assert _money(1234567.891) == "$ 1.234.567,89"
    assert _money(-5.5) == "$ -5,50"

    # Zárate trae precios con IVA; forzado "sin IVA" el total del documento
    # (25.612,10) se compara contra la suma + 21% (30.990,64).
    r = parse_price_list("p.pdf", _zarate_like(), iva_included=False)
    assert r["totals"]["check"] == "mismatch"
    aviso = [w for w in r["warnings"] if "total del documento" in w]
    assert aviso == [
        "El total del documento ($ 25.612,10) no coincide con la suma de renglones más "
        "el 21% de IVA ($ 30.990,64). Revisá si los precios incluyen IVA o si faltan "
        "renglones."], r["warnings"]

    # Digimat es neto; forzado "con IVA" se compara contra la suma tal cual.
    r = parse_price_list("p.pdf", _digimat_like(), iva_included=True)
    aviso = [w for w in r["warnings"] if "total del documento" in w]
    assert aviso == [
        "El total del documento ($ 217.437,47) no coincide con la suma de renglones con "
        "IVA incluido ($ 179.700,39). Revisá si los precios incluyen IVA o si "
        "faltan renglones."], r["warnings"]


def test_fixtures_reales():
    """Presupuestos reales (si están en disco)."""
    from app.services.price_list_parse import parse_price_list

    expected = {
        "rptPresupuesto_SILICIO CONSTRU_013.pdf": (30, False, 769732.58),
        "Presupuesto 30-09-2026 15-48-13.pdf": (29, True, 226691.89),
    }
    for name, (n, iva, total) in expected.items():
        path = FIXTURES / name
        if not path.exists():
            print(f"        (sin fixture {name}, se omite)")
            continue
        r = parse_price_list(name, path.read_bytes())
        assert len(r["lines"]) == n, (name, len(r["lines"]))
        assert r["iva"]["included"] is iva, (name, r["iva"])
        assert abs(r["totals"]["lines_sum"] - total) < 0.02, (name, r["totals"])
        assert r["totals"]["check"] == "ok", (name, r["totals"])
        assert all(ln["unit_price_net"] and ln["unit_price_net"] > 0 for ln in r["lines"])


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
