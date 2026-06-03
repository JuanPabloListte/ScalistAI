import os
import sys
from pathlib import Path

# Agregar el directorio actual al path para importar app
sys.path.append(str(Path(__file__).parent))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models.project import Project
from app.models.plan import Plan
from app.models.detected_element import DetectedElement

database_url = "postgresql+psycopg://scalistai:scalistai_dev@postgres:5432/scalistai"
engine = create_engine(database_url)

with Session(engine) as session:
    print("--- PROYECTOS ---")
    projects = session.scalars(select(Project)).all()
    for p in projects:
        print(f"ID: {p.id}, Nombre: {p.name}, Status: {p.status}, Step: {p.wizard_step}")

    print("\n--- PLANOS ---")
    plans = session.scalars(select(Plan)).all()
    for plan in plans:
        print(f"Plan ID: {plan.id}, Proj ID: {plan.project_id}, File: {plan.original_filename}")
        print(f"  Page Count: {plan.page_count}, Status: {plan.status}")
        print(f"  Page Roles: {plan.page_roles}")
        print(f"  Page Scales: {plan.page_scales}")

        # Contar elementos por tipo
        for el_type in ["wall", "room", "opening"]:
            elements = session.execute(
                select(DetectedElement)
                .where(DetectedElement.plan_id == plan.id, DetectedElement.type == el_type)
            ).all()
            print(f"  Detected {el_type}s count: {len(elements)}")
            if len(elements) > 0:
                pages_found = sorted(list(set(el[0].page for el in elements)))
                print(f"    En páginas: {pages_found}")
