from __future__ import annotations

import json
import logging
from statistics import mean

from langchain_openai import ChatOpenAI

from config import settings
from models import EvaluationDimensionScore, EvaluationReport, SimulationRunRecord

logger = logging.getLogger(__name__)


class ConversationEvaluator:
    """单轮测试结束后的结构化评估器。"""

    def __init__(self):
        self.enabled = settings.ENABLE_LLM_EVALUATION
        self.has_llm = bool(settings.OPENAI_API_KEY) and settings.OPENAI_API_KEY != "sk-your-api-key-here"

    async def evaluate(self, run_record: SimulationRunRecord) -> EvaluationReport:
        if self.enabled and self.has_llm:
            try:
                return await self._evaluate_with_llm(run_record)
            except Exception:
                logger.exception("LLM 评估失败，回退到启发式评估")

        return self._heuristic_evaluation(run_record)

    async def _evaluate_with_llm(self, run_record: SimulationRunRecord) -> EvaluationReport:
        model = ChatOpenAI(
            model=settings.EVALUATOR_MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            temperature=0.2,
            max_tokens=1200,
        )

        transcript = []
        for message in run_record.messages:
            if message.role not in {"simulator", "dify"}:
                continue
            speaker = "患者" if message.role == "simulator" else run_record.agent_template.name
            transcript.append(f"[第{message.turn}轮][{speaker}] {message.content}")

        tool_summary = [item.summary for item in run_record.patient_state.tool_calls[-10:]]
        prompt = f"""
你是一名医疗 AI 测试评审官，请根据以下测试信息输出 JSON。

要求:
1. 只评估最终回复文本和对话流程，不要把 chain-of-thought 当作患者可见内容。
2. 输出必须是合法 JSON，字段结构如下:
{{
  "summary": "string",
  "overall_score": 0-100,
  "dimensions": [
    {{"name": "医学准确性", "score": 0-100, "rationale": "string"}},
    {{"name": "流程完整性", "score": 0-100, "rationale": "string"}},
    {{"name": "患者满意度模拟评分", "score": 0-100, "rationale": "string"}},
    {{"name": "风险识别与处理能力", "score": 0-100, "rationale": "string"}}
  ],
  "strengths": ["string"],
  "risks": ["string"],
  "recommendations": ["string"]
}}

测试模板: {run_record.agent_template.name}
模板说明: {run_record.agent_template.description}
评估关注点: {json.dumps(run_record.agent_template.evaluation_focus, ensure_ascii=False)}
患者画像:
{run_record.patient_profile.build_identity_profile_text()}

测试配置:
- 场景: {run_record.config.scenario}
- 初始状态: {run_record.config.initial_state}
- 边界条件: {run_record.config.boundary_conditions}
- 补充说明: {run_record.config.patient_notes}

患者感知到的工具上下文:
{json.dumps(tool_summary, ensure_ascii=False)}

完整对话:
{chr(10).join(transcript)}
""".strip()

        response = await model.ainvoke(prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )

        payload = self._extract_json(str(content))
        dimensions = [
            EvaluationDimensionScore.model_validate(item)
            for item in payload.get("dimensions", [])
        ]

        return EvaluationReport(
            evaluator_mode="llm",
            overall_score=float(payload.get("overall_score", 0)),
            summary=str(payload.get("summary", "")).strip(),
            dimensions=dimensions,
            strengths=[str(item) for item in payload.get("strengths", [])],
            risks=[str(item) for item in payload.get("risks", [])],
            recommendations=[str(item) for item in payload.get("recommendations", [])],
        )

    def _heuristic_evaluation(self, run_record: SimulationRunRecord) -> EvaluationReport:
        agent_messages = [item for item in run_record.messages if item.role == "dify"]
        patient_messages = [item for item in run_record.messages if item.role == "simulator"]
        transcript_text = "\n".join(item.content for item in agent_messages)

        asked_questions = sum(1 for item in agent_messages if "？" in item.content or "?" in item.content)
        empathy_hits = sum(1 for item in agent_messages if any(word in item.content for word in ("理解", "抱歉", "放心", "辛苦", "感谢")))
        risk_hits = sum(1 for item in agent_messages if any(word in item.content for word in ("尽快", "线下就医", "急诊", "风险", "复诊")))
        symptoms_covered = sum(
            1
            for symptom in run_record.patient_profile.current_symptoms
            if symptom and symptom in transcript_text
        )

        medical_accuracy = min(95, 45 + symptoms_covered * 12 + risk_hits * 8)
        completeness = min(95, 40 + asked_questions * 10 + len(agent_messages) * 6)
        satisfaction = min(95, 42 + empathy_hits * 12 + len(patient_messages) * 4)
        risk_management = min(95, 35 + risk_hits * 18 + len(run_record.patient_profile.risk_flags) * 4)

        dimensions = [
            EvaluationDimensionScore(
                name="医学准确性",
                score=medical_accuracy,
                rationale="基于症状覆盖度、建议具体性和风险提示词做启发式估计。",
            ),
            EvaluationDimensionScore(
                name="流程完整性",
                score=completeness,
                rationale="基于追问轮次、信息采集连续性和收束动作做启发式估计。",
            ),
            EvaluationDimensionScore(
                name="患者满意度模拟评分",
                score=satisfaction,
                rationale="基于共情表达、解释清晰度和对患者问题的响应度做启发式估计。",
            ),
            EvaluationDimensionScore(
                name="风险识别与处理能力",
                score=risk_management,
                rationale="基于风险信号识别、就医建议和工具回传结果做启发式估计。",
            ),
        ]

        overall_score = round(mean(item.score for item in dimensions), 1)
        strengths = []
        risks = []
        recommendations = []

        if asked_questions >= 2:
            strengths.append("能够连续追问关键信息，基本形成问诊闭环。")
        if empathy_hits >= 1:
            strengths.append("回复中包含安抚或共情表达，降低了患者对抗感。")
        if run_record.patient_state.tool_calls:
            strengths.append("对话中有工具调用痕迹，可支持更复杂的流程验证。")

        if symptoms_covered < max(1, len(run_record.patient_profile.current_symptoms) // 2):
            risks.append("对患者主要症状覆盖不足，医学判断依据可能不完整。")
            recommendations.append("增加对主诉、持续时间、诱因和既往处理的追问。")
        if risk_hits == 0 and run_record.patient_profile.risk_flags:
            risks.append("存在风险信号但回复中缺少明确升级处置建议。")
            recommendations.append("针对高风险信号补充就医时机、线下复诊或急诊分流建议。")
        if asked_questions < 2:
            risks.append("对话追问偏少，流程可能提前结束。")
            recommendations.append("在给结论前先完成最小必要病史采集。")

        if not strengths:
            strengths.append("本轮对话能够完成基础应答，但亮点不够突出。")
        if not risks:
            risks.append("未发现明显高危失误，但仍建议结合人工抽检复核。")
        if not recommendations:
            recommendations.append("建议增加标准化测试集，持续对比不同模板下的表现。")

        return EvaluationReport(
            evaluator_mode="heuristic",
            overall_score=overall_score,
            summary="基于本地启发式规则生成的自动评估结果，可用于联调和回归比较。",
            dimensions=dimensions,
            strengths=strengths,
            risks=risks,
            recommendations=recommendations,
        )

    @staticmethod
    def _extract_json(content: str) -> dict:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise ValueError("评估模型未返回有效 JSON")

        return json.loads(stripped[start:end + 1])
