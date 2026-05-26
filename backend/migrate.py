"""数据库迁移脚本 - 补全所有缺失字段"""
from sqlalchemy import text
from models.db import get_engine

ALTER_STMTS = [
    ("documents", "source_url", "VARCHAR(512) NULL"),
    ("nodes", "confidence", "FLOAT DEFAULT 0.8"),
    ("edges", "source_doc_ids", "JSON NULL"),
]


def migrate():
    engine = get_engine()
    with engine.connect() as conn:
        for table, col, col_def in ALTER_STMTS:
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
                ))
                conn.commit()
                print(f"[OK] {table}.{col} added")
            except Exception as e:
                if "Duplicate column" in str(e):
                    print(f"[SKIP] {table}.{col} already exists")
                else:
                    print(f"[ERR] {table}.{col}: {e}")

    # 验证表结构
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE nodes"))
        cols = {row[0] for row in result}
        print(f"\n nodes 表字段: {sorted(cols)}")

        result = conn.execute(text("DESCRIBE edges"))
        cols = {row[0] for row in result}
        print(f" edges 表字段: {sorted(cols)}")

        result = conn.execute(text("DESCRIBE documents"))
        cols = {row[0] for row in result}
        print(f" documents 表字段: {sorted(cols)}")

    print("\n[迁移完成]")


if __name__ == "__main__":
    migrate()
