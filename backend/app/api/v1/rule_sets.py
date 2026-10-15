from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user, require_org_admin
from app.models.rule_set import Rule, RuleSet
from app.models.user import User
from app.schemas.rule_set import RuleSetCreate, RuleSetRead, RuleSetUpdate
from app.services import budget_rules as br

router = APIRouter(prefix="/rule-sets", tags=["rule-sets"])


def _org_id(user: User) -> int:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="Usuario sin organización")
    return user.organization_id


def _get(rule_set_id: int, user: User, db: Session) -> RuleSet:
    rs = db.scalar(
        select(RuleSet)
        .where(RuleSet.id == rule_set_id)
        .options(selectinload(RuleSet.rules))
    )
    if rs is None or rs.organization_id != _org_id(user):
        raise HTTPException(status_code=404, detail="Juego de reglas no encontrado")
    return rs


@router.get("/meta")
def rule_sets_meta(_: User = Depends(get_current_user)) -> dict:
    """Medidas, unidades y modos disponibles (para el editor)."""
    return {
        "measures": [{"key": k, "label": lbl, "unit": u} for k, (lbl, u) in br.MEASURES.items()],
        "units": list(br.UNITS),
        "modes": [
            {"key": "fixed", "label": "Medida × factor"},
            {"key": "brick_dims", "label": "Ladrillos por m² según medidas del proveedor"},
            {"key": "rebar", "label": "Hierro por diámetro (kg → barras)"},
        ],
    }


@router.get("", response_model=list[RuleSetRead])
def list_rule_sets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RuleSet]:
    rows = br.list_rule_sets(_org_id(user), db)
    db.commit()  # persiste el seed la primera vez
    return rows


@router.get("/{rule_set_id}", response_model=RuleSetRead)
def get_rule_set(
    rule_set_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleSet:
    return _get(rule_set_id, user, db)


@router.post("", response_model=RuleSetRead, status_code=status.HTTP_201_CREATED)
def create_rule_set(
    payload: RuleSetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
) -> RuleSet:
    org_id = _org_id(user)
    br.ensure_default_rule_set(org_id, db)
    if payload.copy_from_id is not None:
        rs = br.duplicate_rule_set(_get(payload.copy_from_id, user, db), payload.name, db)
        if payload.description is not None:
            rs.description = payload.description
    else:
        rs = RuleSet(organization_id=org_id, name=payload.name,
                     description=payload.description, is_default=False, rules=[])
        db.add(rs)
    db.commit()
    return _get(rs.id, user, db)


@router.put("/{rule_set_id}", response_model=RuleSetRead)
def update_rule_set(
    rule_set_id: int,
    payload: RuleSetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
) -> RuleSet:
    rs = _get(rule_set_id, user, db)
    rs.name = payload.name
    rs.description = payload.description
    if payload.is_default and not rs.is_default:
        for other in db.scalars(select(RuleSet).where(
                RuleSet.organization_id == rs.organization_id, RuleSet.id != rs.id)):
            other.is_default = False
        rs.is_default = True
    rs.rules = [Rule(position=i, **r.model_dump()) for i, r in enumerate(payload.rules)]
    db.commit()
    db.expire_all()
    return _get(rule_set_id, user, db)


@router.delete("/{rule_set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule_set(
    rule_set_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
) -> None:
    rs = _get(rule_set_id, user, db)
    others = list(db.scalars(select(RuleSet).where(
        RuleSet.organization_id == rs.organization_id, RuleSet.id != rs.id)
        .order_by(RuleSet.id)))
    if not others:
        raise HTTPException(status_code=400, detail="No se puede borrar el único juego de reglas.")
    if rs.is_default:
        others[0].is_default = True
    db.delete(rs)
    db.commit()
