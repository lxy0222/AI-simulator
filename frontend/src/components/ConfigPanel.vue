<template>
  <div class="config-panel">
    <div class="panel-header">
      <div class="header-icon">
        <el-icon :size="22"><Setting /></el-icon>
      </div>
      <div class="header-text">
        <h2>测试配置</h2>
        <p>选择 Agent 模板、患者画像和动态测试入参</p>
      </div>
    </div>

    <el-form
      :model="form"
      label-position="top"
      class="config-form"
      :disabled="isRunning || !selectedTemplate"
    >
      <el-form-item label="被测 Agent 模板">
        <el-select v-model="form.agent_template_id" placeholder="选择 Agent 模板" style="width: 100%">
          <el-option
            v-for="template in agentTemplates"
            :key="template.id"
            :label="template.name"
            :value="template.id"
          />
        </el-select>
      </el-form-item>

      <div v-if="selectedTemplate" class="template-intro">
        <div class="template-name">{{ selectedTemplate.name }}</div>
        <div class="template-desc">{{ selectedTemplate.description }}</div>
      </div>

      <el-form-item label="患者画像">
        <el-select v-model="form.patient_profile_id" placeholder="选择患者画像" style="width: 100%">
          <el-option
            v-for="profile in patientProfiles"
            :key="profile.id"
            :label="profile.name"
            :value="profile.id"
          />
        </el-select>
      </el-form-item>

      <div v-if="selectedPatient" class="patient-card">
        <div class="patient-card-title">
          <span>{{ selectedPatient.name }}</span>
          <span>{{ patientMeta }}</span>
        </div>
        <div class="patient-card-complaint">{{ selectedPatient.chief_complaint }}</div>
        <div class="patient-tags">
          <span
            v-for="tag in selectedPatient.reusable_tags || []"
            :key="tag"
            class="patient-tag"
          >
            {{ tag }}
          </span>
        </div>
      </div>

      <template v-for="field in templateFields" :key="field.name">
        <el-form-item :label="field.label">
          <el-select
            v-if="field.type === 'select'"
            :model-value="getFieldValue(field)"
            @update:model-value="(value) => setFieldValue(field, value)"
            style="width: 100%"
          >
            <el-option
              v-for="option in field.options || []"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>

          <el-input
            v-else-if="field.type === 'textarea'"
            :model-value="getFieldValue(field)"
            @update:model-value="(value) => setFieldValue(field, value)"
            type="textarea"
            :rows="field.name === 'boundary_conditions' ? 4 : 3"
            :placeholder="field.placeholder || field.help_text"
            resize="vertical"
          />

          <el-input-number
            v-else-if="field.type === 'number'"
            :model-value="getFieldValue(field)"
            @update:model-value="(value) => setFieldValue(field, value)"
            :min="field.min ?? 0"
            :max="field.max ?? 999"
            :step="1"
            style="width: 100%"
          />

          <el-switch
            v-else-if="field.type === 'switch'"
            :model-value="getFieldValue(field)"
            @update:model-value="(value) => setFieldValue(field, value)"
          />

          <el-input
            v-else
            :model-value="getFieldValue(field)"
            @update:model-value="(value) => setFieldValue(field, value)"
            :placeholder="field.placeholder || field.help_text"
          />
        </el-form-item>
      </template>

      <el-form-item label="本轮患者补充说明">
        <el-input
          v-model="form.patient_notes"
          type="textarea"
          :rows="3"
          placeholder="可补充本轮测试想强调的情绪、限制条件或特殊目标"
          resize="vertical"
        />
      </el-form-item>

      <el-form-item label="最大对话轮数">
        <el-input-number
          v-model="form.max_turns"
          :min="1"
          :max="20"
          :step="1"
          style="width: 100%"
        />
      </el-form-item>

      <div class="form-actions">
        <el-button
          type="primary"
          size="large"
          :loading="isRunning"
          :disabled="isRunning || !selectedTemplate || !selectedPatient"
          @click="handleStart"
          class="start-btn"
        >
          <el-icon v-if="!isRunning"><VideoPlay /></el-icon>
          <span>{{ isRunning ? '测试进行中...' : '启动对话测试' }}</span>
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

    <div class="status-bar" v-if="statusInfo">
      <div class="status-indicator" :class="statusClass"></div>
      <span>{{ statusInfo }}</span>
    </div>

    <div class="mock-badge" v-if="isMockMode">
      <el-icon><Warning /></el-icon>
      <span>Mock 模式</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  agentTemplates: { type: Array, default: () => [] },
  patientProfiles: { type: Array, default: () => [] },
  defaultRequest: { type: Object, default: null },
  isRunning: { type: Boolean, default: false },
  hasMessages: { type: Boolean, default: false },
  statusInfo: { type: String, default: '' },
  statusClass: { type: String, default: '' },
  isMockMode: { type: Boolean, default: false },
})

