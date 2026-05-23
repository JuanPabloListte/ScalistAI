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
    """Detecta candidatos a Muros buscando parejas de líneas paralelas en el PDF (espesor de muro).

    Filtra trazos finos (como tramas y rayados) y líneas discontinuas (grillas/ejes)
    para garantizar una precisión óptima en los muros propuestos.
    """
    factor = dpi / 72.0
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        drawings = page.get_drawings()
    finally:
        doc.close()

    raw_lines = []
    for draw in drawings:
        w = draw.get("width")
        # Saltamos trazos finos (menores a 0.6pt, ej. tramas/mobiliario)
        if w is not None and w < 0.6:
            continue
        
        # Saltamos líneas de eje / discontinuas
        dashes = draw.get("dashes")
        if dashes and dashes != "[] 0":
            continue

        for item in draw.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                px1 = p1.x * factor
                py1 = p1.y * factor
                px2 = p2.x * factor
                py2 = p2.y * factor
                length_px = math.sqrt((px1 - px2)**2 + (py1 - py2)**2)
                length_m = length_px / scale
                
                # Filtro inicial de longitud física razonable
                if 0.5 <= length_m <= 25.0:
                    raw_lines.append((px1, py1, px2, py2, length_px))

    # Si hay muy pocos trazos vectoriales detectados (plano escaneado / foto),
    # hacemos el fallback a OpenCV para extraer las líneas físicas de la imagen
    if len(raw_lines) < 10:
        raw_lines = _extract_lines_from_image(pdf_path, page_index, dpi, scale)

    # --- Parejas Paralelas (Double-Line matching) ---
    # Convertimos espesores de muro típicos de metros a píxeles
    min_dist_px = 0.08 * scale
    max_dist_px = 0.35 * scale

    horizontal = []
    vertical = []
    for x1, y1, x2, y2, l_px in raw_lines:
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        if dx > dy * 3:
            if x1 > x2:
                x1, y1, x2, y2 = x2, y2, x1, y1
            horizontal.append((x1, y1, x2, y2, l_px))
        elif dy > dx * 3:
            if y1 > y2:
                x1, y1, x2, y2 = x2, y2, x1, y1
            vertical.append((x1, y1, x2, y2, l_px))

    parallel_walls = []
    matched_h = set()
    matched_v = set()

    # Emparejar horizontales
    for i, h1 in enumerate(horizontal):
        if i in matched_h:
            continue
        best_j = None
        best_dist = float('inf')
        for j, h2 in enumerate(horizontal):
            if i == j or j in matched_h:
                continue
            dist_y = abs(h1[1] - h2[1])
            if min_dist_px <= dist_y <= max_dist_px:
                # Comprobar solapamiento horizontal
                overlap = max(0, min(h1[2], h2[2]) - max(h1[0], h2[0]))
                min_len = min(h1[4], h2[4])
                if overlap > min_len * 0.5:
                    if dist_y < best_dist:
                        best_dist = dist_y
                        best_j = j
        if best_j is not None:
            matched_h.add(i)
            matched_h.add(best_j)
            h2 = horizontal[best_j]
            cx1 = (h1[0] + h2[0]) / 2.0
            cx2 = (h1[2] + h2[2]) / 2.0
            cy = (h1[1] + h2[1]) / 2.0
            length = cx2 - cx1
            parallel_walls.append((cx1, cy, cx2, cy, length, length / scale))

    # Emparejar verticales
    for i, v1 in enumerate(vertical):
        if i in matched_v:
            continue
        best_j = None
        best_dist = float('inf')
        for j, v2 in enumerate(vertical):
            if i == j or j in matched_v:
                continue
            dist_x = abs(v1[0] - v2[0])
            if min_dist_px <= dist_x <= max_dist_px:
                # Comprobar solapamiento vertical
                overlap = max(0, min(v1[3], v2[3]) - max(v1[1], v2[1]))
                min_len = min(v1[4], v2[4])
                if overlap > min_len * 0.5:
                    if dist_x < best_dist:
                        best_dist = dist_x
                        best_j = j
        if best_j is not None:
            matched_v.add(i)
            matched_v.add(best_j)
            v2 = vertical[best_j]
            cx = (v1[0] + v2[0]) / 2.0
            cy1 = (v1[1] + v2[1]) / 2.0
            cy2 = (v1[3] + v2[3]) / 2.0
            length = cy2 - cy1
            parallel_walls.append((cx, cy1, cx, cy2, length, length / scale))

    # Consolidación final de colineales
    merged_lines = _merge_collinear_lines(parallel_walls, tolerance_px=12, gap_px=25)

    if split_by_openings:
        from app.services.opening_detection import detect_opening_labels
        try:
            # Llamamos a detect_opening_labels desactivando align_to_walls para evitar recursión
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

                # Buscar intervalos de aberturas sobre este muro
                intervals = []
                for op in openings:
                    cx, cy = op["cx"], op["cy"]
                    t = ((cx - x1) * dx + (cy - y1) * dy) / line_len_sq
                    # Solo consideramos aberturas cuyo centro esté contenido dentro del segmento
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
        
        # Descartar fragmentos residuales cortísimos (< 60cm)
        if length_m < 0.6:
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


def detect_rooms(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None
) -> list[dict]:
    """Detecta candidatos a Recintos buscando etiquetas de texto en el plano PDF."""
    factor = dpi / 72.0
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        text_page = page.get_text("dict")
    finally:
        doc.close()

    candidates = []
    temp_idx = 1

    seen_texts = set()
    for block in text_page.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text or len(text) < 3 or text in seen_texts:
                    continue
                seen_texts.add(text)

                matched_key = None
                text_lower = text.lower()
                for key in ROOM_KEYWORDS:
                    if key in text_lower:
                        matched_key = key
                        break

                if matched_key:
                    display_name, w_m, h_m = ROOM_KEYWORDS[matched_key]
                    x0, y0, x1, y1 = span["bbox"]
                    cx = ((x0 + x1) / 2.0) * factor
                    cy = ((y0 + y1) / 2.0) * factor

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
                        "id": f"room_candidate_{temp_idx}",
                        "type": "room",
                        "geometry": {
                            "points": pts,
                            "label": text.upper(),
                        },
                        "length_m": None,
                        "area_m2": round(w_m * h_m, 2),
                        "height_m": 2.8,
                        "page": page_index + 1
                    })
                    temp_idx += 1

    # Check if page is raster/scanned (fewer than 10 vector drawings)
    # and no text elements were found.
    if len(candidates) == 0:
        is_scanned = False
        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(page_index)
            if len(page.get_drawings()) < 10:
                is_scanned = True
        finally:
            doc.close()

        if is_scanned:
            raise ValueError(
                "El plano parece ser una imagen escaneada. La detección automática de recintos requiere texto vectorial. Por favor, dibuja los recintos manualmente usando la herramienta Recinto (tecla P)."
            )

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
