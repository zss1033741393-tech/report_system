<template>
  <div class="tool-calls">
    <div
      v-for="(tc, idx) in toolCalls"
      :key="idx"
      :class="['tc-item', `tc-item--${tc.status}`]"
    >
      <!-- 工具名 + 状态 -->
      <div class="tc-header">
        <span class="tc-icon">🔧</span>
        <span class="tc-name">{{ tc.name }}</span>
        <span class="tc-status-badge">
          <span v-if="tc.status === 'running'" class="tc-spinner"></span>
          <span v-else-if="tc.status === 'done' && tc.success !== false">✓</span>
          <span v-else-if="tc.status === 'done' && tc.success === false">✗</span>
        </span>
        <span class="tc-status-text">{{ statusText(tc) }}</span>
        <!-- 折叠按钮（有结果时才显示） -->
        <button
          v-if="tc.result !== undefined"
          class="tc-toggle"
          @click="tc._expanded = !tc._expanded"
        >{{ tc._expanded ? '收起' : '详情' }}</button>
      </div>

      <!-- 参数（始终显示简短摘要） -->
      <div v-if="tc.args && hasVisibleArgs(tc.args)" class="tc-args">
        <span class="tc-label">参数：</span>
        <span class="tc-args-text">{{ formatArgs(tc.args) }}</span>
      </div>

      <!-- 结果（折叠展示） -->
      <div v-if="tc._expanded && tc.result !== undefined" class="tc-result">
        <span class="tc-label">结果：</span>
        <span class="tc-result-text">{{ tc.result }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const props = defineProps({
  // toolCalls: [{name, args, status: 'running'|'done', result, success, _expanded}]
  toolCalls: { type: Array, default: () => [] }
})

function statusText(tc) {
  if (tc.status === 'running') return '执行中'
  if (tc.status === 'done' && tc.success === false) return '失败'
  if (tc.status === 'done') return '完成'
  return ''
}

function hasVisibleArgs(args) {
  if (!args || typeof args !== 'object') return false
  const keys = Object.keys(args).filter(k => k !== 'session_id')
  return keys.length > 0
}

function formatArgs(args) {
  if (!args) return ''
  const filtered = Object.entries(args)
    .filter(([k]) => k !== 'session_id')
    .map(([k, v]) => {
      const val = typeof v === 'object' ? JSON.stringify(v) : String(v)
      const truncated = val.length > 60 ? val.slice(0, 60) + '…' : val
      return `${k}: ${truncated}`
    })
  return filtered.join('  |  ')
}
</script>

<style scoped>
.tool-calls {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0;
}

.tc-item {
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  padding: 8px 12px;
  font-size: var(--text-xs);
  background: var(--c-bg-muted);
  transition: border-color var(--duration) var(--ease);
}

.tc-item--running {
  border-color: var(--c-primary-border);
  background: var(--c-primary-bg);
}

.tc-item--done {
  border-color: var(--c-border);
}

.tc-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tc-icon { font-size: 13px; }

.tc-name {
  font-weight: 600;
  color: var(--c-text);
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.tc-status-badge {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: var(--c-primary);
  min-width: 14px;
}

.tc-item--done .tc-status-badge { color: var(--c-success, #22c55e); }
.tc-item--done:has(.tc-status-text:empty) .tc-status-badge { color: var(--c-error, #ef4444); }

.tc-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid var(--c-primary-border);
  border-top-color: var(--c-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.tc-status-text {
  color: var(--c-text-tertiary);
  font-size: 11px;
}

.tc-toggle {
  margin-left: auto;
  background: none;
  border: 1px solid var(--c-border);
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  color: var(--c-text-secondary);
  cursor: pointer;
  transition: border-color var(--duration) var(--ease);
}
.tc-toggle:hover { border-color: var(--c-primary-border); color: var(--c-primary); }

.tc-args, .tc-result {
  margin-top: 4px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.tc-label {
  color: var(--c-text-tertiary);
  flex-shrink: 0;
}

.tc-args-text {
  color: var(--c-text-secondary);
  word-break: break-all;
}

.tc-result-text {
  color: var(--c-text-secondary);
  word-break: break-all;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
</style>
