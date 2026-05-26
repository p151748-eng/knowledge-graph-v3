"""查看数据库表结构的诊断脚本"""
from sqlalchemy import text
from models.db import get_engine


def inspect():
    engine = get_engine()
    with engine.connect() as conn:
        for table in ["nodes", "edges", "documents", "conversations"]:
            try:
                result = conn.execute(text(f"DESCRIBE {table}"))
                cols = list(result)
                print(f"\n=== {table} ===")
                for row in cols:
                    print(f"  {row[0]}: {row[1]}")
            except Exception as e:
                print(f"{table}: {e}")


if __name__ == "__main__":
    inspect()
