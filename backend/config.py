# ============================================
# AutoZenith 配置管理
# 管理所有环境变量和默认配置
# ============================================

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings:
    """应用配置类"""

    # ---- LLM (Simulator Agent) 配置 ----
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    OPENAI_MODEL_NAME: str = os.getenv("OPENAI_MODEL_NAME", "deepseek-chat")

    # ---- Dify API 配置 ----
    DIFY_API_BASE: str = os.getenv("DIFY_API_BASE", "https://your-dify-instance.com/v1")
    DIFY_API_KEY: str = os.getenv("DIFY_API_KEY", "")
    DIFY_CONNECT_TIMEOUT: float = float(os.getenv("DIFY_CONNECT_TIMEOUT", "10"))
    DIFY_READ_TIMEOUT: float = float(os.getenv("DIFY_READ_TIMEOUT", "300"))
    DIFY_WRITE_TIMEOUT: float = float(os.getenv("DIFY_WRITE_TIMEOUT", "30"))
    DIFY_POOL_TIMEOUT: float = float(os.getenv("DIFY_POOL_TIMEOUT", "30"))

    # ---- 应用配置 ----
    CORS_ORIGINS: list = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ---- Mock 模式 ----
    # 设为 True 时不会真正调用 Dify API，使用模拟返回进行调试
    MOCK_DIFY: bool = os.getenv("MOCK_DIFY", "true").lower() == "true"


settings = Settings()
