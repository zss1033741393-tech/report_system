<template>
  <div class="tcb">
    <div
      v-for="(call, idx) in calls"
      :key="call.id || idx"
      :class="['tcb__item', `tcb__item--${call.status}`]"
    >
      <!-- 头部：工具名 + 状态徽标 -->
      <div class="tcb__head" @click="toggleExpand(idx)">
        <span class="tcb__dot" :class="`tcb__dot--${call.status}`"></span>
        <span class="tcb__icon">{{ toolIcon(call.name) }}</span>
        <span class="tcb__name">{{ toolLabel(call.name) }}</span>
        <span class="tcb__badge" :class="`tcb__badge--${call.status}`">
          {{ statusText(call.status) }}
        </span>
        <span class="tcb__chev" :class="{ 'tcb__chev--open': expanded[idx] }">‹</span>
      </div>

      <!-- 展开区：参数 + 结果 -->
      <transition name="fold">
        <div v-if="expanded[idx]" class="tcb__detail">
          <!-- 参数 -->
          <div v-if="hasArgs(call.args)" class="tcb__section">
            <div class="tcb__label">参数</div>
            <div class="tcb__code">
              <span
                v-for="(val, key) in filteredArgs(call.args)"
                :key="key"
                class="tcb__kv"
              >
                <span class="tcb__k">{{ key }}</span>
                <span class="tcb__v">{{ truncate(val) }}</span>
              </span>
            </div>
          </div>

          <!-- 结果 -->
          <div v-if="call.result" class="tcb__section">
            <div class="tcb__label">{{ call.error ? '错误' : '结果' }}</div>
            <div :class="['tcb__result', { 'tcb__result--err': call.error }]">
              {{ truncate(call.result, 200) }}
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({
  calls: { type: Array, default: () => [] }
})

// 每个 call 是否展开（默认展开进行中和出错的，折叠已完成的）
const expanded = reactive({})

function toggleExpand(idx) {
  expanded[idx] = !expanded[idx]
}

// 自动展开进行中 / 出错的条目
function shouldExpand(call) {
  return call.status === 'running' || call.status === 'error'
}

// 工具名 → 显示图标
function toolIcon(name) {
  const icons = {
    read_skill_file: '📖',
    get_session_status: '📊',
    search_skill: '🔍',
    get_current_outline: '📋',
    clip_outline: '✂️',
    inject_params: '🔧',
    execute_data: '⚡',
    render_report: '📄',
    understand_intent: '🧠',
    extract_structure: '🗂️',
    design_outline: '✏️',
    bind_data: '🔗',
    preview_report: '👁️',
    persist_skill: '💾',
  }
  return icons[name] || '🔨'
}

// 工具名 → 中文标签
function toolLabel(name) {
  const labels = {
    read_skill_file: '读取技能文档',
    get_session_status: '获取会话状态',
    search_skill: '检索已有能力',
    get_current_outline: '获取当前大纲',
    clip_outline: '裁剪大纲节点',
    inject_params: '注入参数条件',
    execute_data: '执行数据查询',
    render_report: '生成报告',
    understand_intent: '理解看网意图',
    extract_structure: '提取结构化信息',
    design_outline: '设计大纲结构',
    bind_data: '绑定数据源',
    preview_report: '预览报告',
    persist_skill: '沉淀看网能力',
  }
  return labels[name] || name
}

// 状态 → 文案
function statusText(status) {
  return { running: '执行中', done: '完成', error: '失败' }[status] || status
}

// 过滤掉 session_id 等内部参数
function filteredArgs(args) {
  if (!args || typeof args !== 'object') return {}
  const hidden = ['session_id']
  return Object.fromEntries(
    Object.entries(args).filter(([k]) => !hidden.includes(k))
  )
}

function hasArgs(args) {
  return Object.keys(filteredArgs(args)).length > 0
}

function truncate(val, maxLen = 120) {
  const s = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '')
  return s.length > maxLen ? s.slice(0, maxLen) + '…' : s
}
</script>

<style scoped>
.tcb {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 4px 0 8px;
}

/* 单个工具调用条目 */
.tcb__item {
  border-radius: 8px;
  border: 1px solid var(--c-border);
  background: var(--c-bg-elevated);
  overflow: hidden;
  transition: border-color 0.2s;
}
.tcb__item--running { border-color: var(--c-primary-border); }
.tcb__item--error   { border-color: #fca5a5; }

/* 头部 */
.tcb__head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.tcb__head:hover { background: var(--c-bg-muted); }

/* 状态点 */
.tcb__dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tcb__dot--running {
  background: var(--c-primary);
  animation: pulse 1.2s ease-in-out infinite;
}
.tcb__dot--done  { background: #22c55e; }
.tcb__dot--error { background: #ef4444; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

.tcb__icon { font-size: 13px; flex-shrink: 0; }
.tcb__name { font-size: 13px; font-weight: 500; color: var(--c-text); flex: 1; }

/* 徽标 */
.tcb__badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  font-weight: 500;
  flex-shrink: 0;
}
.tcb__badge--running { background: var(--c-primary-bg); color: var(--c-primary); }
.tcb__badge--done    { background: #dcfce7; color: #16a34a; }
.tcb__badge--error   { background: #fee2e2; color: #dc2626; }

/* 展开箭头 */
.tcb__chev {
  font-size: 14px;
  color: var(--c-text-tertiary);
  transform: rotate(-90deg);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.tcb__chev--open { transform: rotate(90deg); }

/* 展开区 */
.tcb__detail {
  padding: 0 10px 10px;
  border-top: 1px solid var(--c-border);
}
.tcb__section { margin-top: 8px; }
.tcb__label {
  font-size: 11px;
  color: var(--c-text-tertiary);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* 参数代码块 */
.tcb__code {
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: var(--c-bg-muted);
  border-radius: 6px;
  padding: 6px 8px;
}
.tcb__kv {
  display: flex;
  gap: 6px;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  align-items: flex-start;
}
.tcb__k {
  color: var(--c-text-secondary);
  min-width: 80px;
  flex-shrink: 0;
}
.tcb__v {
  color: var(--c-text);
  word-break: break-all;
}

/* 结果文本 */
.tcb__result {
  font-size: 12px;
  color: var(--c-text-secondary);
  line-height: 1.6;
  background: var(--c-bg-muted);
  border-radius: 6px;
  padding: 6px 8px;
  word-break: break-all;
}
.tcb__result--err { color: #dc2626; background: #fff5f5; }

/* 折叠动画 */
.fold-enter-active,
.fold-leave-active { transition: all 0.2s ease; max-height: 300px; overflow: hidden; }
.fold-enter-from,
.fold-leave-to { max-height: 0; opacity: 0; }
</style>
