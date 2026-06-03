import json
from app.core.database import SessionLocal
from app.models.detected_element import DetectedElement

db = SessionLocal()
openings = db.query(DetectedElement).filter(DetectedElement.type == "opening").all()
subtypes = {}
for o in openings:
    geom = o.geometry or {}
    st = geom.get("subtype", "None")
    subtypes[st] = subtypes.get(st, 0) + 1

print("Total openings:", len(openings))
print("Subtypes:", json.dumps(subtypes, indent=2))
