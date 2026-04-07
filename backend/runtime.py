from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime
from typing import Any

from models import (
    AgentTemplateConfig,
    ChatMessage,
    PatientInteractionState,
    PatientProfile,
    SimulationConfig,
    ToolCallRecord,
)


IMAGE_URL_RE = re.compile(r"https?://[^\s'\"<>]+?\.(?:png|jpg|jpeg|gif|webp)", re.IGNORECASE)
CARD_SIGNAL_KEYS = {
    "mini_program",
    "miniProgram",
    "miniprogram",
    "mini_app",
    "miniapp",
    "card",
    "card_info",
    "cardInfo",
    "card_data",
    "cardData",
    "card_url",
    "cardUrl",
    "card_type",
    "cardType",
    "applet",
    "applet_info",
    "app_link",
    "appLink",
    "deeplink",
    "deep_link",
    "jump_url",
    "jumpUrl",
    "schema",
}
PRESCRIPTION_SIGNAL_KEYS = {
    "prescription",
    "prescription_info",
    "prescriptionInfo",
    "prescription_id",
    "prescriptionId",
    "recipe",
    "recipe_info",
    "recipeInfo",
    "rx",
    "drug_list",
    "drugList",
    "medication_list",
    "medicationList",
}
PATIENT_VISIBLE_TOOL_NAME_KEYWORDS = (
    "card",
    "mini",
    "image"
)


def build_agent_inputs(
    *,
    config: SimulationConfig,
    template: AgentTemplateConfig,
    patient_profile: PatientProfile,
    run_id: str,
    chat_history: list[dict[str, Any]],
    patient_state: PatientInteractionState,
) -> dict[str, Any]:
    """根据模板和运行时状态生成 Agent 调用入参。"""
    now = datetime.now()
    inputs = copy.deepcopy(template.base_inputs)

    runtime_values = {
        "scenario": config.scenario or template.default_scenario,
        "initial_state": config.initial_state or template.default_initial_state,
        "boundary_conditions": config.boundary_conditions or template.default_boundary_conditions,
        "patient_notes": config.patient_notes,
        "patient_profile_id": patient_profile.id,
        "patient_profile_json": json.dumps(patient_profile.model_dump(mode="json"), ensure_ascii=False),
        "patient_profile_text": patient_profile.build_identity_profile_text(),
        "identity_profile": patient_profile.build_identity_profile_text(),
        "communication_style": patient_profile.communication_style,
        "patient_name": patient_profile.name,
        "patient_age": patient_profile.age,
        "patient_gender": patient_profile.gender,
        "chief_complaint": patient_profile.chief_complaint,
        "current_symptoms": json.dumps(patient_profile.current_symptoms, ensure_ascii=False),
        "medical_history": json.dumps(patient_profile.medical_history, ensure_ascii=False),
        "risk_flags": json.dumps(patient_profile.risk_flags, ensure_ascii=False),
        "chat_history": json.dumps(chat_history, ensure_ascii=False),
        "patient_context": patient_state.to_prompt_text(),
        "current_time": now.isoformat(),
        "user_msg_timestamp": int(now.timestamp() * 1000),
        "conversation_run_id": run_id,
        "union_id": f"autozenith-{run_id}",
        "externalUserId": f"autozenith-ext-{run_id[:12]}",
        "chat_record_id": str(uuid.uuid4().int)[:18],
        "trance_id": str(uuid.uuid4().int)[:17],
        "sys.workflow_run_id": str(uuid.uuid4()),
        "sys.dialogue_count": len(chat_history) // 2 + 1,
    }

    for key, value in config.extra_inputs.items():
        runtime_values[key] = value

    inputs.setdefault("chat_history", "[]")
    inputs.setdefault("sys.files", [])
    inputs.setdefault("sys.query", "")

    for source_key, target_key in template.input_bindings.items():
        if source_key not in runtime_values:
            continue
        value = runtime_values[source_key]
        if value is None:
            continue
        inputs[target_key] = value

    return inputs


