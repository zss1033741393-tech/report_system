<template>
  <div :class="['cm', `cm--${msg.role}`]">
    <div class="cm__av">
      <svg v-if="msg.role === 'user'" width="20" height="20" viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.5"/>
        <path d="M3 17c0-3.5 3-5 7-5s7 1.5 7 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <svg v-else width="20" height="20" viewBox="0 0 20 20" fill="none">
        <rect x="3" y="3" width="14" height="14" rx="3" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="7.5" cy="9" r="1" fill="currentColor"/>
        <circle cx="12.5" cy="9" r="1" fill="currentColor"/>
        <path d="M7 13c1 1.5 5 1.5 6 0" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
      </svg>
    </div>

    <div class="cm__body">
      <!-- 思考步骤 -->
      <ThinkingBlock
        v-if="msg.metadata?.thinking?.length"
        :steps="msg.metadata.thinking"
        :initial-collapsed="true"
      />

      <!-- 设计态进度 -->
      <SkillFactoryProgress
        v-if="msg.metadata?.design_steps?.length"
        :design-steps="msg.metadata.design_steps"
      />

      <!-- ✨ 历史消息中的工具调用记录 -->
      <ToolCallBlock
        v-if="msg.metadata?.tool_calls?.length"
        :calls="msg.metadata.tool_calls"
      />

      <!-- 消息正文 -->
      <div class="cm__c" v-html="rendered"></div>

      <!-- 大纲折叠 -->
      <div v-if="msg.metadata?.outline_md" class="attach">
        <div class="attach__h" @click="outExp = !outExp">
          <span class="attach__icon">📋</span>
          <span class="attach__label">大纲内容</span>
          <span :class="['attach__chev', { 'attach__chev--open': outExp }]">‹</span>
        </div>
        <transition name="fold">
          <div v-if="outExp" class="attach__body" v-html="renderMd(msg.metadata.outline_md)"></div>
        </transition>
      </div>

      <!-- 报告折叠 -->
      <div v-if="msg.metadata?.report_html" class="attach">
        <div class="attach__h" @click="rptExp = !rptExp">
          <span class="attach__icon">📊</span>
          <span class="attach__label">报告内容</span>
          <span :class="['attach__chev', { 'attach__chev--open': rptExp }]">‹</span>
        </div>
        <transition name="fold">
          <div v-if="rptExp" class="attach__rpt">
            <iframe class="rpt-iframe" :srcdoc="msg.metadata.report_html" sandbox="allow-same-origin allow-scripts"></iframe>
          </div>
        </transition>
      </div>

      <!-- L5 层级确认 -->
      <div v-if="msg.msg_type === 'confirm' && msg.metadata?.ancestors" class="ccs">
        <div v-for="a in msg.metadata.ancestors" :key="a.id" class="cc" @click="$emit('confirm', a)">
          <span class="cc__l">{{ a.label }}</span>
          <span class="cc__n">{{ a.name }}</span>
          <span class="cc__d">{{ { 2: '生成该子场景所有内容', 3: '生成该维度所有评估项', 4: '生成该评估项所有指标' }[a.level] || '' }}</span>
        </div>
      </div>

      <!-- 沉淀确认 -->
      <div v-if="msg.msg_type === 'persist_prompt'" class="persist-bar">
        <el-button type="primary" size="small" @click="$emit('confirm', { action: 'persist' })">保存为看网能力</el-button>
        <el-button size="small" @click="$emit('confirm', { action: 'skip' })">暂不保存</el-button>
      </div>

      <div class="cm__time">{{ fmtTime(msg.created_at) }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import ThinkingBlock from './ThinkingBlock.vue'
import SkillFactoryProgress from './SkillFactoryProgress.vue'
import ToolCallBlock from './ToolCallBlock.vue'

const props = defineProps({ msg: { type: Object, required: true } })
defineEmits(['confirm'])

const outExp = ref(false), rptExp = ref(false)

const rendered = computed(() =>
  (props.msg.content || '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/「(.*?)」/g, '<em class="hl">$1</em>')
    .replace(/\n/g, '<br>')
)

function fmtTime(ts) {
  if (!ts) return ''
  try { return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }
  catch { return '' }
}

function renderMd(md) {
  return (md || '').split('\n').map(l => {
    const m = l.match(/^(#{1,6})\s+(.*)/)
    if (m) return `<h${m[1].length} style="margin:4px 0;font-size:${18 - m[1].length}px">${m[2]}</h${m[1].length}>`
    if (l.trim()) return `<p style="margin:2px 0;font-size:13px;color:var(--c-text-secondary)">${l}</p>`
    return ''
  }).join('')
}
</script>

<style scoped>
.cm { display: flex; gap: 12px; padding: 14px 0; animation: msgIn .35s var(--ease) }
@keyframes msgIn { from { opacity: 0; transform: translateY(12px) } to { opacity: 1; transform: translateY(0) } }
.cm--user { flex-direction: row-reverse }

.cm__av { flex-shrink: 0; width: 36px; height: 36px; border-radius: var(--r-md); display: flex; align-items: center; justify-content: center; font-size: 18px; border: 1.5px solid var(--c-border); color: var(--c-text-secondary); background: var(--c-bg-elevated); box-shadow: var(--shadow-sm) }
.cm--user .cm__av { background: var(--c-primary-bg); border-color: var(--c-primary-border); color: var(--c-primary) }
.cm--assistant .cm__av { background: var(--c-bg-muted) }

.cm__body { max-width: 80%; min-width: 60px }

.cm__c { padding: 12px 16px; border-radius: var(--r-lg); font-size: var(--text-base); line-height: 1.7; word-break: break-word }
.cm--assistant .cm__c { background: var(--c-bg-muted); color: var(--c-text); border-top-left-radius: var(--sp-xs); border: 1px solid var(--c-border) }
.cm--user .cm__c { background: var(--c-primary); color: #fff; border-top-right-radius: var(--sp-xs) }
.cm__c :deep(.hl) { color: var(--c-primary); font-style: normal; font-weight: 500 }

.cm__time { font-size: 11px; color: var(--c-text-tertiary); margin-top: 4px; padding: 0 4px }
.cm--user .cm__time { text-align: right }

/* 大纲/报告折叠 */
.attach { margin-top: 8px; border: 1px solid var(--c-border); border-radius: var(--r-md); overflow: hidden }
.attach__h { display: flex; align-items: center; gap: 6px; padding: 8px 12px; cursor: pointer; background: var(--c-bg-muted); font-size: 13px; color: var(--c-text-secondary); user-select: none }
.attach__h:hover { background: var(--c-bg); }
.attach__icon { font-size: 14px }
.attach__label { flex: 1; font-weight: 500 }
.attach__chev { font-size: 14px; transform: rotate(-90deg); transition: transform .2s }
.attach__chev--open { transform: rotate(90deg) }
.attach__body { padding: 12px; font-size: 13px; border-top: 1px solid var(--c-border) }
.attach__rpt { height: 400px; border-top: 1px solid var(--c-border) }
.rpt-iframe { width: 100%; height: 100%; border: none }

/* L5 确认卡片 */
.ccs { display: flex; flex-direction: column; gap: 6px; margin-top: 8px }
.cc { display: grid; grid-template-columns: 24px 1fr; grid-template-rows: auto auto; gap: 2px 8px; padding: 10px 12px; border: 1px solid var(--c-border); border-radius: var(--r-md); cursor: pointer; transition: all .15s; background: var(--c-bg-elevated) }
.cc:hover { border-color: var(--c-primary-border); background: var(--c-primary-bg) }
.cc__l { grid-row: 1 / 3; align-self: center; font-size: 16px; font-weight: 700; color: var(--c-primary) }
.cc__n { font-size: 13px; font-weight: 600; color: var(--c-text) }
.cc__d { font-size: 12px; color: var(--c-text-secondary) }

/* 沉淀确认 */
.persist-bar { display: flex; gap: 8px; margin-top: 8px; padding: 10px 12px; background: var(--c-primary-bg); border-radius: var(--r-md); border: 1px solid var(--c-primary-border) }

/* 折叠动画 */
.fold-enter-active, .fold-leave-active { transition: all .2s; overflow: hidden }
.fold-enter-from, .fold-leave-to { max-height: 0; opacity: 0 }
.fold-enter-to, .fold-leave-from { max-height: 600px }
</style>
