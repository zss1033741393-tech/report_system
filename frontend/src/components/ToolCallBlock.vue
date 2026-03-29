<template>
  <div class="tcb" :class="`tcb--${statusClass}`">
    <div class="tcb__header" @click="expanded = !expanded">
      <span class="tcb__icon">🔧</span>
      <span class="tcb__name">{{ call.name }}</span>
      <span class="tcb__status">
        <span v-if="call.status === 'running'" class="tcb__dot tcb__dot--running"></span>
        <span v-else-if="call.status === 'done'" class="tcb__badge tcb__badge--done">✓ 完成</span>
        <span v-else-if="call.status === 'error'" class="tcb__badge tcb__badge--error">✗ 失败</span>
      </span>
      <span class="tcb__expand">{{ expanded ? '▲' : '▼' }}</span>
    </div>
    <transition name="tcb-fold">
      <div v-if="expanded" class="tcb__body">
        <div v-if="hasArgs" class="tcb__section">
          <div class="tcb__label">参数</div>
          <div class="tcb__code">{{ argsText }}</div>
        </div>
        <div v-if="call.summary" class="tcb__section">
          <div class="tcb__label">结果</div>
          <div class="tcb__result" :class="{'tcb__result--error': !call.success}">{{ call.summary }}</div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  call: { type: Object, required: true }
  // call: { name, args, status ('running'|'done'|'error'), summary, success }
})

const expanded = ref(false)

const statusClass = computed(() => props.call.status || 'running')

const hasArgs = computed(() => {
  const args = props.call.args
  return args && typeof args === 'object' && Object.keys(args).length > 0
})

const argsText = computed(() => {
  try {
    return JSON.stringify(props.call.args, null, 2)
  } catch {
    return String(props.call.args)
  }
})
</script>

<style scoped>
.tcb {
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  overflow: hidden;
  margin: 4px 0;
  font-size: var(--text-sm);
  background: var(--c-bg-elevated);
}
.tcb--running { border-color: var(--c-primary-border); }
.tcb--done { border-color: var(--c-border); }
.tcb--error { border-color: #FCA5A5; }

.tcb__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  background: var(--c-bg-muted);
  transition: background var(--duration) var(--ease);
  user-select: none;
}
.tcb__header:hover { background: var(--c-bg-subtle); }
.tcb--running .tcb__header { background: var(--c-primary-bg); }

.tcb__icon { font-size: 12px; }
.tcb__name { flex: 1; font-weight: 600; color: var(--c-text); font-family: var(--font-mono, monospace); }

.tcb__status { display: flex; align-items: center; }
.tcb__dot--running {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--c-primary);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

.tcb__badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 600;
}
.tcb__badge--done { background: #D1FAE5; color: #065F46; }
.tcb__badge--error { background: #FEE2E2; color: #991B1B; }

.tcb__expand { font-size: 10px; color: var(--c-text-tertiary); margin-left: 4px; }

.tcb__body { padding: 10px 12px; border-top: 1px solid var(--c-border-light); }
.tcb__section + .tcb__section { margin-top: 8px; }
.tcb__label { font-size: 11px; font-weight: 600; color: var(--c-text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.tcb__code {
  background: var(--c-bg);
  border: 1px solid var(--c-border-light);
  border-radius: var(--r-xs);
  padding: 6px 8px;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  color: var(--c-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
}
.tcb__result { font-size: var(--text-sm); color: var(--c-text-secondary); line-height: 1.5; }
.tcb__result--error { color: #DC2626; }

.tcb-fold-enter-active, .tcb-fold-leave-active { transition: all .2s var(--ease); overflow: hidden; }
.tcb-fold-enter-from, .tcb-fold-leave-to { max-height: 0; opacity: 0; }
</style>
