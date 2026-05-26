"""
Run a backend smoke test for the chat memory flow.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import get_session_factory
from services.chat import ChatService


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    db = get_session_factory()()
    try:
        service = ChatService(db)
        first = service.chat_fast_path("我的名字是小明")
        conv_id = first["conversation_id"]
        second = service.chat_fast_path("我叫什么名字？", conv_id)
        assert conv_id == second["conversation_id"]
        assert any(token in second["response"] for token in ["小明", "你叫小明", "您的名字是小明"]), second["response"]
        print("memory smoke test passed")
        print(first["response"])
        print(second["response"])
    finally:
        db.close()


if __name__ == "__main__":
    main()
