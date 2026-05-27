import math
from pathlib import Path
import fitz

ROOM_KEYWORDS = {
    "baño": ("Baño", 2.0, 2.0),
    "toilette": ("Toilette", 1.8, 1.8),
    "vestidor": ("Vestidor", 2.0, 1.8),
    "lavadero": ("Lavadero", 2.0, 1.5),
    "cocina": ("Cocina", 4.0, 3.0),
    "comedor": ("Comedor", 4.5, 3.5),
    "estar": ("Estar", 4.0, 4.0),
    "living": ("Living", 5.0, 4.0),
    "playroom": ("Playroom", 4.0, 4.0),
    "cochera": ("Cochera", 5.0, 3.0),
    "dormitorio": ("Dormitorio", 3.5, 3.2),
    "dorm": ("Dormitorio", 3.5, 3.2),
    "suite": ("Suite", 4.0, 3.5),
    "estudio": ("Estudio", 3.0, 3.0),
    "oficina": ("Oficina", 3.0, 3.0),
    "paso": ("Paso", 2.0, 1.2),
    "hall": ("Hall", 2.0, 1.5),
    "balcon": ("Balcón", 3.5, 1.5),
    "terraza": ("Terraza", 4.0, 2.0),
    "patio": ("Patio", 4.0, 3.0),
}


def _extract_lines_from_image(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    scale: float
) -> list[tuple]:
    """Extrae líneas físicas de una página escaneada utilizando OpenCV."""
    import cv2
    import numpy as np

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        
        # Renderizar la página a pixmap
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        
        # Convertir el pixmap a array de numpy
        img_width = pixmap.width
        img_height = pixmap.height
        
        # pixmap.samples contiene los bytes RGB
        img_data = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape((img_height, img_width, 3))
        
        # Convertir a escala de grises
        gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
        
        # Binarización adaptativa para aislar trazos negros
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8
        )
        
        # Hough Line Transform Probabilística
        lines = cv2.HoughLinesP(
            thresh,
            rho=1,
            theta=np.pi / 180,
            threshold=50,
            minLineLength=int(0.3 * scale), # mínimo 30cm en píxeles
            maxLineGap=12
        )
        
        raw_lines = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                length_px = math.sqrt((x1 - x2)**2 + (y1 - y2)**2)
                raw_lines.append((float(x1), float(y1), float(x2), float(y2), length_px))
                
        return raw_lines
    finally:
        doc.close()


