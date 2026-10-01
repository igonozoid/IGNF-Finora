from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from finora.models.base import Base

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DATA_DIR.mkdir(exist_ok=True)
engine = create_engine(f"sqlite:///{DATA_DIR / 'finora.db'}", future=True)
Session = sessionmaker(engine)

def init_db():
    import finora.models  # noqa: registra modelos
    Base.metadata.create_all(engine)
