<template>
  <!-- ============================================
       配置面板组件
       左侧表单区域，用于配置模拟患者参数
       ============================================ -->
  <div class="config-panel">
    <!-- 面板标题 -->
    <div class="panel-header">
      <div class="header-icon">
        <el-icon :size="22"><Setting /></el-icon>
      </div>
      <div class="header-text">
        <h2>模拟配置</h2>
        <p>设定模拟患者的参数</p>
      </div>
    </div>

    <!-- 配置表单 -->
    <el-form
      :model="form"
      label-position="top"
      class="config-form"
      :disabled="isRunning"
    >
      <!-- 就诊场景 -->
      <el-form-item label="就诊场景">
        <el-select v-model="form.scenario" placeholder="选择场景" style="width: 100%">
          <el-option label="初诊" value="初诊" />
          <el-option label="复诊" value="复诊" />
        </el-select>
      </el-form-item>

      <!-- 患者画像 -->
      <el-form-item label="患者画像">
        <el-input
          v-model="form.identity_profile"
          type="textarea"
          :rows="5"
          placeholder="描述模拟患者的身份背景..."
          resize="vertical"
        />
      </el-form-item>

      <!-- 沟通风格 -->
      <el-form-item label="沟通风格">
        <el-input
          v-model="form.communication_style"
          type="textarea"
          :rows="4"
          placeholder="描述患者的说话方式和性格特点..."
          resize="vertical"
        />
      </el-form-item>

      <!-- 最大对话轮数 -->
      <el-form-item label="最大对话轮数">
        <el-input-number
          v-model="form.max_turns"
          :min="1"
          :max="20"
          :step="1"
          style="width: 100%"
        />
      </el-form-item>

      <!-- 操作按钮 -->
      <div class="form-actions">
        <el-button
          type="primary"
          size="large"
          :loading="isRunning"
          :disabled="isRunning"
          @click="handleStart"
          class="start-btn"
        >
          <el-icon v-if="!isRunning"><VideoPlay /></el-icon>
          <span>{{ isRunning ? '模拟进行中...' : '启动对话模拟' }}</span>
        </el-button>

        <el-button
          size="large"
          :disabled="!hasMessages"
          @click="handleReset"
          class="reset-btn"
        >
          <el-icon><RefreshRight /></el-icon>
          <span>重置</span>
        </el-button>
      </div>
    </el-form>

    <!-- 状态信息 -->
    <div class="status-bar" v-if="statusInfo">
      <div class="status-indicator" :class="statusClass"></div>
      <span>{{ statusInfo }}</span>
    </div>

    <!-- Mock 模式提示 -->
    <div class="mock-badge" v-if="isMockMode">
      <el-icon><Warning /></el-icon>
      <span>Mock 模式</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

// ---- Props & Emits ----
const props = defineProps({
  isRunning: { type: Boolean, default: false },
  hasMessages: { type: Boolean, default: false },
  statusInfo: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  isMockMode: { type: Boolean, default: false },
})

const emit = defineEmits(['start', 'reset'])

// ---- 表单数据 ----
const form = ref({
  scenario: '初诊',
  identity_profile: '一位焦虑的母亲，带6岁女儿来看小儿鼻炎。\n女儿经常鼻塞、流清涕，晚上睡觉张口呼吸。\n之前在西医院看过，用了喷鼻药效果不好，想尝试中医治疗。',
  communication_style: '说话简短急切，会用短句表达。\n有些焦虑和不耐烦，但对医生还是比较尊重。\n喜欢追问具体的治疗方案和时间。',
  max_turns: 5,
})

// ---- 事件处理 ----
const handleStart = () => {
  emit('start', { ...form.value })
}

const handleReset = () => {
  emit('reset')
}
</script>

<style scoped>
.config-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px;
  overflow-y: auto;
}

/* ---- 面板标题 ---- */
.panel-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.header-icon {
  width: 44px;
  height: 44px;
  background: var(--primary-gradient);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.header-text h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.header-text p {
  font-size: 13px;
  color: var(--text-muted);
}

/* ---- 表单区域 ---- */
.config-form {
  flex: 1;
}

.config-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.config-form :deep(.el-form-item__label) {
  font-size: 13px;
  padding-bottom: 6px;
}

/* ---- 操作按钮 ---- */
.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.start-btn {
  flex: 1;
  background: var(--primary-gradient) !important;
  border: none !important;
  border-radius: var(--radius-md) !important;
  font-weight: 600;
  letter-spacing: 0.5px;
  height: 44px !important;
  transition: all var(--transition-normal);
}

.start-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-glow);
}

.start-btn:active:not(:disabled) {
  transform: translateY(0);
}

.reset-btn {
  background: rgba(255, 255, 255, 0.06) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: var(--radius-md) !important;
  color: var(--text-secondary) !important;
  height: 44px !important;
  transition: all var(--transition-normal);
}

.reset-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1) !important;
  color: var(--text-primary) !important;
}

/* ---- 状态栏 ---- */
.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-muted);
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-indicator.running {
  background: var(--success-color);
  animation: pulse 1.5s infinite;
}

.status-indicator.done {
  background: var(--primary-color);
}

.status-indicator.error {
  background: var(--danger-color);
}

.status-indicator.idle {
  background: var(--text-muted);
}

/* ---- Mock 模式标记 ---- */
.mock-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--warning-color);
}
</style>
