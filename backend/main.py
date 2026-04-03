# ============================================
# AutoZenith - 主应用入口
# FastAPI 后端服务，提供 SSE 流式对聊接口
# ============================================

import json
import asyncio
import uuid
import logging
import traceback
from datetime import datetime
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from config import settings
from models import SimulationConfig
from simulator_agent import SimulatorAgent
from dify_client import DifyClient

logger = logging.getLogger(__name__)

# ---- 创建 FastAPI 应用 ----
app = FastAPI(
    title="AutoZenith - AI 对话博弈测试平台",
    description="双 AI 对话博弈的可视化测试后端",
    version="1.0.0",
)

# ---- CORS 配置（允许前端跨域访问）----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 初始化 Dify 客户端 ----
dify_client = DifyClient()


def build_dify_inputs(config: SimulationConfig) -> dict:
    """
    根据前端配置 + 默认值，组装 Dify API 所需的 inputs 字段

    这里按照用户提供的 Payload 结构组装，
    部分字段使用默认值，实际环境中可从数据库或上下文获取。

    Args:
        config: 前端传入的模拟配置

    Returns:
        dict: Dify inputs 字段完整结构
    """
    # 当前时间戳
    now = datetime.now()
    current_time = now.isoformat()
    user_msg_timestamp = int(now.timestamp() * 1000)

    inputs = {
        # ---- 患者/医生基础信息 ----
        "patient_id": 4117202,
        "doctor_id": 55585,
        "session_id": "298330907301912576",

        # ---- 支持的病种列表 ----
        "supported_diseases": json.dumps(
            ["鼻炎", "外感发热", "高血压", "诺如病毒", "黄褐斑", "痤疮",
             "乳腺结节", "感冒后遗咳嗽", "更年期综合征", "颈椎腰椎病",
             "腺样体肥大", "失眠", "桥本甲状腺炎", "甲状腺结节", "脾胃病",
             "子宫内膜", "咳嗽", "痛经", "阴道炎", "小儿鼻炎", "小儿哮喘"],
            ensure_ascii=False,
        ),

        # ---- 未开放病种 ----
        "unopened_diseases": json.dumps(
            ["内容管理模型", "专病名称"],
            ensure_ascii=False,
        ),

        # ---- 主动任务列表 ----
        "initiative_task_list": json.dumps([
            {
                "name": "小方提醒患者任务",
                "inputParams": "",
                "description": "患者和小方说一段时间后提醒我来问诊，请计算对应的问诊提醒时间点。在该时间点执行任务：执行前先判断患者当前在不在问诊中，如果患者正在问诊，则不发送提醒；如果患者不在问诊中，则发送问诊提醒。",
                "type": "XIAOFANG_REMIND_PATIENT",
                "agentPrompt": "",
            },
            {
                "name": "小方唤醒消息任务",
                "inputParams": "",
                "description": "小方向患者发消息后，延时 5 分钟执行唤醒任务：执行前根据时间戳判断，若患者未回复新消息，且最新聊天记录里还没发过唤醒消息，则发送唤醒消息；否则不发送。",
                "type": "XIAOFANG_ACTIVATION_MESSAGE",
                "agentPrompt": "",
            },
        ], ensure_ascii=False),

        # ---- 其他上下文字段 ----
        "xf_qw_picture": "https://image.studio.dajiazhongyi.com/owl/720/ec16c2aa0f62b54c9097194e1f265f228523e144.png",
        "source_page": "首页",
        "chat_history": "[]",  # 首轮为空，后续动态更新
        "user_msg_timestamp": user_msg_timestamp,
        "patient_name": "模拟患者-AutoZenith",
        "tenant_id": 4,
        "current_time": current_time,
        "product_id": 2,
        "chat_record_id": str(uuid.uuid4().int)[:18],
        "channel": "企微",

        # ---- 核心：从前端配置中注入 ----
        "scenario": config.scenario,
        "union_id": f"autozenith-{uuid.uuid4().hex[:12]}",
        "identity_profile": config.identity_profile,
        "communication_style": config.communication_style,
        "previous_session_memory": None,
        "urgency_signal": "",
        "trance_id": str(uuid.uuid4().int)[:17],
        "externalUserId": f"autozenith-ext-{uuid.uuid4().hex[:8]}",
        "sys.files": [],
        "sys.user_id": "4117202",
        "sys.app_id": "5cdece40-9065-4913-a283-55a36383d55b",
        "sys.workflow_id": "6939f9fa-bef3-49ae-ae32-58865974fad5",
        "sys.workflow_run_id": str(uuid.uuid4()),
        "sys.query": "",
        "sys.dialogue_count": 1,
    }

    return inputs


