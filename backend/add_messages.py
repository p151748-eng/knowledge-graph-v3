from sqlalchemy import text
from models.db import get_engine

e = get_engine()
with e.connect() as c:
    try:
        c.execute(text('ALTER TABLE conversations ADD COLUMN messages JSON NULL'))
        c.commit()
        print('messages column added to conversations')
    except Exception as ex:
        if 'Duplicate column' in str(ex) or 'already exists' in str(ex):
            print('messages column already exists')
        else:
            print(f'Error: {ex}')
