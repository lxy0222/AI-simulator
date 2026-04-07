<template>
  <div class="app-container">
    <div class="bg-orb bg-orb-1"></div>
    <div class="bg-orb bg-orb-2"></div>
    <div class="bg-orb bg-orb-3"></div>

    <header class="app-header">
      <div class="logo-area">
        <div class="logo-icon">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <circle cx="14" cy="14" r="12" stroke="url(#grad)" stroke-width="2.5" />
            <path d="M9 14L12.5 17.5L19 11" stroke="url(#grad)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="28" y2="28">
                <stop stop-color="#667eea"/>
                <stop offset="1" stop-color="#764ba2"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div class="logo-text">
          <h1>AutoZenith</h1>
          <span class="version-badge">v1.0</span>
        </div>
      </div>
      <p class="header-subtitle">医疗 Agent 测试框架 — 多模板、多画像、多轮评估</p>
    </header>

    <main class="main-content">
      <aside class="left-panel glass-card">
        <ConfigPanel
          :agent-templates="agentTemplates"
          :patient-profiles="patientProfiles"
          :default-request="defaultRequest"
          :is-running="isRunning"
          :has-messages="messages.length > 0"
          :status-info="statusInfo"
          :status-class="statusClass"
          :is-mock-mode="isMockMode"
          @start="handleStartSimulation"
          @reset="handleReset"
        />
      </aside>

      <section class="right-panel glass-card">
        <ChatWindow
          :messages="messages"
          :evaluation-report="evaluationReport"
          :run-info="runInfo"
          :agent-label="activeAgentLabel"
          :is-running="isRunning"
          :is-thinking="isThinking"
          :current-turn="currentTurn"
          :max-turns="maxTurns"
        />
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import ConfigPanel from './components/ConfigPanel.vue'
import ChatWindow from './components/ChatWindow.vue'

const messages = ref([])
const isRunning = ref(false)
const isThinking = ref(false)
const currentTurn = ref(0)
const maxTurns = ref(5)
const statusInfo = ref('')
const statusClass = ref('idle')
const isMockMode = ref(false)
const agentTemplates = ref([])
const patientProfiles = ref([])
const defaultRequest = ref(null)
const evaluationReport = ref(null)
const runInfo = ref(null)
const activeAgentLabel = ref('被测 Agent')

onMounted(async () => {
  try {
    const resp = await fetch('/api/config/defaults')
    if (resp.ok) {
      const data = await resp.json()
      isMockMode.value = data.mock_mode
      agentTemplates.value = data.agent_templates || []
      patientProfiles.value = data.patient_profiles || []
      defaultRequest.value = data.default_request || null
      const defaultTemplate = agentTemplates.value.find(
        (item) => item.id === data.default_request?.agent_template_id,
      )
      activeAgentLabel.value = defaultTemplate?.name || '被测 Agent'
      statusInfo.value = 'API 连接正常'
      statusClass.value = 'idle'
    }
  } catch {
    statusInfo.value = '后端未启动，请先运行 FastAPI 服务'
    statusClass.value = 'error'
  }
})

const handleStartSimulation = async (config) => {
  messages.value = []
  evaluationReport.value = null
  runInfo.value = null
  isRunning.value = true
  isThinking.value = false
  currentTurn.value = 0
  maxTurns.value = config.max_turns
  statusInfo.value = '正在初始化对话...'
  statusClass.value = 'running'
  activeAgentLabel.value = agentTemplates.value.find(
    (item) => item.id === config.agent_template_id,
  )?.name || '被测 Agent'

  try {
    const response = await fetch('/api/simulation/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue

        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue

        try {
          const event = JSON.parse(jsonStr)
          handleSSEEvent(event)
        } catch {
          console.warn('SSE 解析跳过:', jsonStr)
        }
      }
    }

    if (buffer.trim()) {
      const trimmed = buffer.trim()
      if (trimmed.startsWith('data:')) {
        const jsonStr = trimmed.slice(5).trim()
        try {
          const event = JSON.parse(jsonStr)
          handleSSEEvent(event)
        } catch {
        }
      }
    }
  } catch (error) {
    ElMessage.error('对话模拟出错: ' + error.message)
    statusInfo.value = '发生错误: ' + error.message
    statusClass.value = 'error'
  } finally {
    isRunning.value = false
    isThinking.value = false
  }
}