async def run_conversation_loop(config: SimulationConfig) -> AsyncGenerator[str, None]:
    """
    核心对聊循环生成器
    使用 SSE 流式推送每一轮对话消息到前端

    流程：
    1. Simulator 生成开场白
    2. 将开场白发送给 Dify
    3. 拿到 Dify 回复 -> 推送给前端
    4. 将回复喂给 Simulator -> 生成下一句
    5. 重复直到达到 max_turns

    Yields:
        str: JSON 格式的 SSE 事件数据
    """

    # 初始化 Simulator Agent
    simulator = SimulatorAgent(
        identity_profile=config.identity_profile,
        communication_style=config.communication_style,
        scenario=config.scenario,
    )

    # 组装 Dify inputs
    dify_inputs = build_dify_inputs(config)

    # Dify 会话 ID，首轮为空
    dify_conversation_id = ""

    # 维护聊天历史（用于更新 chat_history 字段）
    chat_history = []

    # ---- 发送"开始"事件 ----
    yield json.dumps({
        "event": "start",
        "data": {
            "message": "对话模拟开始...",
            "config": {
                "scenario": config.scenario,
                "max_turns": config.max_turns,
                "mock_mode": settings.MOCK_DIFY,
            }
        }
    }, ensure_ascii=False)

    turn = 0

    try:
        for turn in range(1, config.max_turns + 1):
            # ========================================
            # 第一步：Simulator 生成患者消息
            # ========================================
            if turn == 1:
                simulator_msg = await simulator.generate_opening()
            else:
                simulator_msg = await simulator.generate_reply(dify_answer)

            # 推送 Simulator 消息到前端
            yield json.dumps({
                "event": "message",
                "data": {
                    "role": "simulator",
                    "content": simulator_msg,
                    "turn": turn,
                    "timestamp": datetime.now().isoformat(),
                }
            }, ensure_ascii=False)

            # 短暂延迟，让前端有时间渲染
            await asyncio.sleep(0.3)

            # ========================================
            # 第二步：将 Simulator 消息发送给 Dify
            # ========================================

            # 更新 chat_history
            chat_history.append({
                "content": simulator_msg,
                "role": "user",
                "timestamp": datetime.now().isoformat(),
            })
            dify_inputs["chat_history"] = json.dumps(chat_history, ensure_ascii=False)
            dify_inputs["sys.query"] = simulator_msg
            dify_inputs["sys.dialogue_count"] = turn

            # 推送"思考中"状态
            yield json.dumps({
                "event": "thinking",
                "data": {
                    "role": "dify",
                    "turn": turn,
                    "message": "Dify 客服正在思考...",
                }
            }, ensure_ascii=False)

            # 调用 Dify API
            dify_result = await dify_client.send_message(
                query=simulator_msg,
                inputs=dify_inputs,
                conversation_id=dify_conversation_id,
                user="autozenith-tester",
            )

            dify_answer = dify_result["answer"]
            dify_conversation_id = dify_result["conversation_id"]

            # 更新 chat_history
            chat_history.append({
                "content": dify_answer,
                "role": "assistant",
                "timestamp": datetime.now().isoformat(),
            })

            # 推送 Dify 回复到前端
            yield json.dumps({
                "event": "message",
                "data": {
                    "role": "dify",
                    "content": dify_answer,
                    "trace": dify_result.get("trace", []),
                    "turn": turn,
                    "timestamp": datetime.now().isoformat(),
                }
            }, ensure_ascii=False)

            # 轮次间延迟
            await asyncio.sleep(0.5)

    except Exception as e:
        error_type = type(e).__name__
        error_detail = str(e).strip() or repr(e)
        error_traceback = traceback.format_exc()

        logger.exception("对话过程中发生错误，turn=%s", turn)

        yield json.dumps({
            "event": "error",
            "data": {
                "message": f"对话过程中发生错误: {error_type}: {error_detail}",
                "error_type": error_type,
                "error_detail": error_detail,
                "traceback": error_traceback,
                "turn": turn,
            }
        }, ensure_ascii=False)

    # ---- 发送"结束"事件 ----
    yield json.dumps({
        "event": "done",
        "data": {
            "message": "对话模拟完成",
            "total_turns": config.max_turns,
            "conversation_id": dify_conversation_id,
        }
    }, ensure_ascii=False)


# ============================================
# API 路由
# ============================================

@app.get("/")
async def root():
    """健康检查"""
    return {
        "service": "AutoZenith",
        "status": "running",
        "mock_mode": settings.MOCK_DIFY,
    }


@app.post("/api/simulation/start")
async def start_simulation(config: SimulationConfig):
    """
    启动对话模拟

    接收前端配置参数，返回 SSE 流式事件
    前端通过 EventSource 或 fetch 接收实时对话消息

    Args:
        config: 模拟配置参数

    Returns:
        EventSourceResponse: SSE 事件流
    """
    return EventSourceResponse(
        run_conversation_loop(config),
        media_type="text/event-stream",
    )


@app.get("/api/config/defaults")
async def get_default_config():
    """
    获取默认配置信息
    前端可用于初始化表单
    """
    return {
        "scenario_options": ["初诊", "复诊"],
        "default_identity_profile": "患者：未知患者\n当前可用档案：\n- 本人（姓名: 张三）\n当问题涉及具体档案信息时，先确认是本人还是哪位家属。",
        "default_communication_style": "【沟通风格默认指引】\n- 语气：礼貌温和，亲切但不失专业\n- 节奏：一次只追问一个最关键的问题\n- 信任建立优先：初次接触先表达关心\n- 主动引导：说明你能帮助患者做什么\n- 避免：使用过于专业的医学术语",
        "default_max_turns": 5,
        "mock_mode": settings.MOCK_DIFY,
    }


# ============================================
# 应用启动入口
# ============================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  AutoZenith - AI 对话博弈测试平台")
    print(f"  Mock 模式: {'✅ 开启' if settings.MOCK_DIFY else '❌ 关闭'}")
    print(f"  服务地址: http://{settings.HOST}:{settings.PORT}")
    print("=" * 50)

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
