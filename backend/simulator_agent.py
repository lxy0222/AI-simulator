# ============================================
# Simulator Agent（模拟患者智能体）
# 使用 LangChain Deep Agents 构建的深度角色扮演 Agent
# 负责在对聊循环中扮演患者角色
# ============================================

import asyncio
import logging
import random
from typing import Any, List

from langchain_openai import ChatOpenAI

from config import settings
from deepagents import create_deep_agent

logger = logging.getLogger(__name__)


# --- 系统提示词模板 ---
SIMULATOR_SYSTEM_PROMPT_TEMPLATE = """你是一个专业的"模拟患者"演员，正在参与一个医疗导诊智能体的自动化测试。
你的任务是：完全沉浸在下面给定的患者画像和沟通风格中，与对面的"AI 客服智能体"进行自然的中文对话。

## 你的患者画像
{identity_profile}

## 你的沟通风格
{communication_style}

## 本次就诊场景
{scenario}

## 重要规则
1. 你必须始终保持角色扮演，绝不能暴露你是 AI 或测试工具。
2. 你的回复应该像真实患者一样自然，可以包含口语化表达、犹豫、追问等。
3. 每次回复保持简短自然（1-3句话为主），像真实的微信聊天。
4. 根据客服的引导逐步提供信息，不要一次性把所有症状都说完。
5. 如果客服问了你画像中没有的信息，你可以合理编造，但要与画像保持一致。
6. 到后面几轮如果客服已经给出了建议或推荐，你可以表示考虑/同意/还有疑问来结束对话。
7. 这是一个纯对话角色扮演任务，不要输出计划、不要解释思考过程、不要调用文件系统或其他工具，直接以患者身份自然回复。
"""

# --- 开场白生成提示词 ---
OPENING_PROMPT = """现在请你作为患者发起第一句对话。
根据你的画像和场景，用自然的语气开始问诊。
注意：这是你主动发起的第一句话，要符合你的沟通风格。

请直接输出患者说的话，不要加任何前缀、引号或标记。"""

# --- 继续对话提示词 ---
CONTINUE_PROMPT_TEMPLATE = """AI 客服刚刚回复了：

"{dify_response}"

请你继续扮演患者角色进行回复。根据客服的回复内容，自然地继续对话。
请直接输出患者说的话，不要加任何前缀、引号或标记。"""


