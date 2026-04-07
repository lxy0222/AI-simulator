from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from langchain_openai import ChatOpenAI

from config import settings
from models import PatientInteractionState, PatientProfile

try:
    from deepagents import create_deep_agent
except ImportError:  # pragma: no cover - optional dependency
    create_deep_agent = None


logger = logging.getLogger(__name__)


SIMULATOR_SYSTEM_PROMPT_TEMPLATE = """你是一个专业的"模拟患者"演员，正在参与医疗 Agent 自动化测试。
你的任务是完全沉浸在患者角色中，与被测医疗 AI 进行自然中文对话。

## 患者固定档案
{patient_profile}

## 本轮测试场景
场景: {scenario}
初始状态: {initial_state}
边界条件: {boundary_conditions}
补充说明: {patient_notes}

## 你需要维护的患者认知
1. 你只能看到 AI 的最终回复文本，绝不能看到或引用思维链。
2. 你需要记住历史交互里是否出现过图片、卡片/小程序，以及工具调用带来的结果。
3. 如果 AI 发过图片、卡片或工具结果，你可以像真实患者一样提及它们，但不要伪造你没感知过的内容。

## 表达要求
1. 始终保持患者身份，绝不能暴露你是 AI 或测试工具。
2. 回复像真实微信聊天，通常 1-3 句话，允许犹豫、追问和情绪波动。
3. 根据 AI 的追问逐步透露信息，不要一次性把全部病史说完。
4. 如果 AI 没问到但你认为与场景强相关，可以少量补充。
5. 当 AI 已经完成解释、分诊或建议后，可以自然收束对话。
"""


OPENING_PROMPT = """现在请你发起第一句对话。
要求:
1. 根据固定档案、测试场景和初始状态开始。
2. 如果边界条件要求控制信息暴露，请只说最初愿意主动说出的内容。
3. 直接输出患者说的话，不要加前缀、引号或解释。"""


CONTINUE_PROMPT_TEMPLATE = """AI 刚刚给你的最终回复是:
"{final_reply}"

你当前能记住的额外上下文如下:
{interaction_context}

请继续扮演患者，自然回复。
直接输出患者说的话，不要加前缀、引号或解释。"""


class SimulatorAgent:
    """模拟患者智能体。"""

    def __init__(
        self,
        *,
        patient_profile: PatientProfile,
        scenario: str,
        initial_state: str,
        boundary_conditions: str,
        patient_notes: str = "",
    ):
        self.patient_profile = patient_profile
        self.system_prompt = SIMULATOR_SYSTEM_PROMPT_TEMPLATE.format(
            patient_profile=patient_profile.build_identity_profile_text(),
            scenario=scenario or "未指定",
            initial_state=initial_state or "患者刚进入对话，尚未说明全部情况。",
            boundary_conditions=boundary_conditions or "无额外边界条件。",
            patient_notes=patient_notes or "无",
        )

        self.messages: list[dict[str, str]] = []
        self.mock_mode = (
            not settings.OPENAI_API_KEY
            or settings.OPENAI_API_KEY == "sk-your-api-key-here"
        )

        self.deep_agent = None
        if not self.mock_mode and create_deep_agent is not None:
            self.deep_agent = self._build_deep_agent()

    def _build_deep_agent(self):
        model = ChatOpenAI(
            model="deepseek-v3.2",
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,
            temperature=0.8,
            max_tokens=256,
        )
        return create_deep_agent(
            model=model,
            system_prompt=self.system_prompt,
        )
    async def generate_opening(self) -> str:
        if self.mock_mode:
            return await self._mock_generate_opening()
        return await self._invoke_deep_agent(OPENING_PROMPT)

    async def generate_reply(
        self,
        final_reply_text: str,
        interaction_state: PatientInteractionState,
    ) -> str:
        if self.mock_mode:
            return await self._mock_generate_reply(final_reply_text, interaction_state)

        prompt = CONTINUE_PROMPT_TEMPLATE.format(
            final_reply=final_reply_text,
            interaction_context=interaction_state.to_prompt_text(),
        )
        return await self._invoke_deep_agent(prompt)

    async def _invoke_deep_agent(self, prompt: str) -> str:
        if self.deep_agent is None:
            raise RuntimeError(
                "当前环境未安装或无法加载 deepagents。"
                "请重新安装 backend/requirements.txt 中的依赖，或切换到 Mock 模式。"
            )

        self.messages.append({"role": "user", "content": prompt})
        try:
            result = await self.deep_agent.ainvoke({"messages": self.messages})
        except Exception as exc:
            error_detail = str(exc).strip() or repr(exc)
            logger.exception("Deep Agent 调用失败")
            raise RuntimeError(
                f"Deep Agent 调用失败（{type(exc).__name__}）: {error_detail}"
            ) from exc

        if not isinstance(result, dict):
            raise RuntimeError(f"Deep Agent 返回结果格式异常: {type(result).__name__}")

        reply = self._extract_reply(result.get("messages", []))
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def _extract_reply(self, messages: list[Any]) -> str:
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
        if isinstance(message, dict):
            return str(message.get("role", "")).lower()
        return str(getattr(message, "type", getattr(message, "role", ""))).lower()

    @staticmethod
    def _message_content(message: Any) -> str:
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
                elif isinstance(item, dict) and item.get("text"):
                    text_parts.append(str(item["text"]))
            return "\n".join(part.strip() for part in text_parts if part and part.strip())

        return str(content).strip()

    async def _mock_generate_opening(self) -> str:
        await asyncio.sleep(random.uniform(0.3, 0.9))
        complaint = self.patient_profile.chief_complaint or "身体不舒服"
        name = self.patient_profile.name
        options = [
            f"你好，我想咨询一下，{complaint}这个情况该怎么处理？",
            f"医生你好，我是{name}，最近{complaint}，想先问问看。",
            f"在吗？我这边主要是{complaint}，想看看下一步怎么办。",
        ]
        return random.choice(options)

    async def _mock_generate_reply(
        self,
        final_reply_text: str,
        interaction_state: PatientInteractionState,
    ) -> str:
        await asyncio.sleep(random.uniform(0.3, 0.9))

        symptoms = self.patient_profile.current_symptoms or ["不太舒服"]
        history = self.patient_profile.medical_history or ["之前看过一次"]

        if interaction_state.tool_calls:
            return f"我看你这边已经查了一些结果，那结合这个情况，{symptoms[0]}需要马上处理吗？"
        if "年龄" in final_reply_text or "几岁" in final_reply_text:
            age = self.patient_profile.age or "30多"
            return f"{age}岁，主要还是{symptoms[0]}比较明显。"
        if "多久" in final_reply_text or "持续" in final_reply_text:
            return "大概有一阵子了，最近这几天更明显。"
        if "有没有" in final_reply_text:
            return f"有的，除了{symptoms[0]}，还会有{symptoms[min(1, len(symptoms) - 1)]}。"
        if "之前" in final_reply_text or "看过" in final_reply_text:
            return f"{history[0]}，但效果一般，所以这次想换个思路看看。"
        return "好的，我明白了，那这种情况一般下一步建议怎么做？"
