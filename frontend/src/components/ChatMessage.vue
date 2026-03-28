<template>
  <div :class="['cm', `cm--${msg.role}`]">
    <div class="cm__av">
      <svg v-if="msg.role==='user'" width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.5"/><path d="M3 17c0-3.5 3-5 7-5s7 1.5 7 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      <svg v-else width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="14" height="14" rx="3" stroke="currentColor" stroke-width="1.5"/><circle cx="7.5" cy="9" r="1" fill="currentColor"/><circle cx="12.5" cy="9" r="1" fill="currentColor"/><path d="M7 13c1 1.5 5 1.5 6 0" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
    </div>
    <div class="cm__body">
      <ThinkingBlock v-if="msg.metadata?.thinking?.length" :steps="msg.metadata.thinking" :initial-collapsed="true" />
      <SkillFactoryProgress v-if="msg.metadata?.design_steps?.length" :design-steps="msg.metadata.design_steps" />
      <div class="cm__c" v-html="rendered"></div>
      <!-- 大纲折叠 -->
      <div v-if="msg.metadata?.outline_md" class="attach">
        <div class="attach__h" @click="outExp=!outExp">
          <span class="attach__icon">📋</span><span class="attach__label">大纲内容</span>
          <span :class="['attach__chev', { 'attach__chev--open': outExp }]">‹</span>
        </div>
        <transition name="fold">
          <div v-if="outExp" class="attach__body" v-html="renderMd(msg.metadata.outline_md)"></div>
        </transition>
      </div>
      <!-- 报告折叠 -->
      <div v-if="msg.metadata?.report_html" class="attach">
        <div class="attach__h" @click="rptExp=!rptExp">
          <span class="attach__icon">📊</span><span class="attach__label">报告内容</span>
          <span :class="['attach__chev', { 'attach__chev--open': rptExp }]">‹</span>
        </div>
        <transition name="fold">
          <div v-if="rptExp" class="attach__rpt"><iframe class="rpt-iframe" :srcdoc="msg.metadata.report_html" sandbox="allow-same-origin allow-scripts"></iframe></div>
        </transition>
      </div>
      <!-- L5 确认 -->
      <div v-if="msg.msg_type==='confirm' && msg.metadata?.ancestors" class="ccs">
        <div v-for="a in msg.metadata.ancestors" :key="a.id" class="cc" @click="$emit('confirm',a)">
          <span class="cc__l">{{ a.label }}</span><span class="cc__n">{{ a.name }}</span>
          <span class="cc__d">{{ {2:'生成该子场景所有内容',3:'生成该维度所有评估项',4:'生成该评估项所有指标'}[a.level]||'' }}</span>
        </div>
      </div>
      <!-- 沉淀确认 -->
      <div v-if="msg.msg_type==='persist_prompt'" class="persist-bar">
        <el-button type="primary" size="small" @click="$emit('confirm',{action:'persist'})">保存为看网能力</el-button>
        <el-button size="small" @click="$emit('confirm',{action:'skip'})">暂不保存</el-button>
      </div>
      <div class="cm__time">{{ fmtTime(msg.created_at) }}</div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed } from 'vue'
