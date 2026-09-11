import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models import models as m

db = SessionLocal()
modulo = db.query(m.Modulo).filter(m.Modulo.clave == "proyectos").first()
if modulo:
    modulo.ruta = "/proyectos"
    db.commit()
    print(f"Corregido. Nueva ruta: {modulo.ruta}")
else:
    print("No se encontró el módulo 'proyectos'")
db.close()