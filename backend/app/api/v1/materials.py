from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Material, MaterialYield, User
from app.schemas.material import (
    MaterialCreate,
    MaterialUpdate,
    MaterialRead,
    MaterialPriceUpdateRequest,
)

router = APIRouter(tags=["materials"])

APPLIES_TO_MAP = {
    "muro": "wall",
    "wall": "wall",
    "recinto piso": "room_floor",
    "room_floor": "room_floor",
    "recinto pared": "room_wall",
    "recinto paredes": "room_wall",
    "room_wall": "room_wall",
    "recinto perimetro": "room_perimeter",
    "recinto perímetro": "room_perimeter",
    "room_perimeter": "room_perimeter",
    "abertura area": "opening",
    "abertura área": "opening",
    "opening": "opening",
    "abertura perimetro": "opening_perimeter",
    "abertura perímetro": "opening_perimeter",
    "opening_perimeter": "opening_perimeter",
    "viga": "beam",
    "beam": "beam",
    "techo": "roof",
    "losa": "roof",
    "techo / losa": "roof",
    "roof": "roof",
    "columna": "column",
    "column": "column",
}

APPLIES_TO_REVERSE_MAP = {
    "wall": "Muro",
    "room_floor": "Recinto Piso",
    "room_wall": "Recinto Pared",
    "room_perimeter": "Recinto Perímetro",
    "opening": "Abertura Área",
    "opening_perimeter": "Abertura Perímetro",
    "beam": "Viga",
    "roof": "Techo / Losa",
    "column": "Columna",
}


@router.get("/", response_model=list[MaterialRead])
def list_materials(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Material]:
    stmt = select(Material).order_by(Material.name.asc())
    return list(db.scalars(stmt).all())


@router.post("/", response_model=MaterialRead, status_code=status.HTTP_201_CREATED)
def create_material(
    payload: MaterialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    # Check duplicate name
    stmt = select(Material).where(Material.name == payload.name)
    existing = db.scalar(stmt)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un material con el nombre '{payload.name}'."
        )

    material = Material(
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
    )
    db.add(material)
    db.flush()  # to get material.id

    for y_payload in payload.yields:
        db_yield = MaterialYield(
            material_id=material.id,
            applies_to=y_payload.applies_to,
            consumption=y_payload.consumption,
            waste_factor=y_payload.waste_factor,
            unit_price=y_payload.unit_price,
        )
        db.add(db_yield)

    db.commit()
    db.refresh(material)
    return material


@router.get("/{material_id}", response_model=MaterialRead)
def get_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    return material


@router.put("/{material_id}", response_model=MaterialRead)
def update_material(
    material_id: int,
    payload: MaterialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    if payload.name is not None:
        # Check duplicate name if changed
        if payload.name != material.name:
            stmt = select(Material).where(Material.name == payload.name)
            existing = db.scalar(stmt)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ya existe otro material con el nombre '{payload.name}'."
                )
        material.name = payload.name

    if payload.category is not None:
        material.category = payload.category
    if payload.unit is not None:
        material.unit = payload.unit

    if payload.yields is not None:
        # clear yields
        material.yields.clear()
        # insert new yields
        for y_payload in payload.yields:
            db_yield = MaterialYield(
                material_id=material.id,
                applies_to=y_payload.applies_to,
                consumption=y_payload.consumption,
                waste_factor=y_payload.waste_factor,
                unit_price=y_payload.unit_price,
            )
            db.add(db_yield)

    db.commit()
    db.refresh(material)
    return material


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    db.delete(material)
    db.commit()


@router.patch("/{material_id}/price", response_model=MaterialRead)
def update_material_price(
    material_id: int,
    payload: MaterialPriceUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    for y in material.yields:
        y.unit_price = payload.unit_price

    db.commit()
    db.refresh(material)
    return material


@router.get("/export/xlsx")
def export_materials_xlsx(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    stmt = select(Material).order_by(Material.name.asc())
    materials = db.scalars(stmt).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Materiales"

    # Header
    headers = [
        "Nombre del Material",
        "Categoría",
        "Unidad de Compra",
        "Aplica A",
        "Consumo",
        "Factor Desperdicio",
        "Precio Unitario",
    ]
    ws.append(headers)

    # Styles
    font_family = "Segoe UI"
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    data_font = Font(name=font_family, size=10)
    
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")  # slate-800
    
    thin_border = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )

    # Apply style to header
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center" if col_idx > 3 else "left", vertical="center")
        cell.border = thin_border

    # Data
    row_idx = 2
    for m in materials:
        if not m.yields:
            # Material without yields, write empty yields
            ws.append([m.name, m.category, m.unit, "", "", "", ""])
            row_idx += 1
        else:
            for y in m.yields:
                applies_friendly = APPLIES_TO_REVERSE_MAP.get(y.applies_to, y.applies_to)
                ws.append([
                    m.name,
                    m.category,
                    m.unit,
                    applies_friendly,
                    y.consumption,
                    y.waste_factor,
                    y.unit_price,
                ])
                row_idx += 1

    # Style data rows
    for r in range(2, row_idx):
        for c in range(1, 8):
            cell = ws.cell(row=r, column=c)
            cell.font = data_font
            cell.border = thin_border
            
            # Alignments & Formats
            if c in (1, 2):
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif c in (3, 4):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif c in (5, 6):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if c == 5:
                    cell.number_format = "0.00"
                else:
                    cell.number_format = "0.0%"
            elif c == 7:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "$#,##0.00"

    # Set column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if cell.number_format == "0.0%":
                try:
                    val_str = f"{float(cell.value)*100}%"
                except:
                    pass
            max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Return stream
    out = BytesIO()
    wb.save(out)
    out.seek(0)

    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=catalogo_materiales.xlsx"},
    )


