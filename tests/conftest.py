import os

# 导入应用时会初始化 OpenAI 客户端；测试只使用占位密钥，不会发起真实请求。
os.environ.setdefault("OPENAI_API_KEY", "test-key")
# 测试使用进程内 SQLite，避免写入本地 data/zenai.db。
os.environ["DATABASE_URL"] = "sqlite://"

import pytest

import database


@pytest.fixture(autouse=True)
def fresh_database():
    database.reset_database()
    yield
