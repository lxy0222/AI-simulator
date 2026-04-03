<template>
  <div class="chat-window">
    <div class="chat-header">
      <div class="chat-header-left">
        <div class="avatar-group">
          <div class="avatar simulator-avatar" title="模拟患者">
            <span>患</span>
          </div>
          <div class="vs-badge">VS</div>
          <div class="avatar dify-avatar" title="Dify 客服">
            <span>方</span>
          </div>
        </div>
        <div class="chat-title">
          <h3>AI 对话博弈</h3>
          <p class="chat-subtitle">
            {{ isRunning ? `第 ${currentTurn} 轮对话中...` : (messages.length > 0 ? '对话已结束' : '等待启动') }}
          </p>
        </div>
      </div>
      <div class="chat-header-right">
        <div class="turn-badge" v-if="messages.length > 0">
          <el-icon><ChatDotRound /></el-icon>
          <span>{{ Math.ceil(messages.length / 2) }} 轮</span>
        </div>
      </div>
    </div>

    <div class="chat-body" ref="chatBodyRef">
      <div class="empty-state" v-if="messages.length === 0 && !isRunning">
        <div class="empty-icon">
          <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
            <circle cx="40" cy="40" r="38" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
            <path d="M24 35C24 29.477 28.477 25 34 25H46C51.523 25 56 29.477 56 35V42C56 47.523 51.523 52 46 52H38L30 58V52H34C28.477 52 24 47.523 24 42V35Z" fill="rgba(102,126,234,0.15)" stroke="rgba(102,126,234,0.4)" stroke-width="1.5"/>
            <circle cx="34" cy="38.5" r="2" fill="rgba(102,126,234,0.6)"/>
            <circle cx="40" cy="38.5" r="2" fill="rgba(102,126,234,0.6)"/>
            <circle cx="46" cy="38.5" r="2" fill="rgba(102,126,234,0.6)"/>
          </svg>
        </div>
        <p class="empty-title">等待对话开始</p>
        <p class="empty-desc">配置左侧参数并点击"启动对话模拟"</p>
      </div>

      <div
        v-for="(msg, index) in messages"
        :key="index"
        class="message-row"
        :class="msg.role"
      >
        <div class="msg-avatar" :class="msg.role + '-avatar'">
          <span>{{ msg.role === 'simulator' ? '患' : '方' }}</span>
        </div>

        <div class="msg-bubble-wrapper">
          <div class="msg-role-label">
            {{ msg.role === 'simulator' ? '模拟患者' : 'Dify 客服（小方）' }}
            <span class="msg-turn">第{{ msg.turn }}轮</span>
          </div>

          <div class="msg-bubble" :class="msg.role + '-bubble'">
            <template v-if="msg.role === 'dify' && hasTrace(msg)">
              <div class="trace-shell">
                <div class="trace-shell-header">
                  <span class="trace-shell-title">思考轨迹</span>
                  <span class="trace-shell-count">{{ msg.trace.length }} 条</span>
                </div>

                <div class="trace-timeline">
                  <details
                    v-for="(traceItem, traceIndex) in msg.trace"
                    :key="traceItem.id || traceIndex"
                    class="trace-item"
                  >
                    <summary class="trace-summary">
                      <div class="trace-summary-main">
                        <span class="trace-dot"></span>
                        <span class="trace-title">{{ getTraceTitle(traceItem, traceIndex) }}</span>
                        <span
                          v-for="toolName in traceItem.tool_names || []"
                          :key="toolName"
                          class="trace-badge tool-badge"
                        >
                          {{ toolName }}
                        </span>
                      </div>
                      <span class="trace-time">{{ formatTime(traceItem.created_at || msg.timestamp) }}</span>
                    </summary>

                    <div class="trace-detail">
                      <div v-if="traceItem.thought" class="trace-block">
                        <div class="trace-label">思考内容</div>
                        <pre class="trace-pre">{{ traceItem.thought }}</pre>
                      </div>

                      <div v-if="(traceItem.tool_names || []).length" class="trace-block">
                        <div class="trace-label">工具调用</div>
                        <div class="trace-tools">
                          <span
                            v-for="toolName in traceItem.tool_names"
                            :key="toolName"
                            class="trace-badge"
                          >
                            {{ toolName }}
                          </span>
                        </div>
                      </div>

                      <div v-if="hasStructuredValue(traceItem.tool_input)" class="trace-block">
                        <div class="trace-label">输入参数</div>
                        <pre class="trace-pre">{{ formatStructured(traceItem.tool_input) }}</pre>
                      </div>

                      <div v-if="hasStructuredValue(traceItem.observation)" class="trace-block">
                        <div class="trace-label">输出结果</div>
                        <pre class="trace-pre">{{ formatStructured(traceItem.observation) }}</pre>
                      </div>
                    </div>
                  </details>
                </div>
              </div>
            </template>

            <div class="final-answer">
              <div v-if="msg.role === 'dify' && hasTrace(msg)" class="final-answer-label">最终回复</div>
              <span class="msg-text">{{ msg.content }}</span>
            </div>
          </div>

          <div class="msg-time">{{ formatTime(msg.timestamp) }}</div>
        </div>
      </div>

      <div class="message-row dify thinking-row" v-if="isThinking">
        <div class="msg-avatar dify-avatar">
          <span>方</span>
        </div>
        <div class="msg-bubble-wrapper">
          <div class="msg-role-label">Dify 客服（小方）</div>
          <div class="msg-bubble dify-bubble typing-indicator">
            <div class="typing-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-footer" v-if="isRunning || messages.length > 0">
      <div class="progress-info">
        <span>对话进度</span>
        <span>{{ Math.ceil(messages.length / 2) }} / {{ maxTurns }} 轮</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  isRunning: { type: Boolean, default: false },
  isThinking: { type: Boolean, default: false },
  currentTurn: { type: Number, default: 0 },
  maxTurns: { type: Number, default: 5 },
})

