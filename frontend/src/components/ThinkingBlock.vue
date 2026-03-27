<template>
  <div :class="['tb', { 'tb--done': allDone }]">
    <div class="tb__h" @click="collapsed=!collapsed">
      <div class="tb__status">
        <span v-if="!allDone" class="tb__pulse"></span>
        <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="var(--c-success)" stroke-width="1.5"/><path d="M5 8l2 2 4-4" stroke="var(--c-success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <span class="tb__title">{{ allDone ? `思考完成 · ${steps.length} 步` : '正在思考...' }}</span>
      <span :class="['tb__chev', { 'tb__chev--open': !collapsed }]">‹</span>
    </div>
    <transition name="expand">
      <div v-show="!collapsed" class="tb__body">
        <div v-for="(s, i) in steps" :key="i" class="ts">
          <div class="ts__dot">
            <span v-if="s.status==='running'" class="ts__spin"></span>
            <svg v-else width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" fill="var(--c-success-bg)"/><path d="M4 7l2 2 4-4" stroke="var(--c-success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>
          <div class="ts__content">
            <span class="ts__text">{{ s.detail }}</span>
            <div v-if="s.data?.top_matches" class="ts__tags">
              <span v-for="(m, mi) in s.data.top_matches" :key="mi" class="ts__tag">{{ m.name }} <span class="ts__score">({{ m.score }})</span></span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>
<script setup>
import { ref, computed } from 'vue'
const props = defineProps({ steps: { type: Array, default: () => [] }, initialCollapsed: { type: Boolean, default: false } })
const collapsed = ref(props.initialCollapsed)
const allDone = computed(() => props.steps.length > 0 && props.steps.every(s => s.status === 'done'))
</script>
<style scoped>
.tb { margin: var(--sp-sm) 0; border-radius: var(--r-sm); background: var(--c-bg-elevated); border: 1px solid var(--c-border); font-size: var(--text-sm); overflow: hidden }
.tb--done { border-color: var(--c-border-light) }

.tb__h { display: flex; align-items: center; gap: var(--sp-sm); padding: 10px 14px; cursor: pointer; transition: background var(--duration) var(--ease) }
.tb__h:hover { background: var(--c-bg-muted) }
.tb__status { flex-shrink: 0; width: 16px; height: 16px; display: flex; align-items: center; justify-content: center }
.tb__title { flex: 1; font-weight: 500; color: var(--c-text) }
.tb--done .tb__title { color: var(--c-text-secondary) }
.tb__chev { font-size: 14px; color: var(--c-text-tertiary); transform: rotate(-90deg); transition: transform var(--duration) var(--ease) }
.tb__chev--open { transform: rotate(-270deg) }

/* 脉冲动画 */
.tb__pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--c-primary); animation: pulse 1.5s ease-in-out infinite }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1) } 50% { opacity: 0.5; transform: scale(0.8) } }

.tb__body { padding: 0 14px 12px; border-top: 1px solid var(--c-border-light) }

/* 步骤条 */
.ts { display: flex; gap: 10px; padding: 6px 0; position: relative }
.ts + .ts { border-top: none }
.ts__dot { flex-shrink: 0; width: 20px; display: flex; align-items: center; justify-content: center; padding-top: 2px }
.ts__content { flex: 1; min-width: 0 }
.ts__text { color: var(--c-text-secondary); line-height: 1.5 }
.ts__tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px }
.ts__tag { font-size: var(--text-xs); padding: 1px 8px; background: var(--c-primary-bg); color: var(--c-primary); border-radius: var(--r-full); border: 1px solid var(--c-primary-border) }
.ts__score { opacity: 0.6 }

.ts__spin { width: 12px; height: 12px; border: 2px solid var(--c-border); border-top-color: var(--c-primary); border-radius: 50%; animation: spin .7s linear infinite }
@keyframes spin { to { transform: rotate(360deg) } }

.expand-enter-active, .expand-leave-active { transition: all .25s var(--ease); overflow: hidden }
.expand-enter-from, .expand-leave-to { max-height: 0; opacity: 0; padding-top: 0; padding-bottom: 0 }
</style>
