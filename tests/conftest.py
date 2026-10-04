import os

# 导入应用时会初始化 OpenAI 客户端；测试只使用占位密钥，不会发起真实请求。
os.environ.setdefault("OPENAI_API_KEY", "test-key")
