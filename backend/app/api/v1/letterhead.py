"""Membrete del estudio: logo y datos de contacto que encabezan el presupuesto en PDF."""
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_org_admin
from app.core.uploads import read_upload
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/organization/letterhead", tags=["letterhead"])

MAX_LOGO_BYTES = 2 * 1024 * 1024
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg"}


class LetterheadRead(BaseModel):
    name: str
    contact_info: str | None
    has_logo: bool


class LetterheadUpdate(BaseModel):
    contact_info: str | None = Field(default=None, max_length=600)


def _org(user: User, db: Session) -> Organization:
    org = db.get(Organization, user.organization_id) if user.organization_id else None
    if org is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    return org


def logo_file(org: Organization) -> Path | None:
    if not org.logo_path:
        return None
    p = Path(org.logo_path)
    return p if p.exists() else None


def _read(org: Organization) -> LetterheadRead:
    return LetterheadRead(name=org.name, contact_info=org.contact_info,
                          has_logo=logo_file(org) is not None)


@router.get("", response_model=LetterheadRead)
def get_letterhead(db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> LetterheadRead:
    return _read(_org(user, db))


@router.put("", response_model=LetterheadRead)
def update_letterhead(payload: LetterheadUpdate, db: Session = Depends(get_db),
                      user: User = Depends(require_org_admin)) -> LetterheadRead:
    org = _org(user, db)
    org.contact_info = (payload.contact_info or "").strip() or None
    db.commit()
    return _read(org)


@router.get("/logo")
def get_logo(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    path = logo_file(_org(user, db))
    if path is None:
        raise HTTPException(status_code=404, detail="La organización no tiene logo")
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return Response(content=path.read_bytes(), media_type=media,
                    headers={"Cache-Control": "no-store"})


@router.put("/logo", response_model=LetterheadRead)
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require_org_admin)) -> LetterheadRead:
    from PIL import Image, UnidentifiedImageError

    data = await read_upload(file, MAX_LOGO_BYTES)
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Subí el logo en PNG o JPG.") from exc
    if fmt not in _MIME:
        raise HTTPException(status_code=400, detail="Subí el logo en PNG o JPG.")
    org = _org(user, db)
    folder = Path(settings.STORAGE_DIR) / "logos"
    folder.mkdir(parents=True, exist_ok=True)
    new = folder / f"org_{org.id}_{uuid.uuid4().hex[:8]}.{'png' if fmt == 'PNG' else 'jpg'}"
    new.write_bytes(data)
    old = logo_file(org)
    org.logo_path = str(new)
    db.commit()
    if old is not None and old != new:
        old.unlink(missing_ok=True)
    return _read(org)


@router.delete("/logo", response_model=LetterheadRead)
def delete_logo(db: Session = Depends(get_db),
                user: User = Depends(require_org_admin)) -> LetterheadRead:
    org = _org(user, db)
    old = logo_file(org)
    org.logo_path = None
    db.commit()
    if old is not None:
        old.unlink(missing_ok=True)
    return _read(org)