def extract_patient_perceptions(
    *,
    turn: int,
    answer: str,
    trace: list[dict[str, Any]],
    patient_state: PatientInteractionState,
) -> dict[str, Any]:
    """从最终回复与工具 trace 中提取患者应感知到的上下文。"""
    visible_trace = _filter_patient_visible_trace(trace)
    image_urls = _extract_image_urls(answer, visible_trace)
    cards = _extract_cards(visible_trace)
    new_tool_calls = _extract_tool_calls(turn=turn, trace=visible_trace)
    visible_events = []

    if image_urls:
        patient_state.image_urls.extend([item for item in image_urls if item not in patient_state.image_urls])
        visible_events.append(f"AI 发送了 {len(image_urls)} 张图片")

    if cards:
        patient_state.mini_program_cards.extend([item for item in cards if item not in patient_state.mini_program_cards])
        visible_events.append("AI 发送了卡片或小程序")

    if new_tool_calls:
        patient_state.tool_calls.extend(new_tool_calls)
        visible_events.extend(_build_tool_visibility_events(new_tool_calls, cards_present=bool(cards)))

    patient_state.last_agent_reply = answer
    patient_state.visible_events.extend(visible_events)

    return {
        "image_urls": image_urls,
        "mini_program_cards": cards,
        "tool_calls": [item.model_dump(mode="json") for item in new_tool_calls],
        "visible_events": visible_events,
    }