def detect_walls(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
    split_by_openings: bool = True
) -> list[dict]:
    """Detecta candidatos a Muros en el plano usando un enfoque morfológico unificado:
    1. Renderiza la página del PDF a imagen rasterizada.
    2. Binariza la imagen e identifica trazos oscuros con Otsu.
    3. Aplica apertura morfológica para remover trazos finos (cotas, grillas, texto).
    4. Sella pequeños huecos con cierre morfológico.
    5. Integra líneas vectoriales estructurales gruesas si están disponibles.
    6. Reduce los muros a una línea centerline de 1 píxel de espesor por esqueletización.
    7. Detecta segmentos de línea usando HoughLinesP.
    8. Normaliza a horizontal/vertical/diagonal.
    9. Combina segmentos colineales y corta según aberturas detectadas.
    """
    import cv2
    import numpy as np
    import math

    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
    factor = dpi / 72.0

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        
        # Renderizar la página a pixmap
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        
        img_width = pixmap.width
        img_height = pixmap.height
        img_data = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape((img_height, img_width, 3))
    finally:
        doc.close()

    # Convertir a escala de grises y binarizar
    gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Apertura morfológica para quitar elementos finos (cotas, textos, ejes)
    kernel_size = max(int(0.06 * scale), 3)
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    wall_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # Cierre morfológico para sellar pequeños huecos en los muros
    close_size = max(int(0.04 * scale), 3)
    if close_size % 2 == 0:
        close_size += 1
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size))
    wall_mask = cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE, close_kernel)

    # Mezclar con la máscara de líneas vectoriales gruesas del PDF si existen
    vector_mask = _render_pdf_vector_walls(pdf_path, page_index, dpi, min_stroke_pt=0.4)
    if vector_mask is not None:
        if vector_mask.shape != wall_mask.shape:
            vh, vw = wall_mask.shape
            vector_mask = cv2.resize(vector_mask, (vw, vh), interpolation=cv2.INTER_NEAREST)
        wall_mask = cv2.bitwise_or(wall_mask, vector_mask)

    # Esqueletización morfológica rápida y robusta
    img_skel = wall_mask.copy()
    skel = np.zeros(img_skel.shape, np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    size = np.size(img_skel)
    done = False
    while not done:
        eroded = cv2.erode(img_skel, element)
        temp = cv2.dilate(eroded, element)
        temp = cv2.subtract(img_skel, temp)
        skel = cv2.bitwise_or(skel, temp)
        img_skel = eroded.copy()
        zeros = size - cv2.countNonZero(img_skel)
        if zeros == size:
            done = True

    # Hough Line Transform sobre el esqueleto
    min_line_len = int(0.5 * scale)  # 50cm mínimo
    max_line_gap = int(0.25 * scale) # tolerancia a pequeños huecos
    lines = cv2.HoughLinesP(
        skel,
        rho=1,
        theta=np.pi / 180,
        threshold=20,
        minLineLength=min_line_len,
        maxLineGap=max_line_gap
    )

    raw_walls = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = math.hypot(x2 - x1, y2 - y1)
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            # Clasificar y enderezar
            if dx > dy * 3:
                # Horizontal
                y_avg = (y1 + y2) / 2.0
                x_min, x_max = min(x1, x2), max(x1, x2)
                raw_walls.append((float(x_min), float(y_avg), float(x_max), float(y_avg), x_max - x_min, (x_max - x_min) / scale))
            elif dy > dx * 3:
                # Vertical
                x_avg = (x1 + x2) / 2.0
                y_min, y_max = min(y1, y2), max(y1, y2)
                raw_walls.append((float(x_avg), float(y_min), float(x_avg), float(y_max), y_max - y_min, (y_max - y_min) / scale))
            else:
                # Diagonal
                raw_walls.append((float(x1), float(y1), float(x2), float(y2), length, length / scale))

    # Fusionar líneas colineales utilizando parámetros dinámicos basados en la escala
    tolerance_px = max(int(0.12 * scale), 8)
    gap_px = max(int(0.3 * scale), 15)
    merged_lines = _merge_collinear_lines(raw_walls, tolerance_px=tolerance_px, gap_px=gap_px)

    # Cortar muros por las aberturas si es necesario
    if split_by_openings:
        from app.services.opening_detection import detect_opening_labels
        try:
            # Llamamos a detect_opening_labels sin alinear a muros para evitar recursión
            openings = detect_opening_labels(pdf_path, page_index, dpi, px_per_m, align_to_walls=False)
        except Exception:
            openings = []

        if len(openings) > 0:
            split_lines = []
            max_dist_px = 1.5 * scale  # 1.5 metros máximo de distancia

            for line in merged_lines:
                x1, y1, x2, y2, l_px = line
                dx = x2 - x1
                dy = y2 - y1
                line_len_sq = dx * dx + dy * dy
                if line_len_sq == 0:
                    continue
                line_len = math.sqrt(line_len_sq)

                intervals = []
                for op in openings:
                    cx, cy = op["cx"], op["cy"]
                    t = ((cx - x1) * dx + (cy - y1) * dy) / line_len_sq
                    if 0.0 <= t <= 1.0:
                        proj_x = x1 + t * dx
                        proj_y = y1 + t * dy
                        dist = math.sqrt((cx - proj_x) ** 2 + (cy - proj_y) ** 2)
                        if dist <= max_dist_px:
                            w_px = op["default_width_m"] * scale
                            w_norm = w_px / line_len
                            t_start = max(0.0, t - w_norm / 2.0)
                            t_end = min(1.0, t + w_norm / 2.0)
                            intervals.append((t_start, t_end))

                if len(intervals) == 0:
                    split_lines.append(line)
                    continue

                # Recortar el segmento usando los intervalos
                wall_intervals = [(0.0, 1.0)]
                for t_s, t_e in intervals:
                    next_wall_intervals = []
                    for a, b in wall_intervals:
                        if a < t_e and b > t_s:
                            if a < t_s:
                                next_wall_intervals.append((a, t_s))
                            if b > t_e:
                                next_wall_intervals.append((t_e, b))
                        else:
                            next_wall_intervals.append((a, b))
                    wall_intervals = next_wall_intervals

                # Convertir los intervalos resultantes de vuelta a coordenadas físicas
                for a, b in wall_intervals:
                    sub_len_px = (b - a) * line_len
                    # Conservamos el muro si mide al menos 0.5 metros
                    if sub_len_px >= 0.5 * scale:
                        sub_x1 = x1 + a * dx
                        sub_y1 = y1 + a * dy
                        sub_x2 = x1 + b * dx
                        sub_y2 = y1 + b * dy
                        split_lines.append((sub_x1, sub_y1, sub_x2, sub_y2, sub_len_px))

            merged_lines = split_lines

    candidates = []
    temp_idx = 1
    for line in merged_lines:
        x1, y1, x2, y2, l_px = line
        length_m = l_px / scale
        
        # Descartar fragmentos residuales cortísimos (< 50cm)
        if length_m < 0.5:
            continue

        candidates.append({
            "id": f"wall_candidate_{temp_idx}",
            "type": "wall",
            "geometry": {
                "points": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                "label": f"Muro AI {temp_idx}",
            },
            "length_m": round(length_m, 2),
            "area_m2": None,
            "height_m": 2.8,
            "page": page_index + 1
        })
        temp_idx += 1

    return candidates


def _label_text_keyword(text: str) -> str | None:
    """Devuelve la keyword de ROOM_KEYWORDS que matchee el texto, o None."""
    text_lower = text.lower()
    for key in ROOM_KEYWORDS:
        if key in text_lower:
            return key
    return None


def _collect_room_labels(text_page: dict, factor: float) -> list[dict]:
    """Extrae etiquetas de texto que corresponden a recintos.
    Devuelve una lista de dicts con keys: text, matched_key, cx_px, cy_px, bbox_px.
    """
    labels = []
    seen = set()
    for block in text_page.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text or len(text) < 3 or text in seen:
                    continue
                seen.add(text)
                matched = _label_text_keyword(text)
                if not matched:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                labels.append({
                    "text": text,
                    "matched_key": matched,
                    "cx_px": (x0 + x1) / 2.0 * factor,
                    "cy_px": (y0 + y1) / 2.0 * factor,
                    "bbox_px": (x0 * factor, y0 * factor, x1 * factor, y1 * factor),
                })
    return labels


def _render_pdf_vector_walls(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    min_stroke_pt: float = 0.4,
) -> "np.ndarray | None":
    """Rasteriza directamente las líneas vectoriales del PDF que parecen
    estructurales (ancho >= min_stroke_pt, no discontinuas).

    Este es el enfoque más confiable cuando el PDF es vectorial: no inferimos
    los muros desde el raster, los pedimos directamente al PDF y los
    pintamos en una máscara binaria con el espesor de trazo correspondiente.
    """
    import cv2
    import numpy as np

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return None
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        w_px = int(round(page.rect.width * zoom)) + 1
        h_px = int(round(page.rect.height * zoom)) + 1
        mask = np.zeros((h_px, w_px), dtype=np.uint8)

        for draw in page.get_drawings():
            stroke_w = draw.get("width") or 0
            if stroke_w < min_stroke_pt:
                continue
            dashes = draw.get("dashes")
            if dashes and dashes != "[] 0":
                continue
            # Espesor pintado: proporcional al stroke real, con mínimo legible
            thickness = max(int(round(stroke_w * zoom * 1.4)), 2)

            for item in draw.get("items", []):
                kind = item[0]
                if kind == "l":
                    p1, p2 = item[1], item[2]
                    x1 = int(round(p1.x * zoom))
                    y1 = int(round(p1.y * zoom))
                    x2 = int(round(p2.x * zoom))
                    y2 = int(round(p2.y * zoom))
                    cv2.line(mask, (x1, y1), (x2, y2), 255, thickness, cv2.LINE_AA)
                elif kind == "re":
                    rect = item[1]
                    x0 = int(round(rect.x0 * zoom))
                    y0 = int(round(rect.y0 * zoom))
                    x1 = int(round(rect.x1 * zoom))
                    y1 = int(round(rect.y1 * zoom))
                    cv2.rectangle(mask, (x0, y0), (x1, y1), 255, thickness)
                elif kind == "qu":
                    # Quad (4 puntos). Lo pintamos como polilínea cerrada.
                    pts_obj = item[1]
                    pts = np.array(
                        [[int(round(p.x * zoom)), int(round(p.y * zoom))] for p in pts_obj],
                        dtype=np.int32,
                    )
                    if len(pts) >= 2:
                        cv2.polylines(mask, [pts], True, 255, thickness)
                elif kind == "c":
                    # Curva Bezier. Sampleamos varios puntos a lo largo.
                    p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                    samples = 12
                    prev = None
                    for s in range(samples + 1):
                        t = s / samples
                        omt = 1 - t
                        x = (omt ** 3) * p1.x + 3 * (omt ** 2) * t * p2.x + 3 * omt * (t ** 2) * p3.x + (t ** 3) * p4.x
                        y = (omt ** 3) * p1.y + 3 * (omt ** 2) * t * p2.y + 3 * omt * (t ** 2) * p3.y + (t ** 3) * p4.y
                        pt = (int(round(x * zoom)), int(round(y * zoom)))
                        if prev is not None:
                            cv2.line(mask, prev, pt, 255, thickness, cv2.LINE_AA)
                        prev = pt
        return mask
    finally:
        doc.close()


def _build_wall_mask(gray: "np.ndarray", scale: float) -> "np.ndarray":
    """Construye una máscara binaria con los muros del plano a partir del gray.
    Estrategia:
      1. Threshold inverso (oscuros -> blanco).
      2. Opening con kernels horizontales/verticales largos para mantener solo
         trazos estructurales (muros, no texto/cotas).
      3. Dilatación leve para cerrar huecos pequeños en los muros.
    """
    import cv2
    import numpy as np

    # Threshold con Otsu sobre el inverso — más robusto que un umbral fijo.
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Kernels largos: extraen solo líneas estructurales largas (muros).
    min_len_px = max(int(0.5 * scale), 25)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len_px, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len_px))
    h_lines = cv2.morphologyEx(dark, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(dark, cv2.MORPH_OPEN, v_kernel)
    structural = cv2.bitwise_or(h_lines, v_lines)

    # Sellar pequeños huecos para que recintos queden cerrados.
    seal_radius = max(int(0.05 * scale), 3)
    seal_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (seal_radius, seal_radius))
    sealed = cv2.dilate(structural, seal_kernel, iterations=2)
    sealed = cv2.morphologyEx(sealed, cv2.MORPH_CLOSE, seal_kernel)
    return sealed


