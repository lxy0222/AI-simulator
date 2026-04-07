from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """应用配置类。"""

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    OPENAI_MODEL_NAME: str = os.getenv("OPENAI_MODEL_NAME", "deepseek-chat")
    EVALUATOR_MODEL_NAME: str = os.getenv("EVALUATOR_MODEL_NAME", OPENAI_MODEL_NAME)

    DIFY_API_BASE: str = os.getenv("DIFY_API_BASE", "https://your-dify-instance.com/v1")
    DIFY_API_KEY: str = os.getenv("DIFY_API_KEY", "")
    DIFY_CONNECT_TIMEOUT: float = float(os.getenv("DIFY_CONNECT_TIMEOUT", "10"))
    DIFY_READ_TIMEOUT: float = float(os.getenv("DIFY_READ_TIMEOUT", "300"))
    DIFY_WRITE_TIMEOUT: float = float(os.getenv("DIFY_WRITE_TIMEOUT", "30"))
    DIFY_POOL_TIMEOUT: float = float(os.getenv("DIFY_POOL_TIMEOUT", "30"))
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_API_BASE: str = os.getenv("DASHSCOPE_API_BASE", "https://api.dashscope.com/v1")

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATA_DIR: Path = BASE_DIR / "data"
    PATIENT_PROFILES_DIR: Path = DATA_DIR / "patient_profiles"
    AGENT_TEMPLATES_DIR: Path = DATA_DIR / "agent_templates"
    TEST_RUNS_DIR: Path = DATA_DIR / "test_runs"

    MOCK_DIFY: bool = os.getenv("MOCK_DIFY", "true").lower() == "true"
    ENABLE_LLM_EVALUATION: bool = os.getenv("ENABLE_LLM_EVALUATION", "true").lower() == "true"


settings = Settings()
