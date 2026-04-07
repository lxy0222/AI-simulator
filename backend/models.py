from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FieldType = Literal["text", "textarea", "select", "number", "switch"]


class InputFieldOption(BaseModel):
    label: str
    value: str


class InputFieldDefinition(BaseModel):
    name: str
    label: str
    type: FieldType = "text"
    required: bool = False
    help_text: str = ""
    placeholder: str = ""
    default: Any = None
    min: int | None = None
    max: int | None = None
    options: list[InputFieldOption] = Field(default_factory=list)


class PatientProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    gender: str = ""
    age: int | None = None
    chief_complaint: str = ""
    current_symptoms: list[str] = Field(default_factory=list)
    medical_history: list[str] = Field(default_factory=list)
    medication_history: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    background_story: str = ""
    communication_style: str = ""
    persona: str = ""
    expectations: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    reusable_tags: list[str] = Field(default_factory=list)

    def build_identity_profile_text(self) -> str:
        lines = [
            f"姓名: {self.name}",
            f"性别: {self.gender or '未知'}",
            f"年龄: {self.age if self.age is not None else '未知'}",
            f"主诉: {self.chief_complaint or '未提供'}",
        ]

        if self.current_symptoms:
            lines.append("当前症状: " + "；".join(self.current_symptoms))
        if self.medical_history:
            lines.append("既往史: " + "；".join(self.medical_history))
        if self.medication_history:
            lines.append("用药史: " + "；".join(self.medication_history))
        if self.allergies:
            lines.append("过敏史: " + "；".join(self.allergies))
        if self.background_story:
            lines.append("背景故事: " + self.background_story)
        if self.persona:
            lines.append("人物性格: " + self.persona)
        if self.expectations:
            lines.append("诉求重点: " + "；".join(self.expectations))
        if self.risk_flags:
            lines.append("风险点: " + "；".join(self.risk_flags))

        return "\n".join(lines)


class AgentTemplateConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    agent_type: str
    description: str = ""
    supported_scenarios: list[str] = Field(default_factory=lambda: ["初诊"])
    default_scenario: str = "初诊"
    default_initial_state: str = ""
    default_boundary_conditions: str = ""
    input_schema: list[InputFieldDefinition] = Field(default_factory=list)
    base_inputs: dict[str, Any] = Field(default_factory=dict)
    input_bindings: dict[str, str] = Field(default_factory=dict)
    evaluation_focus: list[str] = Field(default_factory=list)
    mock_reply_style: str = ""


class SimulationConfig(BaseModel):
    agent_template_id: str = Field(description="被测 Agent 模板 ID")
    patient_profile_id: str = Field(description="复用患者画像 ID")
    scenario: str | None = Field(default=None, description="测试场景")
    initial_state: str = Field(default="", description="测试初始状态")
    boundary_conditions: str = Field(default="", description="边界条件")
    patient_notes: str = Field(default="", description="本轮测试附加患者说明")
    max_turns: int = Field(default=5, ge=1, le=20, description="最大对话轮数")
    extra_inputs: dict[str, Any] = Field(default_factory=dict, description="动态扩展入参")


class ToolCallRecord(BaseModel):
    turn: int
    kind: str = ""
    tool_names: list[str] = Field(default_factory=list)
    tool_input: Any = None
    observation: Any = None
    created_at: str | None = None
    summary: str = ""


class PatientInteractionState(BaseModel):
    last_agent_reply: str = ""
    image_urls: list[str] = Field(default_factory=list)
    mini_program_cards: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    visible_events: list[str] = Field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = []

        if self.image_urls:
            lines.append("历史上 AI 曾发送图片: " + "；".join(self.image_urls[-3:]))
        if self.mini_program_cards:
            lines.append("历史上 AI 曾发送卡片/小程序: " + "；".join(self.mini_program_cards[-3:]))
        if self.tool_calls:
            tool_lines = []
            for item in self.tool_calls[-3:]:
                if item.summary:
                    tool_lines.append(item.summary)
            lines.append("你感知到的工具调用结果: " + "；".join(tool_lines))
        if self.visible_events:
            lines.append("额外上下文: " + "；".join(self.visible_events[-5:]))

        return "\n".join(lines) if lines else "目前没有额外的图片、卡片或工具调用上下文。"


class ChatMessage(BaseModel):
    role: str = Field(description="消息角色：simulator / dify / system")
    content: str = Field(description="消息内容")
    turn: int = Field(description="当前轮次")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    trace: list[dict[str, Any]] = Field(default_factory=list)
    perceptions: dict[str, Any] = Field(default_factory=dict)


class EvaluationDimensionScore(BaseModel):
    name: str
    score: float
    rationale: str


class EvaluationReport(BaseModel):
    evaluator_mode: str
    overall_score: float
    summary: str
    dimensions: list[EvaluationDimensionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class SimulationRunRecord(BaseModel):
    run_id: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: str = "running"
    agent_template: AgentTemplateConfig
    patient_profile: PatientProfile
    config: SimulationConfig
    messages: list[ChatMessage] = Field(default_factory=list)
    patient_state: PatientInteractionState = Field(default_factory=PatientInteractionState)
    evaluation: EvaluationReport | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
