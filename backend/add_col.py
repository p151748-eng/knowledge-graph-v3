from sqlalchemy import text
from models.db import get_engine

with get_engine().begin() as c:
    try:
        c.execute(text("ALTER TABLE conversations ADD COLUMN messages JSON"))
        print("messages column added")
    except Exception as e:
        print(f"Error: {e}")
