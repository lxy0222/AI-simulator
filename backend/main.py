from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from config import settings
from dify_client import DifyClient
from evaluation import ConversationEvaluator
from models import ChatMessage, SimulationConfig, SimulationRunRecord
from runtime import build_agent_inputs, extract_patient_perceptions, serialize_chat_history
from simulator_agent import SimulatorAgent
from storage import LocalDataStore


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoZenith - 医疗 Agent 测试框架",
    description="支持多类医疗 Agent、多患者画像、多轮对话与结构化评估的测试后端",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = LocalDataStore()
dify_client = DifyClient()
conversation_evaluator = ConversationEvaluator()


def build_default_request():
    templates = store.list_agent_templates()
    patients = store.list_patient_profiles()

    if not templates or not patients:
        raise HTTPException(status_code=500, detail="缺少 Agent 模板或患者画像数据。")

    template = templates[0]
    patient = patients[0]
    extra_inputs = {}
    for field in template.input_schema:
        if field.name in {"scenario", "initial_state", "boundary_conditions", "patient_notes"}:
            continue
        extra_inputs[field.name] = field.default

    return {
        "agent_template_id": template.id,
        "patient_profile_id": patient.id,
        "scenario": template.default_scenario,
        "initial_state": template.default_initial_state,
        "boundary_conditions": template.default_boundary_conditions,
        "patient_notes": "",
        "max_turns": 5,
        "extra_inputs": extra_inputs,
    }