def serialize_chat_history(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    history = []
    for message in messages:
        if message.role not in {"simulator", "dify"}:
            continue
        history.append(
            {
                "role": "user" if message.role == "simulator" else "assistant",
                "content": message.content,
                "timestamp": message.timestamp,
            }
        )
    return history


def _extract_image_urls(answer: str, trace: list[dict[str, Any]]) -> list[str]:
    urls = set(IMAGE_URL_RE.findall(answer or ""))

    for item in trace or []:
        for payload in (item.get("tool_input"), item.get("observation")):
            urls.update(IMAGE_URL_RE.findall(_safe_string(payload)))

    return list(urls)


def _extract_cards(trace: list[dict[str, Any]]) -> list[str]:
    cards = []

    for item in trace or []:
        for payload in (item.get("tool_input"), item.get("observation")):
            cards.extend(_collect_card_signals(payload))

    deduped = []
    seen = set()
    for card in cards:
        normalized = card.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _extract_tool_calls(turn: int, trace: list[dict[str, Any]]) -> list[ToolCallRecord]:
    records = []
    seen = set()

    for item in trace or []:
        tool_names = item.get("tool_names") or []
        if not tool_names:
            continue

        dedupe_key = (
            tuple(tool_names),
            _safe_string(item.get("tool_input")),
            _safe_string(item.get("observation")),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        kind = _classify_visible_tool(item)
        summary = _build_patient_visible_tool_summary(kind, tool_names)

        records.append(
            ToolCallRecord(
                turn=turn,
                kind=kind,
                tool_names=tool_names,
                tool_input=_sanitize_patient_visible_payload(item.get("tool_input"), kind),
                observation=_sanitize_patient_visible_payload(item.get("observation"), kind),
                created_at=item.get("created_at"),
                summary=summary,
            )
        )

    return records


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _filter_patient_visible_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in trace or [] if _is_patient_visible_trace_item(item)]


def _is_patient_visible_trace_item(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False

    tool_names = [str(name).strip() for name in (item.get("tool_names") or []) if str(name).strip()]
    for tool_name in tool_names:
        normalized = tool_name.lower()
        if any(keyword in normalized for keyword in PATIENT_VISIBLE_TOOL_NAME_KEYWORDS):
            return True

    for payload in (item.get("tool_input"), item.get("observation")):
        if _has_any_key(payload, CARD_SIGNAL_KEYS | PRESCRIPTION_SIGNAL_KEYS):
            return True
        if IMAGE_URL_RE.search(_safe_string(payload)):
            return True

    return False


def _has_any_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if str(key) in keys:
                return True
            if _has_any_key(nested_value, keys):
                return True
    elif isinstance(value, list):
        for item in value:
            if _has_any_key(item, keys):
                return True
    return False


def _classify_visible_tool(item: dict[str, Any]) -> str:
    for payload in (item.get("tool_input"), item.get("observation")):
        if _has_any_key(payload, CARD_SIGNAL_KEYS):
            return "card"
        if _has_any_key(payload, PRESCRIPTION_SIGNAL_KEYS):
            return "prescription"
        if IMAGE_URL_RE.search(_safe_string(payload)):
            return "image"

    tool_names = " ".join(str(name).lower() for name in (item.get("tool_names") or []))
    if any(keyword in tool_names for keyword in ("处方", "prescription", "recipe", "rx", "药单")):
        return "prescription"
    if any(keyword in tool_names for keyword in ("card", "mini", "applet", "卡片", "小程序", "二维码")):
        return "card"
    if any(keyword in tool_names for keyword in ("image", "picture", "photo", "图片", "海报")):
        return "image"
    return "visible_tool"


def _build_patient_visible_tool_summary(kind: str, tool_names: list[str]) -> str:
    if kind == "prescription":
        return "AI 提供了处方或药单信息。"
    if kind == "card":
        return "AI 发送了卡片或小程序。"
    if kind == "image":
        return "AI 发送了图片。"

    if tool_names:
        return f"AI 返回了患者可见工具结果（{'、'.join(tool_names)}）。"
    return "AI 返回了患者可见工具结果。"


def _sanitize_patient_visible_payload(value: Any, kind: str) -> Any:
    if value is None:
        return None

    if kind == "card":
        return _extract_key_subset(value, CARD_SIGNAL_KEYS)
    if kind == "prescription":
        return _extract_key_subset(value, PRESCRIPTION_SIGNAL_KEYS)
    if kind == "image":
        urls = IMAGE_URL_RE.findall(_safe_string(value))
        return urls[:3] if urls else None

    return None


def _extract_key_subset(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        matched = {}
        for key, nested_value in value.items():
            normalized_key = str(key)
            if normalized_key in keys:
                matched[normalized_key] = nested_value
                continue

            nested_matched = _extract_key_subset(nested_value, keys)
            if nested_matched not in (None, {}, []):
                matched[normalized_key] = nested_matched
        return matched or None

    if isinstance(value, list):
        collected = []
        for item in value:
            nested = _extract_key_subset(item, keys)
            if nested not in (None, {}, []):
                collected.append(nested)
        return collected or None

    return None


def _build_tool_visibility_events(tool_calls: list[ToolCallRecord], cards_present: bool) -> list[str]:
    events = []
    kinds = {item.kind for item in tool_calls}

    if "prescription" in kinds:
        events.append("AI 提供了处方信息")
    if "image" in kinds:
        events.append("AI 提供了图片类结果")
    if "card" in kinds and not cards_present:
        events.append("AI 发送了卡片或小程序")

    return events


def _collect_card_signals(value: Any) -> list[str]:
    results = []

    if isinstance(value, dict):
        matched_keys = [key for key in value.keys() if key in CARD_SIGNAL_KEYS]
        if matched_keys:
            snippet = _safe_string({key: value.get(key) for key in matched_keys})[:160]
            if snippet:
                results.append(snippet)

        for key, nested_value in value.items():
            normalized_key = str(key)
            if normalized_key in CARD_SIGNAL_KEYS and isinstance(nested_value, str) and nested_value.strip():
                results.append(f"{normalized_key}: {nested_value.strip()[:120]}")
            results.extend(_collect_card_signals(nested_value))

    elif isinstance(value, list):
        for item in value:
            results.extend(_collect_card_signals(item))

    return results
