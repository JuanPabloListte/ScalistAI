import sys
from pathlib import Path

# Agregar backend al path para que funcionen los imports
sys.path.append(str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.plan import Plan
from app.models.detected_element import DetectedElement
from app.services.synthetic_generator import generate_synthetic_variations
import shutil

STORAGE_SYNTHETIC = Path("/app/storage/synthetic")

def regenerate():
    # 1. Borrar el dataset viejo con el mapeo viejo de clases
    if STORAGE_SYNTHETIC.exists():
        print(f"Borrando {STORAGE_SYNTHETIC}...")
        shutil.rmtree(STORAGE_SYNTHETIC)
    
    # 2. Generar uno nuevo
    with SessionLocal() as db:
        # Encontrar todas las combinaciones de plan_id y page que tienen elementos manuales
        query = db.query(DetectedElement.plan_id, DetectedElement.page).distinct()
        for plan_id, page in query:
            print(f"Generando sintéticos para plan_id={plan_id}, page={page}...")
            try:
                generate_synthetic_variations(plan_id, page, num_variations=50)
            except Exception as e:
                print(f"Error en plan_id={plan_id}, page={page}: {e}")

if __name__ == "__main__":
    regenerate()
    print("Regeneración terminada.")