class SimulatorAgent:
    """
    模拟患者智能体
    使用 LangChain Deep Agents 构建，支持深度角色扮演对话
    """

    def __init__(
        self,
        identity_profile: str,
        communication_style: str,
        scenario: str = "初诊",
    ):
        """
        初始化 Simulator Agent

        Args:
            identity_profile: 患者画像描述
            communication_style: 沟通风格描述
            scenario: 就诊场景（初诊/复诊）
        """
        self.identity_profile = identity_profile
        self.communication_style = communication_style
        self.scenario = scenario

        self.system_prompt = SIMULATOR_SYSTEM_PROMPT_TEMPLATE.format(
            identity_profile=identity_profile,
            communication_style=communication_style,
            scenario=scenario,
        )

        self.messages: List[dict[str, str]] = []

        # Mock 模式标识（当 LLM API 不可用时自动降级）
        self.mock_mode = (
            not settings.OPENAI_API_KEY
            or settings.OPENAI_API_KEY == "sk-your-api-key-here"
        )

        self.deep_agent = None
        if not self.mock_mode and create_deep_agent is not None:
            self.deep_agent = self._build_deep_agent()

    def _build_deep_agent(self):
        """构建 Deep Agent 实例。"""
        model = ChatOpenAI(
            model=settings.OPENAI_MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            temperature=0.85,
            max_tokens=256,
        )

        return create_deep_agent(
            model=model,
            system_prompt=self.system_prompt,
        )

    async def generate_opening(self) -> str:
        """
        生成患者的开场白（第一句话）

        Returns:
            str: 患者说的第一句话
        """
        if self.mock_mode:
            return await self._mock_generate_opening()

        return await self._invoke_deep_agent(OPENING_PROMPT)

    async def generate_reply(self, dify_response: str) -> str:
        """
        根据 Dify 客服的回复，生成患者的下一句话

        Args:
            dify_response: Dify 客服智能体的回复内容

        Returns:
            str: 患者的回复
        """
        if self.mock_mode:
            return await self._mock_generate_reply(dify_response)

        continue_prompt = CONTINUE_PROMPT_TEMPLATE.format(
            dify_response=dify_response,
        )
        return await self._invoke_deep_agent(continue_prompt)

    async def _invoke_deep_agent(self, prompt: str) -> str:
        """通过 Deep Agent 生成一轮患者回复。"""
        if self.deep_agent is None:
            raise RuntimeError(
                "当前环境未安装或无法加载 deepagents。"
                "请使用 Python 3.11+，并重新安装 backend/requirements.txt 中的依赖。"
            )

        self.messages.append({"role": "user", "content": prompt})
        try:
            result = await self.deep_agent.ainvoke({"messages": self.messages})
        except Exception as e:
            error_detail = str(e).strip() or repr(e)
            logger.exception("Deep Agent 调用失败")
            raise RuntimeError(
                f"Deep Agent 调用失败（{type(e).__name__}）: {error_detail}"
            ) from e

        if not isinstance(result, dict):
            raise RuntimeError(
                f"Deep Agent 返回结果格式异常: {type(result).__name__}"
            )

        reply = self._extract_reply(result.get("messages", []))
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def _extract_reply(self, messages: List[Any]) -> str:
        """从 Deep Agent 返回状态中提取最后一条 AI 文本消息。"""
        for message in reversed(messages):
            role = self._message_role(message)
            if role not in {"ai", "assistant"}:
                continue

            content = self._message_content(message)
            if content:
                return content.strip()

        raise RuntimeError("Deep Agent 未返回有效的患者回复。")

    @staticmethod
    def _message_role(message: Any) -> str:
        """兼容字典消息和 LangChain Message 对象。"""
        if isinstance(message, dict):
            return str(message.get("role", "")).lower()
        return str(getattr(message, "type", getattr(message, "role", ""))).lower()

    @staticmethod
    def _message_content(message: Any) -> str:
        """兼容不同 message content 结构，归一化为纯文本。"""
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                    continue

                if not isinstance(item, dict):
                    continue

                text = item.get("text")
                if text:
                    text_parts.append(str(text))

            return "\n".join(part.strip() for part in text_parts if part and part.strip())

        return str(content).strip()

    # ========================================
    # Mock 模式的方法（用于前后端联调）
    # ========================================

    async def _mock_generate_opening(self) -> str:
        """Mock: 生成模拟开场白"""
        await asyncio.sleep(random.uniform(0.5, 1.5))

        openings = [
            "你好，我想咨询一下小孩鼻炎的问题",
            "医生你好，我家孩子鼻子老是不通气，想问问怎么回事",
            "在吗？我想问一下关于鼻炎的事情",
            "你好，帮我看看孩子的鼻炎",
            "请问一下，小朋友鼻炎反复发作怎么办？",
        ]
        return random.choice(openings)

    async def _mock_generate_reply(self, dify_response: str) -> str:
        """Mock: 根据上下文生成模拟回复"""
        await asyncio.sleep(random.uniform(0.5, 1.5))

        replies = [
            "嗯嗯，是我女儿，今年6岁了",
            "大概有半年了吧，最近天气变化就更严重了",
            "之前去医院看过，开了一些喷鼻子的药，但是停了就又犯了",
            "就是鼻塞、流鼻涕，晚上睡觉还打呼噜",
            "好的，那我试试中医调理吧",
            "嗯，可以的，什么时候能预约呢？",
            "谢谢医生，那我先预约一下",
        ]
        return random.choice(replies)