def _filter_walls_by_structural_mask(
    walls: list[tuple],
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    scale: float,
    min_coverage: float = 0.55,
) -> list[tuple]:
    """Filtra candidatos a muro que no se apoyen sobre pixeles estructurales.

    Para cada muro, samplea puntos a lo largo del segmento y comprueba qué
    fracción cae sobre la máscara morfológica (dilatada para tolerar pequeño
    desplazamiento entre el trazo vectorial y el raster). Si la cobertura
    queda por debajo de `min_coverage`, el muro se descarta.

    Para PDFs vectoriales limpios este filtro casi no descarta nada; para
    planos ruidosos con cotas, tramas y hatching reduce el ruido.
    """
    import cv2
    import numpy as np

    if not walls:
        return walls

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return walls
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        img_w, img_h = pixmap.width, pixmap.height
        img_data = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(img_h, img_w, 3)
    finally:
        doc.close()

    gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
    mask = _build_wall_mask(gray, scale)
    # Dilatamos para tolerar desfases pequeños entre vector y raster.
    pad = max(int(0.04 * scale), 3)
    pad_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (pad, pad))
    mask = cv2.dilate(mask, pad_kernel, iterations=1)

    keep: list[tuple] = []
    for line in walls:
        x1, y1, x2, y2 = line[0], line[1], line[2], line[3]
        l_px = math.hypot(x2 - x1, y2 - y1)
        if l_px <= 0:
            continue
        n_samples = max(int(l_px / 4.0), 10)
        hits = 0
        for i in range(n_samples):
            t = i / max(n_samples - 1, 1)
            x = int(round(x1 + (x2 - x1) * t))
            y = int(round(y1 + (y2 - y1) * t))
            if 0 <= x < img_w and 0 <= y < img_h and mask[y, x] > 0:
                hits += 1
        if hits / n_samples >= min_coverage:
            keep.append(line)
    return keep


