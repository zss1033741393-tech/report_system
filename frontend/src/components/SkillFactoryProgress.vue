<template>
  <div class="sfp">
    <div class="sfp__title">看网能力创建</div>
    <div class="sfp__steps">
      <div v-for="(step, i) in steps" :key="step.key" :class="['sfp__step', stepClass(step)]">
        <span class="sfp__icon">
          <span v-if="step.status==='done'">✓</span>
          <span v-else-if="step.status==='running'" class="sfp__spin"></span>
          <span v-else>{{ i + 1 }}</span>
        </span>
        <span class="sfp__label">{{ step.label }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({ designSteps: { type: Array, default: () => [] } })

const STEP_DEFS = [
  { key: 'intent_understand', label: '意图理解' },
  { key: 'struct_extract', label: '信息提取' },
  { key: 'outline_design', label: '大纲生成' },
  { key: 'data_binding', label: '数据绑定' },
  { key: 'report_preview', label: '报告预览' },
  { key: 'skill_persist', label: '能力沉淀' },
]

const steps = reactive(STEP_DEFS.map(d => ({ ...d, status: 'pending' })))

watch(() => props.designSteps, (ds) => {
  for (const ev of ds) {
    const found = steps.find(s => s.key === ev.step)
    if (found) found.status = ev.status
  }
}, { deep: true })

function stepClass(step) {
  return {
    'sfp__step--done': step.status === 'done',
    'sfp__step--running': step.status === 'running',
    'sfp__step--pending': step.status === 'pending',
  }
}
</script>

<style scoped>
.sfp { margin: 10px 0; padding: 12px 16px; background: var(--c-bg-muted); border-radius: 10px; border: 1px solid var(--c-border) }
.sfp__title { font-size: 13px; font-weight: 600; color: var(--c-text-secondary); margin-bottom: 10px }
.sfp__steps { display: flex; gap: 4px }
.sfp__step { display: flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 16px; font-size: 12px; background: var(--c-bg-subtle); color: var(--c-text-tertiary); transition: all .3s }
.sfp__step--done { background: var(--c-success-bg); color: var(--c-success) }
.sfp__step--running { background: var(--c-primary-bg); color: var(--c-primary) }
.sfp__icon { width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700 }
.sfp__label { white-space: nowrap }
.sfp__spin { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--c-border); border-top-color: var(--c-primary); border-radius: 50%; animation: spin .8s linear infinite }
@keyframes spin { to { transform: rotate(360deg) } }
</style>
