<template>
  <div class="mp">
    <div class="mp__header">
      <div class="mp__title">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6.5" stroke="var(--c-primary)" stroke-width="1.5"/><path d="M8 5v3l2 2" stroke="var(--c-primary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        跨对话记忆
      </div>
      <button class="mp__clear" :disabled="clearing || !hasFacts" @click="clearMemory" title="清除记忆">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 3h10M5 3V2h4v1M3 3l1 9h6l1-9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
        清除
      </button>
    </div>

    <div v-if="loading" class="mp__loading">
      <span class="mp__spin"></span>
      <span>加载记忆中...</span>
    </div>

    <div v-else-if="!hasFacts" class="mp__empty">
      <svg width="32" height="32" viewBox="0 0 32 32" fill="none" style="opacity:0.3"><circle cx="16" cy="16" r="13" stroke="var(--c-text-tertiary)" stroke-width="1.5"/><path d="M16 10v6l4 4" stroke="var(--c-text-tertiary)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <p>暂无跨对话记忆</p>
      <p class="mp__empty-hint">每轮对话结束后自动提取关键信息</p>
    </div>

    <div v-else class="mp__facts">
      <div v-for="(fact, i) in facts" :key="i" class="mp__fact">
        <div class="mp__fact-content">{{ fact.content }}</div>
        <div class="mp__fact-meta">
          <span class="mp__fact-conf" :class="confClass(fact.confidence)">
            {{ confLabel(fact.confidence) }}
          </span>
          <span v-if="fact.source" class="mp__fact-src">{{ fact.source }}</span>
        </div>
      </div>
    </div>

    <div v-if="error" class="mp__error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  sessionId: { type: String, default: '' },
})

const loading = ref(false)
const clearing = ref(false)
const facts = ref([])
const error = ref('')

const hasFacts = computed(() => facts.value.length > 0)

function confLabel(c) {
  if (!c) return '一般'
  if (c >= 0.8) return '高置信'
  if (c >= 0.5) return '中等'
  return '低置信'
}
function confClass(c) {
  if (!c) return 'mp__fact-conf--med'
  if (c >= 0.8) return 'mp__fact-conf--high'
  if (c >= 0.5) return 'mp__fact-conf--med'
  return 'mp__fact-conf--low'
}

async function loadMemory() {
  if (!props.sessionId) { facts.value = []; return }
  loading.value = true; error.value = ''
  try {
    const res = await fetch(`/api/v1/memory/${props.sessionId}`)
    const data = await res.json()
    facts.value = data?.memory?.facts || []
  } catch (e) {
    error.value = '加载记忆失败'
    facts.value = []
  } finally {
    loading.value = false
  }
}

async function clearMemory() {
  if (!props.sessionId || clearing.value) return
  clearing.value = true; error.value = ''
  try {
    await fetch(`/api/v1/memory/${props.sessionId}`, { method: 'DELETE' })
    facts.value = []
  } catch (e) {
    error.value = '清除记忆失败'
  } finally {
    clearing.value = false
  }
}

watch(() => props.sessionId, () => loadMemory(), { immediate: true })
</script>

<style scoped>
.mp { display: flex; flex-direction: column; height: 100%; font-size: var(--text-sm) }

.mp__header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; border-bottom: 1px solid var(--c-border-light); flex-shrink: 0 }
.mp__title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--c-text); font-size: var(--text-base) }

.mp__clear { display: flex; align-items: center; gap: 4px; padding: 4px 10px; border: 1px solid var(--c-border); border-radius: var(--r-sm); background: transparent; color: var(--c-text-secondary); cursor: pointer; font-size: var(--text-xs); transition: all var(--duration) var(--ease) }
.mp__clear:hover:not(:disabled) { border-color: var(--c-danger, #ef4444); color: var(--c-danger, #ef4444) }
.mp__clear:disabled { opacity: 0.4; cursor: not-allowed }

.mp__loading { flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--c-text-tertiary) }
.mp__spin { width: 16px; height: 16px; border: 2px solid var(--c-border); border-top-color: var(--c-primary); border-radius: 50%; animation: spin .7s linear infinite; flex-shrink: 0 }
@keyframes spin { to { transform: rotate(360deg) } }

.mp__empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--c-text-tertiary); text-align: center; padding: var(--sp-xl) }
.mp__empty p { margin: 0; font-size: var(--text-sm) }
.mp__empty-hint { font-size: var(--text-xs) !important; opacity: 0.7 }

.mp__facts { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px }

.mp__fact { background: var(--c-bg-muted); border: 1px solid var(--c-border-light); border-radius: var(--r-sm); padding: 10px 12px; transition: border-color var(--duration) var(--ease) }
.mp__fact:hover { border-color: var(--c-border) }
.mp__fact-content { color: var(--c-text); line-height: 1.6; margin-bottom: 6px }
.mp__fact-meta { display: flex; align-items: center; gap: 6px }
.mp__fact-conf { font-size: var(--text-xs); padding: 1px 7px; border-radius: var(--r-full); border: 1px solid transparent }
.mp__fact-conf--high { background: var(--c-success-bg, #f0fdf4); color: var(--c-success, #16a34a); border-color: #bbf7d0 }
.mp__fact-conf--med { background: var(--c-primary-bg); color: var(--c-primary); border-color: var(--c-primary-border) }
.mp__fact-conf--low { background: #fef9c3; color: #a16207; border-color: #fde047 }
.mp__fact-src { font-size: var(--text-xs); color: var(--c-text-tertiary) }

.mp__error { padding: 8px 16px; color: var(--c-danger, #ef4444); font-size: var(--text-xs); flex-shrink: 0 }
</style>