const handleSSEEvent = (event) => {
  const { event: eventType, data } = event

  switch (eventType) {
    case 'start':
      statusInfo.value = data.message || '对话已开始'
      runInfo.value = {
        runId: data.run_id,
        runFile: data.run_file,
      }
      if (data.config?.mock_mode) {
        isMockMode.value = true
      }
      if (data.config?.agent_template_name) {
        activeAgentLabel.value = data.config.agent_template_name
      }
      break

    case 'message':
      messages.value.push({
        role: data.role,
        content: data.content,
        trace: data.trace || [],
        perceptions: data.perceptions || {},
        turn: data.turn,
        timestamp: data.timestamp,
      })
      currentTurn.value = data.turn
      isThinking.value = false
      statusInfo.value = `第 ${data.turn} 轮 - ${data.role === 'simulator' ? '患者发言' : `${activeAgentLabel.value} 回复`}`
      break

    case 'thinking':
      isThinking.value = true
      statusInfo.value = data.message || 'AI 正在思考...'
      break

    case 'evaluation':
      evaluationReport.value = data
      statusInfo.value = '评估报告已生成'
      break

    case 'error':
      ElMessage.error(data.message || '未知错误')
      statusInfo.value = data.message || '发生错误'
      statusClass.value = 'error'
      isThinking.value = false
      break

    case 'done':
      statusInfo.value = data.total_turns
        ? `${data.message} (共 ${data.total_turns} 轮)`
        : (data.message || '运行结束')
      statusClass.value = data.status === 'failed' ? 'error' : 'done'
      isThinking.value = false
      runInfo.value = {
        ...(runInfo.value || {}),
        runId: data.run_id || runInfo.value?.runId,
        runFile: data.run_file || runInfo.value?.runFile,
        status: data.status,
      }
      if (data.status === 'failed') {
        ElMessage.error('测试运行异常结束')
      } else {
        ElMessage.success('对话模拟完成！')
      }
      break
  }
}

const handleReset = () => {
  messages.value = []
  evaluationReport.value = null
  runInfo.value = null
  isRunning.value = false
  isThinking.value = false
  currentTurn.value = 0
  statusInfo.value = '已重置'
  statusClass.value = 'idle'
}
</script>

<style scoped>
/* ---- 全局容器 ---- */
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
  padding: 0 20px 20px;
}

/* ---- 背景装饰光球 ---- */
.bg-orb {
  position: fixed;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.15;
  pointer-events: none;
  z-index: 0;
}

.bg-orb-1 {
  width: 500px;
  height: 500px;
  background: #667eea;
  top: -150px;
  right: -100px;
  animation: gradientShift 8s ease-in-out infinite;
}

.bg-orb-2 {
  width: 400px;
  height: 400px;
  background: #764ba2;
  bottom: -100px;
  left: -100px;
  animation: gradientShift 12s ease-in-out infinite reverse;
}

.bg-orb-3 {
  width: 300px;
  height: 300px;
  background: #10b981;
  top: 50%;
  left: 40%;
  opacity: 0.06;
  animation: gradientShift 10s ease-in-out infinite;
}

/* ---- 顶部导航 ---- */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 8px;
  flex-shrink: 0;
  z-index: 1;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 42px;
  height: 42px;
  background: rgba(102, 126, 234, 0.12);
  border: 1px solid rgba(102, 126, 234, 0.2);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-text h1 {
  font-size: 22px;
  font-weight: 700;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.version-badge {
  font-size: 10px;
  padding: 2px 8px;
  background: rgba(102, 126, 234, 0.15);
  color: var(--primary-light);
  border-radius: var(--radius-full);
  font-weight: 600;
}

.header-subtitle {
  font-size: 13px;
  color: var(--text-muted);
}

/* ---- 主内容 ---- */
.main-content {
  flex: 1;
  display: flex;
  gap: 20px;
  min-height: 0;
  z-index: 1;
}

.left-panel {
  width: 380px;
  flex-shrink: 0;
  overflow: hidden;
}

.right-panel {
  flex: 1;
  overflow: hidden;
}

/* ---- 响应式 ---- */
@media (max-width: 1024px) {
  .main-content {
    flex-direction: column;
  }

  .left-panel {
    width: 100%;
    max-height: 40vh;
  }

  .header-subtitle {
    display: none;
  }
}
</style>