def _find_enclosed_regions(walls_mask: "np.ndarray"):
    """Dado el mask de muros, devuelve (labels, stats) de los componentes conexos
    de las regiones encerradas (no fondo exterior, no muros).
    """
    import cv2
    import numpy as np

    h, w = walls_mask.shape
    flood = walls_mask.copy()
    ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    # Marcamos el exterior con 128 desde las 4 esquinas.
    for cx, cy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if flood[cy, cx] == 0:
            cv2.floodFill(flood, ff_mask, (cx, cy), 128)
    enclosed = ((flood == 0)).astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(enclosed, connectivity=4)
    return num_labels, labels, stats


def _segment_rooms_watershed(
    walls_mask: "np.ndarray",
    room_labels: list[dict],
    scale: float,
) -> list[dict]:
    """Segmenta recintos usando cv2.watershed con cada label como semilla.

    A diferencia del enfoque de connected-components + flood-fill (donde el
    primer label que matchea un componente "se lo queda"), watershed da a
    cada semilla su propia región acotada por los muros. Los muros son la
    barrera; cada label crece hasta tocarla.

    Si los muros tienen pequeños huecos (por aberturas o trazos discontinuos),
    aplicamos un sellado morfológico previo.
    """
    import cv2
    import numpy as np

    h, w = walls_mask.shape

    # Sellado: cierra huecos de hasta ~0.1m
    seal = max(int(0.06 * scale), 5)
    seal_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (seal, seal))
    sealed = cv2.dilate(walls_mask, seal_kernel, iterations=1)
    sealed = cv2.morphologyEx(sealed, cv2.MORPH_CLOSE, seal_kernel)

    # Construcción de markers
    markers = np.zeros((h, w), dtype=np.int32)
    marker_to_label: dict[int, dict] = {}
    next_id = 2  # 0 = unknown, 1 = barrier

    for label in room_labels:
        cx = int(round(label["cx_px"]))
        cy = int(round(label["cy_px"]))
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        # Si el label cae sobre la pared, buscar un píxel libre cerca.
        if sealed[cy, cx] > 0:
            found = False
            for r in range(6, 80, 6):
                for ang_deg in range(0, 360, 20):
                    rad = math.radians(ang_deg)
                    qx = int(cx + math.cos(rad) * r)
                    qy = int(cy + math.sin(rad) * r)
                    if 0 <= qx < w and 0 <= qy < h and sealed[qy, qx] == 0:
                        cx, cy = qx, qy
                        found = True
                        break
                if found:
                    break
            if not found:
                continue

        # Marker como pequeño círculo (más robusto que un solo pixel)
        cv2.circle(markers, (cx, cy), 6, next_id, -1)
        marker_to_label[next_id] = label
        next_id += 1

    if not marker_to_label:
        return []

    # Los muros son la barrera (== 1)
    markers[sealed > 0] = 1

    # cv2.watershed requiere imagen 3-canal
    img_3ch = cv2.cvtColor(sealed, cv2.COLOR_GRAY2BGR)
    cv2.watershed(img_3ch, markers)

    # Extraer polígono de cada recinto
    out: list[dict] = []
    for marker_id, label in marker_to_label.items():
        region = (markers == marker_id).astype(np.uint8) * 255
        area_px = int(region.sum() // 255)
        area_m2 = area_px / (scale * scale)
        # Filtro de sanidad
        if area_m2 < 0.8 or area_m2 > 400:
            continue
        contours, _ = cv2.findContours(
            region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        perim = cv2.arcLength(contour, True)
        # Aprox poligonal: epsilon proporcional al perímetro
        eps = max(0.005 * perim, 3.0)
        approx = cv2.approxPolyDP(contour, eps, True)
        if len(approx) < 3:
            continue
        if len(approx) > 28:
            eps = 0.014 * perim
            approx = cv2.approxPolyDP(contour, eps, True)
        out.append({
            "label": label,
            "contour": approx,
            "area_m2": area_m2,
        })
    return out


def _find_component_for_label(
    labels: "np.ndarray",
    tx: int,
    ty: int,
    img_w: int,
    img_h: int,
    matched_components: set[int],
) -> int | None:
    """Busca el componente conexo que contiene el centro del label.
    Si el centro cae sobre un muro o el exterior, hace una búsqueda radial
    hasta 40px para encontrar el componente más cercano."""
    if not (0 <= tx < img_w and 0 <= ty < img_h):
        return None
    cid = int(labels[ty, tx])
    if cid != 0 and cid not in matched_components:
        return cid
    # Búsqueda radial — para handles donde el label cae sobre la pared o cerca.
    for radius in range(4, 42, 4):
        for angle_step in range(0, 360, 30):
            rad = math.radians(angle_step)
            qx = int(tx + math.cos(rad) * radius)
            qy = int(ty + math.sin(rad) * radius)
            if 0 <= qx < img_w and 0 <= qy < img_h:
                c = int(labels[qy, qx])
                if c != 0 and c not in matched_components:
                    return c
    return None


def _contour_to_points(contour, factor_x: float = 1.0, factor_y: float = 1.0) -> list[float]:
    """Convierte un contorno OpenCV en una lista plana [x1,y1,x2,y2,...]"""
    pts: list[float] = []
    for pt in contour:
        pts.append(round(float(pt[0][0]) * factor_x, 2))
        pts.append(round(float(pt[0][1]) * factor_y, 2))
    return pts


def _detect_rooms_text_fallback(
    text_page: dict, factor: float, scale: float, page_index: int
) -> list[dict]:
    """Fallback: rectángulo fijo alrededor de cada label (comportamiento legacy).
    Sólo se usa cuando la detección por componentes conexos no devuelve nada."""
    candidates = []
    idx = 1
    for label in _collect_room_labels(text_page, factor):
        _, w_m, h_m = ROOM_KEYWORDS[label["matched_key"]]
        cx, cy = label["cx_px"], label["cy_px"]
        w_px = w_m * scale
        h_px = h_m * scale
        pts = [
            cx - w_px / 2.0, cy - h_px / 2.0,
            cx + w_px / 2.0, cy - h_px / 2.0,
            cx + w_px / 2.0, cy + h_px / 2.0,
            cx - w_px / 2.0, cy + h_px / 2.0,
        ]
        pts = [round(p, 2) for p in pts]
        candidates.append({
            "id": f"room_candidate_{idx}",
            "type": "room",
            "geometry": {"points": pts, "label": label["text"].upper()},
            "length_m": None,
            "area_m2": round(w_m * h_m, 2),
            "height_m": 2.8,
            "page": page_index + 1,
        })
        idx += 1
    return candidates


def detect_rooms(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
) -> list[dict]:
    """Detecta candidatos a Recintos con un enfoque vector-first + watershed.

    Pipeline (nuevo, abandonando flood-fill + connected components):

      1. Extrae las etiquetas de texto (COCINA, BAÑO, ...) del PDF.
      2. Construye una **máscara completa de muros** combinando:
           a) Líneas vectoriales del PDF (ancho >= 0.4pt, no discontinuas).
           b) Morfología sobre el raster (atrapa muros rellenos y artefactos
              que falten en los vectores).
         La unión `OR` de ambas suele cubrir todos los muros reales del plano.
      3. Aplica **watershed** con cada label como semilla independiente. Los
         muros actúan de barrera. Cada label crece a su propia región acotada
         por las paredes que la rodean — no hay competencia entre labels por
         un mismo "componente conexo" como en el enfoque anterior.
      4. De cada región resultante extrae el contorno con `findContours` y
         lo simplifica con `approxPolyDP`.
      5. Si el watershed no encuentra recintos válidos (plano con muros muy
         rotos), cae al fallback legacy (rectángulo alrededor del label).
    """
    import cv2
    import numpy as np

    factor = dpi / 72.0
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        img_w, img_h = pixmap.width, pixmap.height
        img_data = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(img_h, img_w, 3)
        text_page = page.get_text("dict")
        has_drawings = len(page.get_drawings()) > 10
    finally:
        doc.close()

    room_labels = _collect_room_labels(text_page, factor)

    if not room_labels:
        if not has_drawings:
            raise ValueError(
                "El plano parece ser una imagen escaneada sin texto vectorial. "
                "La detección automática de recintos necesita texto. Dibujá los "
                "recintos manualmente con la herramienta Recinto (tecla P)."
            )
        return []

    # --- Máscara combinada de muros ---
    gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
    raster_mask = _build_wall_mask(gray, scale)
    vector_mask = _render_pdf_vector_walls(pdf_path, page_index, dpi, min_stroke_pt=0.4)
    if vector_mask is not None:
        # Igualar tamaño por si difieren en 1 pixel
        if vector_mask.shape != raster_mask.shape:
            vh, vw = raster_mask.shape
            vector_mask = cv2.resize(vector_mask, (vw, vh), interpolation=cv2.INTER_NEAREST)
        walls_mask = cv2.bitwise_or(raster_mask, vector_mask)
    else:
        walls_mask = raster_mask

    # --- Watershed con labels como semillas ---
    regions = _segment_rooms_watershed(walls_mask, room_labels, scale)

    candidates: list[dict] = []
    for idx, region in enumerate(regions, start=1):
        label = region["label"]
        approx = region["contour"]
        candidates.append({
            "id": f"room_candidate_{idx}",
            "type": "room",
            "geometry": {
                "points": _contour_to_points(approx),
                "label": label["text"].upper(),
            },
            "length_m": None,
            "area_m2": round(region["area_m2"], 2),
            "height_m": 2.8,
            "page": page_index + 1,
        })

    # Si nada salió bien — fallback al rectángulo fijo (mejor algo que nada).
    if not candidates:
        return _detect_rooms_text_fallback(text_page, factor, scale, page_index)

    return candidates


def _merge_collinear_lines(lines, tolerance_px=12, gap_px=25):
    """Agrupa y combina segmentos de línea colineales cercanos para evitar redundancia de CAD."""
    horizontal = []
    vertical = []
    other = []

    for x1, y1, x2, y2, _, l_m in lines:
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        if dx > dy * 3:
            if x1 > x2:
                x1, y1, x2, y2 = x2, y2, x1, y1
            horizontal.append((x1, y1, x2, y2, l_m))
        elif dy > dx * 3:
            if y1 > y2:
                x1, y1, x2, y2 = x2, y2, x1, y1
            vertical.append((x1, y1, x2, y2, l_m))
        else:
            other.append((x1, y1, x2, y2, l_m))

    merged = []

    # Combinar horizontales
    horizontal.sort(key=lambda item: item[1])
    h_groups = []
    for h in horizontal:
        added = False
        for g in h_groups:
            avg_y = sum(item[1] for item in g) / len(g)
            if abs(h[1] - avg_y) <= tolerance_px:
                g.append(h)
                added = True
                break
        if not added:
            h_groups.append([h])

    for g in h_groups:
        g.sort(key=lambda item: item[0])
        curr = list(g[0])
        for next_line in g[1:]:
            if next_line[0] <= curr[2] + gap_px:
                curr[2] = max(curr[2], next_line[2])
                curr[1] = (curr[1] + next_line[1]) / 2.0
                curr[3] = (curr[3] + next_line[3]) / 2.0
            else:
                merged.append(curr)
                curr = list(next_line)
        merged.append(curr)

    # Combinar verticales
    vertical.sort(key=lambda item: item[0])
    v_groups = []
    for v in vertical:
        added = False
        for g in v_groups:
            avg_x = sum(item[0] for item in g) / len(g)
            if abs(v[0] - avg_x) <= tolerance_px:
                g.append(v)
                added = True
                break
        if not added:
            v_groups.append([v])

    for g in v_groups:
        g.sort(key=lambda item: item[1])
        curr = list(g[0])
        for next_line in g[1:]:
            if next_line[1] <= curr[3] + gap_px:
                curr[3] = max(curr[3], next_line[3])
                curr[0] = (curr[0] + next_line[0]) / 2.0
                curr[2] = (curr[2] + next_line[2]) / 2.0
            else:
                merged.append(curr)
                curr = list(next_line)
        merged.append(curr)

    for o in other:
        merged.append(list(o))

    final_lines = []
    for line in merged:
        x1, y1, x2, y2 = line[0], line[1], line[2], line[3]
        dx = x2 - x1
        dy = y2 - y1
        length_px = math.sqrt(dx*dx + dy*dy)
        final_lines.append((x1, y1, x2, y2, length_px))

    return final_lines