const chatBodyRef = ref(null)

const scrollToBottom = () => {
  nextTick(() => {
    if (chatBodyRef.value) {
      chatBodyRef.value.scrollTo({
        top: chatBodyRef.value.scrollHeight,
        behavior: 'smooth',
      })
    }
  })
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
)

watch(
  () => props.isThinking,
  () => scrollToBottom(),
)

const progressPercent = computed(() => {
  if (props.maxTurns === 0) return 0
  return Math.min((Math.ceil(props.messages.length / 2) / props.maxTurns) * 100, 100)
})

const hasTrace = (msg) => Array.isArray(msg.trace) && msg.trace.length > 0

const getTraceTitle = (traceItem, index) => {
  const position = traceItem?.position || index + 1
  const hasTools = Array.isArray(traceItem?.tool_names) && traceItem.tool_names.length > 0
  return hasTools ? `第 ${position} 轮思考与工具调用` : `第 ${position} 轮思考`
}

const hasStructuredValue = (value) => {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

const formatStructured = (value) => {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.simulator-avatar {
  background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
  color: var(--text-primary);
  border: 2px solid rgba(255, 255, 255, 0.15);
}

.dify-avatar {
  background: var(--primary-gradient);
  color: white;
  border: 2px solid rgba(102, 126, 234, 0.4);
}

.vs-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  padding: 2px 6px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: var(--radius-sm);
}

.chat-title h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.chat-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.turn-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: rgba(102, 126, 234, 0.1);
  border: 1px solid rgba(102, 126, 234, 0.2);
  border-radius: var(--radius-full);
  font-size: 12px;
  color: var(--primary-light);
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.empty-desc {
  font-size: 13px;
}

.message-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.message-row.simulator {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}

.simulator-avatar,
.simulator-avatar span,
.msg-avatar.simulator-avatar {
  color: var(--text-primary);
}

.msg-bubble-wrapper {
  max-width: min(78%, 860px);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.message-row.simulator .msg-bubble-wrapper {
  align-items: flex-end;
}

.msg-role-label {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 8px;
}

.msg-turn {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}

.msg-bubble {
  padding: 14px 16px;
  border-radius: 18px;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.18);
}

.simulator-bubble {
  background: var(--bubble-simulator);
  color: var(--bubble-simulator-text);
  border-top-right-radius: 6px;
}

.dify-bubble {
  background: var(--bubble-dify);
  color: var(--bubble-dify-text);
  border-top-left-radius: 6px;
}

.msg-text {
  display: block;
  white-space: pre-wrap;
  line-height: 1.72;
  word-break: break-word;
}

.msg-time {
  font-size: 11px;
  color: var(--text-muted);
}

.trace-shell {
  margin-bottom: 14px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(11, 18, 43, 0.26);
  border: 1px solid rgba(255, 255, 255, 0.14);
}

.trace-shell-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.trace-shell-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.trace-shell-count {
  font-size: 11px;
  opacity: 0.72;
}

.trace-timeline {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-timeline::before {
  content: '';
  position: absolute;
  left: 9px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: rgba(255, 255, 255, 0.14);
}

.trace-item {
  position: relative;
  margin-left: 0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.trace-item[open] {
  background: rgba(255, 255, 255, 0.12);
}

.trace-summary {
  list-style: none;
  cursor: pointer;
  padding: 12px 14px 12px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.trace-summary::-webkit-details-marker {
  display: none;
}

.trace-summary-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.trace-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.1);
  position: absolute;
  left: 5px;
}

.trace-title {
  font-size: 13px;
  font-weight: 600;
}

.trace-time {
  flex-shrink: 0;
  font-size: 11px;
  opacity: 0.76;
}

.trace-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 11px;
  line-height: 1.2;
}

.tool-badge {
  background: rgba(255, 241, 118, 0.18);
}

.trace-detail {
  padding: 0 14px 14px 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.trace-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trace-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0.82;
}

.trace-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-pre {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(2, 6, 23, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: inherit;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.final-answer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.final-answer-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  opacity: 0.86;
}

.thinking-row {
  opacity: 0.92;
}

.typing-indicator {
  min-width: 96px;
}

.typing-dots {
  display: flex;
  align-items: center;
  gap: 6px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.88);
  animation: blink 1.2s infinite ease-in-out;
}

.typing-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

.chat-footer {
  padding: 16px 24px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-muted);
  font-size: 12px;
}

.progress-bar {
  width: 100%;
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--primary-gradient);
  transition: width 0.35s ease;
}

@keyframes blink {
  0%, 80%, 100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-1px);
  }
}

@media (max-width: 900px) {
  .chat-header,
  .chat-body,
  .chat-footer {
    padding-left: 16px;
    padding-right: 16px;
  }

  .msg-bubble-wrapper {
    max-width: calc(100% - 48px);
  }

  .trace-summary {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