async def run_conversation_loop(config: SimulationConfig) -> AsyncGenerator[str, None]:
    run_id = f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_record = None
    conversation_id = ""
    last_agent_reply = ""
    turn = 0

    try:
        template = store.get_agent_template(config.agent_template_id)
        patient_profile = store.get_patient_profile(config.patient_profile_id)

        runtime_config = SimulationConfig(
            agent_template_id=template.id,
            patient_profile_id=patient_profile.id,
            scenario=config.scenario or template.default_scenario,
            initial_state=config.initial_state or template.default_initial_state,
            boundary_conditions=config.boundary_conditions or template.default_boundary_conditions,
            patient_notes=config.patient_notes,
            max_turns=config.max_turns,
            extra_inputs=config.extra_inputs,
        )

        run_record = SimulationRunRecord(
            run_id=run_id,
            agent_template=template,
            patient_profile=patient_profile,
            config=runtime_config,
        )
        output_path = store.save_run(run_record)

        yield json.dumps(
            {
                "event": "start",
                "data": {
                    "message": "测试运行开始",
                    "run_id": run_id,
                    "run_file": str(output_path),
                    "config": {
                        "scenario": runtime_config.scenario,
                        "max_turns": runtime_config.max_turns,
                        "mock_mode": settings.MOCK_DIFY,
                        "agent_template_name": template.name,
                        "patient_profile_name": patient_profile.name,
                    },
                },
            },
            ensure_ascii=False,
        )

        simulator = SimulatorAgent(
            patient_profile=patient_profile,
            scenario=runtime_config.scenario or template.default_scenario,
            initial_state=runtime_config.initial_state,
            boundary_conditions=runtime_config.boundary_conditions,
            patient_notes=runtime_config.patient_notes,
        )

        for turn in range(1, runtime_config.max_turns + 1):
            if turn == 1:
                simulator_msg = await simulator.generate_opening()
            else:
                simulator_msg = await simulator.generate_reply(
                    final_reply_text=last_agent_reply,
                    interaction_state=run_record.patient_state,
                )

            simulator_message = ChatMessage(
                role="simulator",
                content=simulator_msg,
                turn=turn,
            )
            run_record.messages.append(simulator_message)
            run_record.updated_at = datetime.now().isoformat()
            store.save_run(run_record)

            yield json.dumps(
                {"event": "message", "data": simulator_message.model_dump(mode="json")},
                ensure_ascii=False,
            )
            await asyncio.sleep(0.2)

            yield json.dumps(
                {
                    "event": "thinking",
                    "data": {
                        "role": "dify",
                        "turn": turn,
                        "message": f"{template.name} 正在思考...",
                    },
                },
                ensure_ascii=False,
            )

            agent_inputs = build_agent_inputs(
                config=runtime_config,
                template=template,
                patient_profile=patient_profile,
                run_id=run_id,
                chat_history=serialize_chat_history(run_record.messages),
                patient_state=run_record.patient_state,
            )
            agent_inputs["sys.query"] = simulator_msg
            agent_inputs["agent_display_name"] = template.name

            dify_result = await dify_client.send_message(
                query=simulator_msg,
                inputs=agent_inputs,
                conversation_id=conversation_id,
                user=f"autozenith-{patient_profile.id}",
            )

            last_agent_reply = dify_result["answer"]
            conversation_id = dify_result.get("conversation_id", conversation_id)
            trace = dify_result.get("trace", [])
            perceptions = extract_patient_perceptions(
                turn=turn,
                answer=last_agent_reply,
                trace=trace,
                patient_state=run_record.patient_state,
            )

            dify_message = ChatMessage(
                role="dify",
                content=last_agent_reply,
                turn=turn,
                trace=trace,
                perceptions=perceptions,
            )
            run_record.messages.append(dify_message)
            run_record.updated_at = datetime.now().isoformat()
            store.save_run(run_record)

            yield json.dumps(
                {"event": "message", "data": dify_message.model_dump(mode="json")},
                ensure_ascii=False,
            )
            await asyncio.sleep(0.3)

        evaluation = await conversation_evaluator.evaluate(run_record)
        run_record.evaluation = evaluation
        run_record.status = "completed"
        run_record.updated_at = datetime.now().isoformat()
        run_record.result_summary = {
            "total_turns": runtime_config.max_turns,
            "conversation_id": conversation_id,
            "overall_score": evaluation.overall_score,
        }
        output_path = store.save_run(run_record)

        yield json.dumps(
            {
                "event": "evaluation",
                "data": evaluation.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        yield json.dumps(
            {
                "event": "done",
                "data": {
                    "message": "对话模拟完成",
                    "status": run_record.status,
                    "total_turns": runtime_config.max_turns,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "run_file": str(output_path),
                },
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        error_type = type(exc).__name__
        error_detail = str(exc).strip() or repr(exc)
        error_traceback = traceback.format_exc()
        logger.exception("对话测试失败，run_id=%s", run_id)

        if run_record is not None:
            run_record.status = "failed"
            run_record.updated_at = datetime.now().isoformat()
            run_record.result_summary = {
                "error_type": error_type,
                "error_detail": error_detail,
                "failed_turn": turn,
            }
            store.save_run(run_record)

        yield json.dumps(
            {
                "event": "error",
                "data": {
                    "message": f"对话过程中发生错误: {error_type}: {error_detail}",
                    "error_type": error_type,
                    "error_detail": error_detail,
                    "traceback": error_traceback,
                    "turn": turn,
                    "run_id": run_id,
                },
            },
            ensure_ascii=False,
        )
        yield json.dumps(
            {
                "event": "done",
                "data": {
                    "message": "测试运行异常结束",
                    "status": "failed",
                    "run_id": run_id,
                },
            },
            ensure_ascii=False,
        )


@app.get("/")
async def root():
    return {
        "service": "AutoZenith",
        "status": "running",
        "mock_mode": settings.MOCK_DIFY,
        "agent_templates": len(store.list_agent_templates()),
        "patient_profiles": len(store.list_patient_profiles()),
    }


@app.get("/api/config/defaults")
async def get_default_config():
    templates = [item.model_dump(mode="json") for item in store.list_agent_templates()]
    patient_profiles = [item.model_dump(mode="json") for item in store.list_patient_profiles()]

    return {
        "mock_mode": settings.MOCK_DIFY,
        "agent_templates": templates,
        "patient_profiles": patient_profiles,
        "default_request": build_default_request(),
    }


@app.post("/api/simulation/start")
async def start_simulation(config: SimulationConfig):
    return EventSourceResponse(
        run_conversation_loop(config),
        media_type="text/event-stream",
    )


if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  AutoZenith - 医疗 Agent 测试框架")
    print(f"  Mock 模式: {'✅ 开启' if settings.MOCK_DIFY else '❌ 关闭'}")
    print(f"  数据目录: {settings.DATA_DIR}")
    print(f"  服务地址: http://{settings.HOST}:{settings.PORT}")
    print("=" * 50)

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
