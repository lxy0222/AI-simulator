# ============================================
# Pydantic 数据模型
# 定义前后端交互的数据结构
# ============================================

from pydantic import BaseModel, Field
from typing import Optional


class SimulationConfig(BaseModel):
    """
    前端传入的模拟配置参数
    """
    # 就诊场景：初诊 / 复诊
    scenario: str = Field(default="初诊", description="就诊场景")

    # 患者画像描述
    identity_profile: str = Field(
        default="一位焦虑的母亲，带6岁女儿来看小儿鼻炎",
        description="患者画像"
    )

    # 沟通风格描述
    communication_style: str = Field(
        default="说话简短，有些着急，偶尔会追问",
        description="沟通风格"
    )

    # 最大对话轮数
    max_turns: int = Field(default=5, ge=1, le=20, description="最大对话轮数")


class ChatMessage(BaseModel):
    """
    单条聊天消息
    """
    role: str = Field(description="消息角色：simulator / dify")
    content: str = Field(description="消息内容")
    turn: int = Field(description="当前轮次")
