<template>
  <div class="sl">
    <div class="sl__h">
      <h3>对话历史</h3>
      <el-button size="small" type="primary" plain @click="$emit('new-session')"><el-icon><Plus /></el-icon>新对话</el-button>
    </div>
    <div class="sl__items">
      <div v-for="s in sessions" :key="s.id" :class="['si', {'si--a': s.id === activeId}]" @click="$emit('select', s.id)">
        <div class="si__icon">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="12" height="12" rx="2.5" stroke="currentColor" stroke-width="1.2"/><path d="M5 6h6M5 8.5h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        </div>
        <div class="si__info">
          <div class="si__t">{{ s.title || '新对话' }}</div>
          <div class="si__time">{{ fmtDate(s.updated_at) }}</div>
        </div>
        <el-icon class="si__del" @click.stop="$emit('delete', s.id)"><Close /></el-icon>
      </div>
      <div v-if="!sessions.length" class="sl__empty">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none"><rect x="6" y="6" width="28" height="28" rx="6" stroke="var(--c-text-tertiary)" stroke-width="1.5" stroke-dasharray="4 3"/><path d="M15 20h10M20 15v10" stroke="var(--c-text-tertiary)" stroke-width="1.5" stroke-linecap="round"/></svg>
        <p>暂无对话记录</p>
        <span>点击「新对话」开始</span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { Plus, Close } from '@element-plus/icons-vue'
defineProps({ sessions: { type: Array, default: () => [] }, activeId: { type: String, default: '' } })
defineEmits(['select', 'new-session', 'delete'])
function fmtDate(ts) { if (!ts) return ''; try { const d = new Date(ts), n = new Date(); return d.toDateString() === n.toDateString() ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) } catch { return '' } }
</script>
<style scoped>
.sl { height: 100%; display: flex; flex-direction: column; background: var(--c-bg); border-right: 1px solid var(--c-border) }
.sl__h { display: flex; justify-content: space-between; align-items: center; padding: var(--sp-md); border-bottom: 1px solid var(--c-border) }
.sl__h h3 { margin: 0; font-size: var(--text-lg); font-weight: 600; color: var(--c-text) }
.sl__items { flex: 1; overflow-y: auto; padding: var(--sp-sm) }
.si { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--r-sm); cursor: pointer; transition: all var(--duration) var(--ease) }
.si:hover { background: var(--c-bg-muted) }
.si--a { background: var(--c-primary-bg); border: 1px solid var(--c-primary-border) }
.si__icon { flex-shrink: 0; color: var(--c-text-tertiary) }
.si--a .si__icon { color: var(--c-primary) }
.si__info { flex: 1; min-width: 0 }
.si__t { font-size: var(--text-sm); color: var(--c-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500 }
.si__time { font-size: var(--text-xs); color: var(--c-text-tertiary); margin-top: 2px }
.si__del { font-size: 12px; color: var(--c-text-tertiary); opacity: 0; transition: opacity var(--duration) var(--ease) }
.si:hover .si__del { opacity: 1 }
.si__del:hover { color: var(--c-error) }
.sl__empty { text-align: center; padding: 48px var(--sp-md); color: var(--c-text-tertiary); font-size: var(--text-sm) }
.sl__empty p { margin: 12px 0 4px; font-weight: 500; color: var(--c-text-secondary) }
.sl__empty span { font-size: var(--text-xs) }
</style>