@router.post("/import/excel")
async def import_materials_excel(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Formato de archivo inválido. Debe ser una planilla Excel (.xlsx o .xls)."
        )

    try:
        contents = await file.read()
        wb = load_workbook(filename=BytesIO(contents), data_only=True)
        ws = wb.active
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error al abrir la planilla Excel: {str(e)}"
        )

    # Read first row to validate headers
    first_row = [str(cell.value or "").strip() for cell in ws[1]]
    if len(first_row) < 7:
        raise HTTPException(
            status_code=400,
            detail="La planilla no tiene suficientes columnas. Se requieren al menos 7 columnas."
        )

    materials_data = {}  # name -> {category, unit, yields: []}

    for r_idx in range(2, ws.max_row + 1):
        row_cells = [ws.cell(row=r_idx, column=c_idx).value for c_idx in range(1, 8)]
        # Skip fully empty rows
        if not any(row_cells):
            continue

        name = str(row_cells[0] or "").strip()
        category = str(row_cells[1] or "").strip()
        unit = str(row_cells[2] or "").strip()
        applies_to_raw = str(row_cells[3] or "").strip()
        consumption_raw = row_cells[4]
        waste_raw = row_cells[5]
        price_raw = row_cells[6]

        if not name:
            raise HTTPException(
                status_code=400,
                detail=f"Fila {r_idx}: El Nombre del Material es obligatorio."
            )
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Fila {r_idx} ({name}): La Categoría es obligatoria."
            )
        if not unit:
            raise HTTPException(
                status_code=400,
                detail=f"Fila {r_idx} ({name}): La Unidad de Compra es obligatoria."
            )

        # Parse applies_to
        applies_to_clean = applies_to_raw.lower()
        if applies_to_clean not in APPLIES_TO_MAP:
            # If applies_to is empty, maybe it doesn't have yields (allowed)
            if not applies_to_raw:
                applies_to = None
            else:
                allowed_vals = ", ".join(set(APPLIES_TO_REVERSE_MAP.values()))
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Fila {r_idx} ({name}): 'Aplica A' con valor '{applies_to_raw}' no es válido. "
                        f"Valores permitidos: {allowed_vals}."
                    )
                )
        else:
            applies_to = APPLIES_TO_MAP[applies_to_clean]

        # Parse metrics
        try:
            consumption = float(consumption_raw) if consumption_raw is not None else 0.0
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Fila {r_idx} ({name}): 'Consumo' debe ser un número."
            )

        try:
            waste_factor = float(waste_raw) if waste_raw is not None else 0.0
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Fila {r_idx} ({name}): 'Factor Desperdicio' debe ser un número."
            )

        try:
            unit_price = float(price_raw) if price_raw is not None else 0.0
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Fila {r_idx} ({name}): 'Precio Unitario' debe ser un número."
            )

        if name not in materials_data:
            materials_data[name] = {
                "category": category,
                "unit": unit,
                "yields": [],
            }

        if applies_to:
            materials_data[name]["yields"].append({
                "applies_to": applies_to,
                "consumption": consumption,
                "waste_factor": waste_factor,
                "unit_price": unit_price,
            })

    # Perform Database Updates (Upsert)
    count = 0
    for name, m_info in materials_data.items():
        stmt = select(Material).where(Material.name == name)
        material = db.scalar(stmt)

        if material:
            # Update existing
            material.category = m_info["category"]
            material.unit = m_info["unit"]
            # Clear existing yields
            material.yields.clear()
        else:
            # Create new
            material = Material(
                name=name,
                category=m_info["category"],
                unit=m_info["unit"],
            )
            db.add(material)
            db.flush()  # to get ID

        # Add yields
        for y_info in m_info["yields"]:
            db_yield = MaterialYield(
                material_id=material.id,
                applies_to=y_info["applies_to"],
                consumption=y_info["consumption"],
                waste_factor=y_info["waste_factor"],
                unit_price=y_info["unit_price"],
            )
            db.add(db_yield)
        count += 1

    db.commit()
    return {"message": "Importación completada con éxito", "count": count}