const emit = defineEmits(['start', 'reset'])

const emptyForm = () => ({
  agent_template_id: '',
  patient_profile_id: '',
  scenario: '',
  initial_state: '',
  boundary_conditions: '',
  patient_notes: '',
  max_turns: 5,
  extra_inputs: {},
})

const form = ref(emptyForm())

const selectedTemplate = computed(() =>
  props.agentTemplates.find((item) => item.id === form.value.agent_template_id),
)

const selectedPatient = computed(() =>
  props.patientProfiles.find((item) => item.id === form.value.patient_profile_id),
)

const patientMeta = computed(() => {
  if (!selectedPatient.value) return ''
  const age = selectedPatient.value.age ? `${selectedPatient.value.age}岁` : '年龄未知'
  return `${selectedPatient.value.gender || '性别未知'} / ${age}`
})

const templateFields = computed(() => selectedTemplate.value?.input_schema || [])

watch(
  () => props.defaultRequest,
  (request) => {
    if (!request) return
    form.value = normalizeForm(request, props.agentTemplates)
  },
  { immediate: true, deep: true },
)

watch(
  () => form.value.agent_template_id,
  (nextId, prevId) => {
    if (!nextId) return
    if (nextId === prevId) return

    const template = props.agentTemplates.find((item) => item.id === nextId)
    if (!template) return

    const preservedPatientId =
      form.value.patient_profile_id || props.defaultRequest?.patient_profile_id || props.patientProfiles[0]?.id || ''

    form.value = {
      ...emptyForm(),
      agent_template_id: nextId,
      patient_profile_id: preservedPatientId,
      scenario: template.default_scenario || '',
      initial_state: template.default_initial_state || '',
      boundary_conditions: template.default_boundary_conditions || '',
      patient_notes: form.value.patient_notes || '',
      max_turns: form.value.max_turns || props.defaultRequest?.max_turns || 5,
      extra_inputs: buildExtraInputs(template),
    }
  },
)

const getFieldValue = (field) => {
  if (field.name === 'scenario') return form.value.scenario
  if (field.name === 'initial_state') return form.value.initial_state
  if (field.name === 'boundary_conditions') return form.value.boundary_conditions
  return form.value.extra_inputs[field.name]
}

const setFieldValue = (field, value) => {
  if (field.name === 'scenario') {
    form.value.scenario = value
  } else if (field.name === 'initial_state') {
    form.value.initial_state = value
  } else if (field.name === 'boundary_conditions') {
    form.value.boundary_conditions = value
  } else {
    form.value.extra_inputs = {
      ...form.value.extra_inputs,
      [field.name]: value,
    }
  }
}

const handleStart = () => {
  emit('start', JSON.parse(JSON.stringify(form.value)))
}

const handleReset = () => {
  emit('reset')
}

function normalizeForm(request, templates) {
  const template = templates.find((item) => item.id === request.agent_template_id) || templates[0]
  return {
    agent_template_id: request.agent_template_id || template?.id || '',
    patient_profile_id: request.patient_profile_id || '',
    scenario: request.scenario || template?.default_scenario || '',
    initial_state: request.initial_state || template?.default_initial_state || '',
    boundary_conditions: request.boundary_conditions || template?.default_boundary_conditions || '',
    patient_notes: request.patient_notes || '',
    max_turns: request.max_turns || 5,
    extra_inputs: {
      ...buildExtraInputs(template),
      ...(request.extra_inputs || {}),
    },
  }
}

function buildExtraInputs(template) {
  if (!template?.input_schema) return {}
  return template.input_schema.reduce((acc, field) => {
    if (['scenario', 'initial_state', 'boundary_conditions'].includes(field.name)) {
      return acc
    }
    acc[field.name] = field.default
    return acc
  }, {})
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

.panel-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
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

.config-form {
  flex: 1;
}

.config-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.config-form :deep(.el-form-item__label) {
  font-size: 13px;
  padding-bottom: 6px;
}

.template-intro,
.patient-card {
  margin-bottom: 18px;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.template-name,
.patient-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.template-desc,
.patient-card-complaint {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.patient-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.patient-tag {
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(102, 126, 234, 0.16);
  color: var(--primary-light);
}

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

.status-indicator.error {
  background: var(--danger-color);
}

.status-indicator.done {
  background: var(--primary-light);
}

.status-indicator.idle {
  background: rgba(255, 255, 255, 0.2);
}

.mock-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  margin-top: 14px;
  padding: 6px 10px;
  border-radius: var(--radius-full);
  background: rgba(245, 158, 11, 0.12);
  color: var(--warning-color);
  font-size: 12px;
}
</style>
