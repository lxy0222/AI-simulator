<template>
  <!-- ============================================
       AutoZenith - AI 对话博弈测试平台
       主应用布局：左侧配置面板 + 右侧聊天窗口
       ============================================ -->
  <div class="app-container">
    <!-- 背景装饰元素 -->
    <div class="bg-orb bg-orb-1"></div>
    <div class="bg-orb bg-orb-2"></div>
    <div class="bg-orb bg-orb-3"></div>

    <!-- 顶部导航栏 -->
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
      <p class="header-subtitle">AI 对话博弈测试平台 — 中医导诊智能体自动化评估</p>
    </header>

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 左侧：配置面板 -->
      <aside class="left-panel glass-card">
        <ConfigPanel
          :is-running="isRunning"
          :has-messages="messages.length > 0"
          :status-info="statusInfo"
          :status-class="statusClass"
          :is-mock-mode="isMockMode"
          @start="handleStartSimulation"
          @reset="handleReset"
        />
      </aside>

      <!-- 右侧：聊天窗口 -->
      <section class="right-panel glass-card">
        <ChatWindow
          :messages="messages"
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

// ============================================
// 状态管理
// ============================================

// 聊天消息列表
const messages = ref([])

// 运行状态
const isRunning = ref(false)
const isThinking = ref(false)
const currentTurn = ref(0)
const maxTurns = ref(5)

// 状态信息
const statusInfo = ref('')
const statusClass = ref('idle')

// Mock 模式标识
const isMockMode = ref(false)

// ============================================
// 初始化：获取默认配置
// ============================================
onMounted(async () => {
  try {
    const resp = await fetch('/api/config/defaults')
    if (resp.ok) {
      const data = await resp.json()
      isMockMode.value = data.mock_mode
      statusInfo.value = 'API 连接正常'
      statusClass.value = 'idle'
    }
  } catch {
    statusInfo.value = '后端未启动，请先运行 FastAPI 服务'
    statusClass.value = 'error'
  }
})

// ============================================
// 核心逻辑：使用 fetch + ReadableStream 读取 SSE
// ============================================
const handleStartSimulation = async (config) => {
  // 重置状态
  messages.value = []
  isRunning.value = true
  isThinking.value = false
  currentTurn.value = 0
  maxTurns.value = config.max_turns
  statusInfo.value = '正在初始化对话...'
  statusClass.value = 'running'

  try {
    // 发起 SSE 请求
    const response = await fetch('/api/simulation/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    // 使用 ReadableStream 解析 SSE 流
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // 解码并拼接到缓冲区
      buffer += decoder.decode(value, { stream: true })

      // 按换行分割处理每条消息
      const lines = buffer.split('\n')
      // 保留最后一行（可能不完整）
      buffer = lines.pop() || ''

      for (const line of lines) {
        // SSE 格式：data: {...}
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue

        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue

        try {
          const event = JSON.parse(jsonStr)
          handleSSEEvent(event)
        } catch {
          // 忽略 JSON 解析错误（可能是不完整的消息）
          console.warn('SSE 解析跳过:', jsonStr)
        }
      }
    }

    // 处理缓冲区中可能剩余的最后一条消息
    if (buffer.trim()) {
      const trimmed = buffer.trim()
      if (trimmed.startsWith('data:')) {
        const jsonStr = trimmed.slice(5).trim()
        try {
          const event = JSON.parse(jsonStr)
          handleSSEEvent(event)
        } catch {
          // 忽略
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

// ============================================
// 处理 SSE 事件
// ============================================
const handleSSEEvent = (event) => {
  const { event: eventType, data } = event

  switch (eventType) {
    case 'start':
      statusInfo.value = data.message || '对话已开始'
      if (data.config?.mock_mode) {
        isMockMode.value = true
      }
      break

    case 'message':
      // 收到对话消息（simulator 或 dify）
      messages.value.push({
        role: data.role,
        content: data.content,
        trace: data.trace || [],
        turn: data.turn,
        timestamp: data.timestamp,
      })
      currentTurn.value = data.turn
      isThinking.value = false
      statusInfo.value = `第 ${data.turn} 轮 - ${data.role === 'simulator' ? '患者发言' : '客服回复'}`
      break

    case 'thinking':
      // Dify 正在思考
      isThinking.value = true
      statusInfo.value = data.message || 'AI 正在思考...'
      break

    case 'error':
      ElMessage.error(data.message || '未知错误')
      statusInfo.value = data.message || '发生错误'
      statusClass.value = 'error'
      isThinking.value = false
      break

    case 'done':
      statusInfo.value = `${data.message} (共 ${data.total_turns} 轮)`
      statusClass.value = 'done'
      isThinking.value = false
      ElMessage.success('对话模拟完成！')
      break
  }
}

// ============================================
// 重置
// ============================================
const handleReset = () => {
  messages.value = []
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