import ThinkingBlock from './ThinkingBlock.vue'
import SkillFactoryProgress from './SkillFactoryProgress.vue'
const props = defineProps({ msg:{type:Object,required:true} })
defineEmits(['confirm'])
const outExp = ref(false), rptExp = ref(false)
const rendered = computed(() => (props.msg.content||'').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>').replace(/「(.*?)」/g,'<em class="hl">$1</em>').replace(/\n/g,'<br>'))
function fmtTime(ts) { if(!ts) return ''; try{return new Date(ts).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}catch{return ''} }
function renderMd(md) { return (md||'').split('\n').map(l=>{const m=l.match(/^(#{1,6})\s+(.*)/);if(m) return `<h${m[1].length} style="margin:4px 0;font-size:${18-m[1].length}px">${m[2]}</h${m[1].length}>`;if(l.trim()) return `<p style="margin:2px 0;font-size:13px;color:var(--c-text-secondary)">${l}</p>`;return ''}).join('') }
</script>
<style scoped>
.cm { display: flex; gap: 12px; padding: 14px 0; animation: msgIn .35s var(--ease) }
@keyframes msgIn { from { opacity: 0; transform: translateY(12px) } to { opacity: 1; transform: translateY(0) } }
.cm--user { flex-direction: row-reverse }

/* 头像 */
.cm__av { flex-shrink: 0; width: 36px; height: 36px; border-radius: var(--r-md); display: flex; align-items: center; justify-content: center; font-size: 18px; border: 1.5px solid var(--c-border); color: var(--c-text-secondary); background: var(--c-bg-elevated); box-shadow: var(--shadow-sm) }
.cm--user .cm__av { background: var(--c-primary-bg); border-color: var(--c-primary-border); color: var(--c-primary) }
.cm--assistant .cm__av { background: var(--c-bg-muted) }

.cm__body { max-width: 80%; min-width: 60px }

/* 气泡 */
.cm__c { padding: 12px 16px; border-radius: var(--r-lg); font-size: var(--text-base); line-height: 1.7; word-break: break-word }
.cm--assistant .cm__c { background: var(--c-bg-muted); color: var(--c-text); border-top-left-radius: var(--sp-xs); border: 1px solid var(--c-border-light) }
.cm--user .cm__c { background: linear-gradient(135deg, var(--c-primary) 0%, var(--c-primary-dark) 100%); color: var(--c-text-inverse); border-top-right-radius: var(--sp-xs); box-shadow: 0 2px 8px rgba(37,99,235,0.25) }
.cm__c :deep(.hl) { color: var(--c-primary); font-style: normal; font-weight: 600 }
.cm--user .cm__c :deep(.hl) { color: var(--c-primary-border) }

.cm__time { font-size: var(--text-xs); color: var(--c-text-tertiary); margin-top: var(--sp-xs) }
.cm--user .cm__time { text-align: right }

/* 折叠附件 */
.attach { margin-top: var(--sp-sm); border: 1px solid var(--c-border); border-radius: var(--r-sm); overflow: hidden }
.attach__h { display: flex; align-items: center; gap: var(--sp-sm); padding: 8px 12px; background: var(--c-bg-muted); cursor: pointer; font-size: var(--text-sm); color: var(--c-text-secondary); transition: background var(--duration) var(--ease) }
.attach__h:hover { background: var(--c-bg-subtle) }
.attach__icon { font-size: 14px }
.attach__label { flex: 1; font-weight: 500 }
.attach__chev { font-size: 14px; color: var(--c-text-tertiary); transform: rotate(-90deg); transition: transform var(--duration) var(--ease) }
.attach__chev--open { transform: rotate(-270deg) }
.attach__body { padding: 10px 14px; max-height: 320px; overflow-y: auto; border-top: 1px solid var(--c-border) }
.attach__rpt { border-top: 1px solid var(--c-border) }
.rpt-iframe { width: 100%; height: 400px; border: none }

.fold-enter-active, .fold-leave-active { transition: all .25s var(--ease); overflow: hidden }
.fold-enter-from, .fold-leave-to { max-height: 0; opacity: 0 }

/* 确认按钮 */
.ccs { display: flex; flex-direction: column; gap: var(--sp-sm); margin-top: 10px }
.cc { display: flex; align-items: center; gap: var(--sp-sm); padding: 10px 14px; background: var(--c-bg-elevated); border: 1px solid var(--c-border); border-radius: var(--r-sm); cursor: pointer; transition: all var(--duration) var(--ease) }
.cc:hover { border-color: var(--c-primary); box-shadow: 0 2px 8px rgba(37,99,235,0.1) }
.cc__l { font-size: var(--text-xs); font-weight: 600; color: var(--c-primary); background: var(--c-primary-bg); padding: 2px 8px; border-radius: var(--sp-xs); white-space: nowrap }
.cc__n { font-size: var(--text-base); color: var(--c-text); font-weight: 500 }
.cc__d { font-size: var(--text-xs); color: var(--c-text-tertiary); margin-left: auto }

.persist-bar { display: flex; gap: var(--sp-sm); margin-top: 10px; padding: 10px 14px; background: var(--c-warning-bg); border: 1px solid var(--c-warning-border, #FDE68A); border-radius: var(--r-sm) }
</style>
