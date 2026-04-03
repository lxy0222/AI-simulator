# ============================================
# Dify API 客户端
# 负责与 Dify Chat Messages API 的通信
# ============================================

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone

import httpx

from config import settings

logger = logging.getLogger(__name__)


class DifyClient:
    """
    Dify 聊天接口客户端
    支持 blocking 模式调用 Chat Messages API
    """

    def __init__(self):
        self.api_base = settings.DIFY_API_BASE
        self.api_key = settings.DIFY_API_KEY
        self.mock_mode = settings.MOCK_DIFY
        self.timeout = httpx.Timeout(
            connect=settings.DIFY_CONNECT_TIMEOUT,
            read=settings.DIFY_READ_TIMEOUT,
            write=settings.DIFY_WRITE_TIMEOUT,
            pool=settings.DIFY_POOL_TIMEOUT,
        )

    async def send_message(
        self,
        query: str,
        inputs: dict,
        conversation_id: str = "",
        user: str = "autozenith-tester",
    ) -> dict:
        """
        向 Dify 发送聊天消息

        Args:
            query: 用户消息（Simulator 生成的对话内容）
            inputs: 上下文变量（患者信息、场景等）
            conversation_id: 会话ID，首轮为空字符串
            user: 用户标识

        Returns:
            dict: 包含 answer 和 conversation_id 的响应
        """
        if self.mock_mode:
            return await self._mock_response(query, conversation_id)

        return await self._real_request(query, inputs, conversation_id, user)

    async def _real_request(
        self,
        query: str,
        inputs: dict,
        conversation_id: str,
        user: str,
    ) -> dict:
        """真实调用 Dify API"""
        url = f"{self.api_base}/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }

        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": "streaming",
            "conversation_id": conversation_id,
            "user": user,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()

                    if "text/event-stream" in content_type:
                        return await self._parse_sse_response(response)

                    body = await response.aread()
                    data = json.loads(body)
        except httpx.ReadTimeout as exc:
            raise RuntimeError(
                "Dify 响应超时。"
                f"URL={url}，read_timeout={settings.DIFY_READ_TIMEOUT}s。"
                "当前 Dify 返回较慢，建议继续增大 DIFY_READ_TIMEOUT，"
                "或改为更快的应用/模型配置。"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                "Dify 接口返回非 2xx 状态。"
                f"status={exc.response.status_code}，url={url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Dify 网络请求失败（{type(exc).__name__}）: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Dify 返回的内容不是有效 JSON: {exc}"
            ) from exc

        return {
            "answer": data.get("answer", ""),
            "conversation_id": data.get("conversation_id", ""),
            "trace": data.get("trace", []),
        }

    async def _parse_sse_response(self, response: httpx.Response) -> dict:
        """解析 Dify 的 SSE 响应，拼出最终 answer。"""
        answer = ""
        conversation_id = ""
        thought_trace_map = {}
        thought_trace_order = []
        seen_agent_log_ids = set()
        round_id_to_trace_id = {}
        node_id_to_title = {}
        seen_embedded_tool_call_ids = set()
        raw_event_count = 0

        async for line in response.aiter_lines():
            if not line:
                continue

            if line.startswith(":"):
                continue

            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue

            try:
                event_data = json.loads(data_str)
            except json.JSONDecodeError:
                logger.warning("收到无法解析的 SSE 数据: %s", data_str)
                continue

            if not isinstance(event_data, dict):
                continue

            raw_event_count += 1
            conversation_id = event_data.get("conversation_id") or conversation_id
            event_name = str(event_data.get("event", "")).lower()

            if event_name in {"agent_log", "agent_thought", "node_started", "node_finished"}:
                logger.warning(
                    "Dify trace event received: event=%s payload=%s",
                    event_name,
                    json.dumps(event_data, ensure_ascii=False, default=str),
                )

            if event_name == "error":
                raise RuntimeError(
                    event_data.get("message")
                    or event_data.get("error")
                    or "Dify SSE 返回 error 事件"
                )

            if event_name in {"node_started", "node_finished"}:
                data_node = event_data.get("data", {})
                node_id = data_node.get("node_id")
                node_title = data_node.get("title")
                if node_id and node_title:
                    node_id_to_title[node_id] = node_title

                if event_name == "node_finished":
                    embedded_count = self._process_embedded_agent_node(
                        data_node=data_node,
                        thought_trace_map=thought_trace_map,
                        thought_trace_order=thought_trace_order,
                        seen_embedded_tool_call_ids=seen_embedded_tool_call_ids,
                    )
                    if embedded_count:
                        logger.warning(
                            "Dify embedded tool traces captured from node_finished: count=%s node_title=%s",
                            embedded_count,
                            data_node.get("title"),
                        )

                    trace_item = self._build_node_trace_item(data_node)
                    if trace_item:
                        logger.warning(
                            "Dify node_finished tool captured: trace_id=%s tool_names=%s tool_input=%s observation=%s",
                            trace_item.get("id"),
                            trace_item.get("tool_names"),
                            json.dumps(trace_item.get("tool_input"), ensure_ascii=False, default=str),
                            json.dumps(trace_item.get("observation"), ensure_ascii=False, default=str),
                        )
                        trace_id = trace_item["id"]
                        self._upsert_trace_item(
                            thought_trace_map,
                            thought_trace_order,
                            trace_id,
                            trace_item,
                        )
                continue

            if event_name == "agent_log":
                processed = self._process_agent_log_event(
                    event_data=event_data,
                    thought_trace_map=thought_trace_map,
                    thought_trace_order=thought_trace_order,
                    seen_agent_log_ids=seen_agent_log_ids,
                    round_id_to_trace_id=round_id_to_trace_id,
                    node_id_to_title=node_id_to_title,
                )
                if processed:
                    continue

            if self._is_trace_event(event_data):
                trace_id = event_data.get("id") or f"thought-{len(thought_trace_order) + 1}"
                self._upsert_trace_item(
                    thought_trace_map,
                    thought_trace_order,
                    trace_id,
                    self._build_trace_item(event_data),
                )
                continue

            answer_piece = self._extract_answer_piece(event_data)
            if answer_piece:
                answer = self._merge_answer(answer, answer_piece)

        trace = [thought_trace_map[trace_id] for trace_id in thought_trace_order]
        cleaned_answer, fallback_trace = self._split_answer_and_reasoning(answer)
        if trace:
            answer = cleaned_answer
        else:
            answer = cleaned_answer
            trace = fallback_trace

        if not answer:
            raise RuntimeError("Dify SSE 响应结束，但未解析到 answer 内容。")

        logger.warning(
            "Dify SSE parse summary: raw_events=%s trace_items=%s trace=%s answer_preview=%s",
            raw_event_count,
            len(trace),
            json.dumps(trace, ensure_ascii=False, default=str),
            answer[:200],
        )

        return {
            "answer": answer,
            "conversation_id": conversation_id,
            "trace": trace,
        }

    def _process_embedded_agent_node(
        self,
        data_node: dict,
        thought_trace_map: dict,
        thought_trace_order: list,
        seen_embedded_tool_call_ids: set,
    ) -> int:
        """从 agent 类型 node_finished 的 outputs/execution_metadata 中提取工具调用。"""
        if not isinstance(data_node, dict):
            return 0

        if str(data_node.get("node_type", "")).lower() != "agent":
            return 0

        embedded_entries = []
        outputs = data_node.get("outputs", {})
        if isinstance(outputs, dict):
            json_entries = outputs.get("json")
            if isinstance(json_entries, list):
                embedded_entries.extend(json_entries)

        execution_metadata = data_node.get("execution_metadata", {})
        if isinstance(execution_metadata, dict):
            agent_logs = execution_metadata.get("agent_log")
            if isinstance(agent_logs, list):
                embedded_entries.extend(agent_logs)

        if not embedded_entries:
            return 0

        round_positions = self._build_embedded_round_positions(embedded_entries)
        round_entries_with_child_thought = self._find_round_entries_with_child_thought(embedded_entries)
        preferred_call_ids = set()
        for entry in embedded_entries:
            output = self._extract_embedded_output(entry)
            if not isinstance(output, dict):
                continue
            if str(entry.get("label", "")).startswith("CALL "):
                tool_call_id = output.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id.strip():
                    preferred_call_ids.add(tool_call_id.strip())

        inserted = 0
        for entry in embedded_entries:
            reasoning_item = self._build_embedded_reasoning_trace_item(
                entry=entry,
                round_positions=round_positions,
                round_entries_with_child_thought=round_entries_with_child_thought,
            )
            if reasoning_item:
                self._upsert_trace_item(
                    thought_trace_map,
                    thought_trace_order,
                    reasoning_item["id"],
                    reasoning_item,
                )
                inserted += 1

            for trace_item in self._build_embedded_trace_items(
                entry=entry,
                round_positions=round_positions,
                preferred_call_ids=preferred_call_ids,
                seen_embedded_tool_call_ids=seen_embedded_tool_call_ids,
            ):
                self._upsert_trace_item(
                    thought_trace_map,
                    thought_trace_order,
                    trace_item["id"],
                    trace_item,
                )
                inserted += 1

        return inserted

    def _build_embedded_round_positions(self, embedded_entries: list) -> dict:
        """建立嵌入式 agent 日志的 round -> position 映射。"""
        round_positions = {}

        for entry in embedded_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id") or entry.get("message_id")
            if not entry_id:
                continue

            round_index = self._extract_round_index(entry)
            if round_index is not None:
                round_positions[entry_id] = round_index

        changed = True
        while changed:
            changed = False
            for entry in embedded_entries:
                if not isinstance(entry, dict):
                    continue

                entry_id = entry.get("id") or entry.get("message_id")
                parent_id = entry.get("parent_id")
                if not entry_id or not parent_id:
                    continue

                if entry_id in round_positions:
                    continue

                parent_position = round_positions.get(parent_id)
                if parent_position is None:
                    continue

                round_positions[entry_id] = parent_position
                changed = True

        return round_positions

    def _find_round_entries_with_child_thought(self, embedded_entries: list) -> set:
        """找出哪些 ROUND 节点已经有单独的 Thought 子节点。"""
        parent_ids = set()
        for entry in embedded_entries:
            if not isinstance(entry, dict):
                continue
            parent_id = entry.get("parent_id")
            if not parent_id:
                continue

            label = str(entry.get("label", "")).lower()
            output = self._extract_embedded_output(entry)
            if not isinstance(output, dict):
                continue

            thought = self._extract_embedded_thought(
                output.get("llm_response") or output.get("output")
            )
            if "thought" in label and thought:
                parent_ids.add(parent_id)

        return parent_ids

    def _build_embedded_reasoning_trace_item(
        self,
        entry: dict,
        round_positions: dict,
        round_entries_with_child_thought: set,
    ) -> dict | None:
        """从嵌入式 agent 日志中提取纯思考节点。"""
        if not isinstance(entry, dict):
            return None

        output = self._extract_embedded_output(entry)
        if not isinstance(output, dict):
            return None

        entry_id = entry.get("id") or entry.get("message_id")
        if not entry_id:
            return None

        if entry.get("parent_id") is None and entry_id in round_entries_with_child_thought:
            return None

        thought = self._extract_embedded_thought(
            output.get("llm_response") or output.get("output")
        )
        if not thought:
            return None

        return {
            "id": f"embedded-reason-{entry_id}",
            "kind": "embedded_reasoning",
            "position": round_positions.get(entry_id),
            "thought": thought,
            "tool_names": [],
            "tool_input": None,
            "observation": None,
            "created_at": self._format_embedded_metadata_time(entry.get("metadata", {})),
            "raw_event": entry,
        }

    def _build_embedded_trace_items(
        self,
        entry: dict,
        round_positions: dict,
        preferred_call_ids: set,
        seen_embedded_tool_call_ids: set,
    ) -> list:
        """把 node_finished 内嵌的 agent 日志转成工具 trace。"""
        if not isinstance(entry, dict):
            return []

        output = self._extract_embedded_output(entry)
        if not isinstance(output, dict):
            return []

        trace_items = []
        entry_id = entry.get("id") or entry.get("message_id") or entry.get("parent_id") or "embedded"
        label = str(entry.get("label", ""))
        created_at = self._format_embedded_metadata_time(entry.get("metadata", {}))

        tool_call_name = output.get("tool_call_name")
        tool_call_input = output.get("tool_call_input")
        tool_response = output.get("tool_response")
        tool_call_id = output.get("tool_call_id")

        if isinstance(tool_call_name, str) and tool_call_name.strip():
            dedupe_id = str(tool_call_id or f"{entry_id}:{tool_call_name}").strip()
            if dedupe_id not in seen_embedded_tool_call_ids:
                seen_embedded_tool_call_ids.add(dedupe_id)
                trace_items.append({
                    "id": f"embedded-call-{dedupe_id}",
                    "kind": "embedded_tool_call",
                    "position": round_positions.get(entry_id),
                    "thought": "",
                    "tool_names": [tool_call_name.strip()],
                    "tool_input": self._parse_json_maybe(tool_call_input),
                    "observation": self._parse_json_maybe(tool_response),
                    "created_at": created_at,
                    "raw_event": entry,
                })
            return trace_items

        tool_responses = output.get("tool_responses")
        if isinstance(tool_responses, list):
            for index, response_item in enumerate(tool_responses, start=1):
                if not isinstance(response_item, dict):
                    continue

                response_call_id = response_item.get("tool_call_id")
                if response_call_id in preferred_call_ids:
                    continue

                response_name = response_item.get("tool_call_name")
                if not isinstance(response_name, str) or not response_name.strip():
                    continue

                dedupe_id = str(response_call_id or f"{entry_id}:{index}:{response_name}").strip()
                if dedupe_id in seen_embedded_tool_call_ids:
                    continue

                seen_embedded_tool_call_ids.add(dedupe_id)
                trace_items.append({
                    "id": f"embedded-response-{dedupe_id}",
                    "kind": "embedded_tool_response",
                    "position": round_positions.get(entry_id),
                    "thought": "",
                    "tool_names": [response_name.strip()],
                    "tool_input": self._parse_json_maybe(response_item.get("tool_call_input")),
                    "observation": self._parse_json_maybe(response_item.get("tool_response")),
                    "created_at": created_at,
                    "raw_event": entry,
                })

        if trace_items:
            return trace_items

        tool_name = output.get("tool_name")
        tool_input = output.get("tool_input")
        if (
            isinstance(tool_name, str)
            and tool_name.strip()
            and self._has_value(self._parse_json_maybe(tool_input))
            and not label.startswith("CALL ")
        ):
            trace_items.append({
                "id": f"embedded-plan-{entry_id}",
                "kind": "embedded_tool_plan",
                "position": round_positions.get(entry_id),
                "thought": "",
                "tool_names": [tool_name.strip()],
                "tool_input": self._parse_json_maybe(tool_input),
                "observation": None,
                "created_at": created_at,
                "raw_event": entry,
            })

        return trace_items

    @staticmethod
    def _extract_embedded_output(entry: dict):
        """从 outputs.json / execution_metadata.agent_log 条目里提取 output。"""
        data = entry.get("data")
        if isinstance(data, dict):
            output = data.get("output")
            if isinstance(output, dict):
                return output
        return None

    def _extract_embedded_thought(self, value) -> str:
        """从嵌入式日志的 llm_response 中提取 think 内容。"""
        if not isinstance(value, str) or not value.strip():
            return ""

        match = re.search(r"<think>(.*?)</think>", value, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return value.strip()

    @staticmethod
    def _format_embedded_metadata_time(metadata: dict):
        """从嵌入式 agent_log 的 metadata 中提取时间。"""
        if not isinstance(metadata, dict):
            return None

        finished_at = metadata.get("finished_at")
        started_at = metadata.get("started_at")
        if isinstance(finished_at, str) and finished_at:
            return finished_at
        if isinstance(started_at, str) and started_at:
            return started_at
        return None

    @staticmethod
    def _extract_round_index(entry: dict):
        """从 ROUND N 标签中提取真实轮次。"""
        label = str(entry.get("label", "")).strip()
        match = re.match(r"^ROUND\s+(\d+)$", label, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def _upsert_trace_item(
        self,
        trace_map: dict,
        trace_order: list,
        trace_id: str,
        trace_item: dict,
    ) -> None:
        """将 trace 节点插入时间线，若已存在则做增量合并。"""
        if not trace_id:
            return

        if trace_id not in trace_map:
            if trace_item.get("position") is None:
                trace_item["position"] = len(trace_order) + 1
            trace_map[trace_id] = trace_item
            trace_order.append(trace_id)
            logger.warning(
                "Dify trace inserted: trace_id=%s kind=%s tool_names=%s",
                trace_id,
                trace_item.get("kind"),
                trace_item.get("tool_names"),
            )
            return

        trace_map[trace_id] = self._merge_trace_item(trace_map[trace_id], trace_item)
        logger.warning(
            "Dify trace merged: trace_id=%s kind=%s tool_names=%s",
            trace_id,
            trace_map[trace_id].get("kind"),
            trace_map[trace_id].get("tool_names"),
        )

    def _build_node_trace_item(self, data_node: dict) -> dict | None:
        """把 node_finished 中的工具节点转成前端时间线项。"""
        if not isinstance(data_node, dict):
            return None

        node_type = str(data_node.get("node_type", "")).lower()
        if node_type not in {"tool", "http-request"}:
            return None

        node_id = data_node.get("node_id") or data_node.get("id")
        title = data_node.get("title") or data_node.get("node_name") or "tool"

        return {
            "id": f"node-{node_id or title}",
            "kind": "node_finished",
            "position": None,
            "thought": "",
            "tool_names": [title],
            "tool_input": self._parse_json_maybe(data_node.get("inputs")),
            "observation": self._parse_json_maybe(data_node.get("outputs")),
            "created_at": self._format_event_time(
                data_node.get("finished_at")
                or data_node.get("created_at")
                or data_node.get("start_at")
            ),
            "raw_event": data_node,
        }

    def _process_agent_log_event(
        self,
        event_data: dict,
        thought_trace_map: dict,
        thought_trace_order: list,
        seen_agent_log_ids: set,
        round_id_to_trace_id: dict,
        node_id_to_title: dict,
    ) -> bool:
        """解析 agent_log 事件并写入时间线。"""
        outer = event_data.get("data", {})
        if not isinstance(outer, dict):
            return False

        entry_id = outer.get("id")
        entry_status = outer.get("status")
        parent_id = outer.get("parent_id")
        label = str(outer.get("label", ""))
        if not entry_id or entry_status != "success" or entry_id in seen_agent_log_ids:
            return False

        seen_agent_log_ids.add(entry_id)
        log_data = outer.get("data", {})
        if not isinstance(log_data, dict):
            return False

        agent_node_id = outer.get("node_id")
        agent_node_title = node_id_to_title.get(agent_node_id, agent_node_id)
        created_at = self._format_event_time(outer.get("created_at"))

        if parent_id is None:
            action_name = (
                log_data.get("action_name")
                or log_data.get("action")
                or log_data.get("tool_name")
            )
            thought = self._extract_thought(log_data)

            logger.warning(
                "Dify agent_log round entry: entry_id=%s action_name=%s thought=%s observation=%s raw=%s",
                entry_id,
                action_name,
                thought[:200] if isinstance(thought, str) else thought,
                json.dumps(log_data.get("observation"), ensure_ascii=False, default=str),
                json.dumps(log_data, ensure_ascii=False, default=str),
            )

            if (
                isinstance(action_name, str)
                and action_name
                and action_name != "Final Answer"
                and not action_name.strip().startswith("{")
            ):
                trace_item = {
                    "id": f"agent-log-{entry_id}",
                    "kind": "agent_log_tool",
                    "position": None,
                    "thought": thought,
                    "tool_names": [action_name],
                    "tool_input": self._parse_json_maybe(log_data.get("action_input")),
                    "observation": self._parse_json_maybe(log_data.get("observation")),
                    "created_at": created_at,
                    "raw_event": event_data,
                    "caller_node": agent_node_title,
                }
                trace_id = trace_item["id"]
                self._upsert_trace_item(
                    thought_trace_map,
                    thought_trace_order,
                    trace_id,
                    trace_item,
                )
                round_id_to_trace_id[entry_id] = trace_id
                return True

            if thought:
                trace_item = {
                    "id": f"agent-log-{entry_id}",
                    "kind": "agent_log_thought",
                    "position": None,
                    "thought": thought,
                    "tool_names": [],
                    "tool_input": None,
                    "observation": None,
                    "created_at": created_at,
                    "raw_event": event_data,
                    "caller_node": agent_node_title,
                }
                self._upsert_trace_item(
                    thought_trace_map,
                    thought_trace_order,
                    trace_item["id"],
                    trace_item,
                )
                return True

            return False

        target_trace_id = round_id_to_trace_id.get(parent_id)
        if not target_trace_id:
            logger.warning(
                "Dify agent_log child entry skipped: entry_id=%s parent_id=%s label=%s raw=%s",
                entry_id,
                parent_id,
                label,
                json.dumps(log_data, ensure_ascii=False, default=str),
            )
            return False

        trace_item = {
            "id": target_trace_id,
            "kind": "agent_log_call",
            "position": None,
            "thought": self._extract_thought(log_data),
            "tool_names": self._extract_tool_names(log_data),
            "tool_input": self._parse_json_maybe(
                log_data.get("tool_call_args") or log_data.get("action_input")
            ),
            "observation": self._parse_json_maybe(
                log_data.get("output") or log_data.get("observation")
            ),
            "created_at": created_at,
            "raw_event": event_data,
        }

        logger.warning(
            "Dify agent_log child entry: entry_id=%s parent_id=%s label=%s tool_names=%s tool_input=%s observation=%s",
            entry_id,
            parent_id,
            label,
            trace_item.get("tool_names"),
            json.dumps(trace_item.get("tool_input"), ensure_ascii=False, default=str),
            json.dumps(trace_item.get("observation"), ensure_ascii=False, default=str),
        )

        if label.startswith("CALL "):
            self._upsert_trace_item(
                thought_trace_map,
                thought_trace_order,
                target_trace_id,
                trace_item,
            )
            return True

        if self._has_value(trace_item.get("thought")) or self._has_value(trace_item.get("tool_input")):
            self._upsert_trace_item(
                thought_trace_map,
                thought_trace_order,
                target_trace_id,
                trace_item,
            )
            return True

        return False

    def _build_trace_item(self, event_data: dict) -> dict:
        """把一条 agent_thought 事件标准化为前端可渲染结构。"""
        tool_names = self._extract_tool_names(event_data)
        tool_input = self._extract_tool_input(event_data)
        observation = self._extract_observation(event_data)

        return {
            "id": event_data.get("id"),
            "kind": str(event_data.get("event", "")).lower() or "trace_event",
            "position": event_data.get("position"),
            "thought": self._extract_thought(event_data),
            "tool_names": tool_names,
            "tool_input": tool_input,
            "observation": observation,
            "created_at": self._format_event_time(event_data.get("created_at")),
            "raw_event": event_data,
        }

    def _merge_trace_item(self, current: dict, event_data: dict) -> dict:
        """合并同一个 thought 的增量事件。"""
        merged = dict(current)
        new_item = event_data if isinstance(event_data, dict) and "kind" in event_data else self._build_trace_item(event_data)

        for key in ("position", "created_at"):
            if new_item.get(key) is not None:
                merged[key] = new_item[key]

        for key in ("thought", "tool_input", "observation"):
            if self._has_value(new_item.get(key)):
                merged[key] = new_item[key]

        if new_item.get("tool_names"):
            merged["tool_names"] = new_item["tool_names"]

        if new_item.get("kind"):
            merged["kind"] = new_item["kind"]

        merged["raw_event"] = new_item.get("raw_event", event_data)
        return merged

    @staticmethod
    def _extract_answer_piece(event_data: dict) -> str:
        """从一条 SSE 事件中尽量提取文本增量。"""
        for key in ("answer", "text", "delta"):
            value = event_data.get(key)
            if isinstance(value, str) and value.strip():
                return value

        data = event_data.get("data")
        if isinstance(data, dict):
            for key in ("answer", "text", "delta"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value

        return ""

    @staticmethod
    def _merge_answer(current: str, incoming: str) -> str:
        """兼容 SSE 分片和累计文本两种返回形式。"""
        if not current:
            return incoming

        if incoming.startswith(current):
            return incoming

        if current.endswith(incoming):
            return current

        return current + incoming

    @staticmethod
    def _split_tool_names(tool_field: str) -> list:
        """把分号分隔的工具名拆成数组。"""
        if not isinstance(tool_field, str) or not tool_field.strip():
            return []
        return [item.strip() for item in tool_field.split(";") if item.strip()]

    def _extract_tool_names(self, event_data: dict) -> list:
        """兼容不同事件格式提取工具名。"""
        names = []

        for key in ("tool", "tool_name", "action", "action_name"):
            value = event_data.get(key)
            if isinstance(value, str) and value.strip():
                names.extend(self._split_tool_names(value))

        tool_calls = event_data.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                for key in ("tool_name", "name", "action"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        names.append(value.strip())

        output = event_data.get("output")
        if isinstance(output, dict):
            for key in ("tool_call_name", "tool_name", "name", "action"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    names.append(value.strip())

        # 去重并保持顺序
        deduped = []
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _extract_tool_input(self, event_data: dict):
        """兼容不同事件格式提取工具输入。"""
        for key in ("tool_input", "action_input", "tool_parameters", "inputs", "input"):
            value = self._parse_json_maybe(event_data.get(key))
            if self._has_value(value):
                return value

        tool_calls = event_data.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            normalized = []
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                normalized.append({
                    "name": item.get("tool_name") or item.get("name") or item.get("action"),
                    "input": self._parse_json_maybe(
                        item.get("tool_input") or item.get("input") or item.get("arguments")
                    ),
                })
            if normalized:
                return normalized

        output = event_data.get("output")
        if isinstance(output, dict):
            for key in ("tool_call_input", "tool_input", "input", "arguments"):
                value = self._parse_json_maybe(output.get(key))
                if self._has_value(value):
                    return value

        return None

    def _extract_observation(self, event_data: dict):
        """兼容不同事件格式提取工具输出。"""
        for key in ("observation", "tool_output", "output", "result"):
            value = self._parse_json_maybe(event_data.get(key))
            if self._has_value(value):
                return value

        output = event_data.get("output")
        if isinstance(output, dict):
            for key in ("tool_response", "tool_output", "output", "result", "response"):
                value = self._parse_json_maybe(output.get(key))
                if self._has_value(value):
                    return value
        return None

    @staticmethod
    def _extract_thought(event_data: dict) -> str:
        """兼容不同事件格式提取思考内容。"""
        for key in ("thought", "reasoning", "log", "message"):
            value = event_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _is_trace_event(self, event_data: dict) -> bool:
        """判断一条 SSE 事件是否值得纳入思考/工具时间线。"""
        event_name = str(event_data.get("event", "")).lower()
        if event_name in {"agent_thought", "tool_call", "tool_result"}:
            return True

        if self._extract_tool_names(event_data):
            return True

        if self._has_value(self._parse_json_maybe(event_data.get("tool_input"))):
            return True

        if self._has_value(self._parse_json_maybe(event_data.get("observation"))):
            return True

        output = event_data.get("output")
        if isinstance(output, dict):
            if self._extract_tool_names({"output": output}):
                return True
            if self._has_value(self._parse_json_maybe(output.get("tool_call_input"))):
                return True
            if self._has_value(self._parse_json_maybe(output.get("tool_response"))):
                return True

        return False

    @staticmethod
    def _parse_json_maybe(value):
        """尽量把 JSON 字符串解析成对象，失败则保留原值。"""
        if value in (None, "", []):
            return None

        if isinstance(value, (dict, list)):
            return value

        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return None

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped

    @staticmethod
    def _format_event_time(timestamp_value):
        """把 Dify 事件时间戳转成 ISO 字符串。"""
        if timestamp_value in (None, ""):
            return None

        try:
            return datetime.fromtimestamp(
                float(timestamp_value),
                tz=timezone.utc,
            ).astimezone().isoformat()
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _has_value(value) -> bool:
        """判断字段是否有有效内容。"""
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict)):
            return bool(value)
        return True

    def _split_answer_and_reasoning(self, answer: str) -> tuple[str, list]:
        """把回答里的 <think> 块拆成折叠思考，正文单独保留。"""
        if not answer:
            return "", []

        think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
        thought_matches = list(think_pattern.finditer(answer))
        if not thought_matches:
            return answer.strip(), []

        trace = []
        for index, match in enumerate(thought_matches, start=1):
            thought_text = match.group(1).strip()
            if not thought_text:
                continue
            trace.append({
                "id": f"think-{index}",
                "kind": "reasoning_block",
                "position": index,
                "thought": thought_text,
                "tool_names": [],
                "tool_input": None,
                "observation": None,
                "created_at": None,
            })

        cleaned_answer = think_pattern.sub("", answer)
        cleaned_answer = re.sub(r"\n{3,}", "\n\n", cleaned_answer).strip()
        return cleaned_answer, trace

    async def _mock_response(self, query: str, conversation_id: str) -> dict:
        """
        Mock 模式：模拟 Dify 客服智能体的回复
        用于前后端联调阶段，无需真实 API Key
        """
        # 模拟网络延迟
        await asyncio.sleep(random.uniform(0.8, 2.0))

        # 根据关键词生成不同的模拟回复
        mock_replies = [
            "您好！我是小方，很高兴为您服务 😊 请问您想咨询哪方面的问题呢？是您本人还是家人需要看诊？",
            "明白了，请问能详细描述一下症状吗？比如症状持续多久了？有没有其他不舒服的地方？",
            "感谢您的信任！根据您描述的情况，建议先做一些基本的问诊了解。请问之前有没有看过类似的问题？有没有服用什么药物？",
            "好的，我已经记录下您的情况了。根据初步判断，您的症状可能与鼻炎有关。我们这边有专业的中医团队可以帮助您，要不要帮您安排一下问诊呢？",
            "非常理解您的担心，鼻炎虽然常见，但如果长期不调理确实会影响生活质量。我们会根据您的体质进行辨证施治，制定个性化的调理方案。请问您方便提供一下患者的年龄和性别吗？",
            "好的！综合您刚才提供的信息，我建议可以先预约一次线上问诊，医生会根据具体情况给出用药建议。预约时间一般在 1-2 天内，您看方便吗？",
        ]

        # 简单根据轮次选择回复
        reply_index = hash(query) % len(mock_replies)

        # 如果没有 conversation_id，生成一个模拟的
        if not conversation_id:
            conversation_id = f"mock-conv-{random.randint(10000, 99999)}"

        return {
            "answer": mock_replies[reply_index],
            "conversation_id": conversation_id,
        }
