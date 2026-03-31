<template>
  <div class="app">
    <aside class="sidebar">
      <div class="sidebar__tabs">
        <button :class="['stab', {active: sideTab==='sessions'}]" @click="sideTab='sessions'" title="会话">💬</button>
        <button :class="['stab', {active: sideTab==='memory'}]" @click="sideTab='memory'" title="记忆">🧠</button>
        <button :class="['stab', {active: sideTab==='skills'}]" @click="sideTab='skills'" title="技能">⚙️</button>
      </div>
      <div class="sidebar__body">
        <SessionList v-if="sideTab==='sessions'" :sessions="sessions" :active-id="sid" @select="switchSession" @new-session="newSession" @delete="delSession" />
        <MemoryPanel v-else-if="sideTab==='memory'" />
        <SkillsManager v-else-if="sideTab==='skills'" />
      </div>
    </aside>
    <section :class="['chat', {'chat--full': !showRight}]">
      <div class="chat__msgs" ref="msgsCtn">
        <!-- 欢迎页 -->
        <div v-if="!conv.messages.value.length && !thinkSteps.length" class="welcome">
          <div class="welcome__hero">
            <div class="welcome__icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none"><rect width="48" height="48" rx="12" fill="var(--c-primary-bg)"/><path d="M14 20h20M14 28h12M24 14l8 6-8 6" stroke="var(--c-primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <h1 class="welcome__title">智能看网报告系统</h1>
            <p class="welcome__desc">将业务专家的网络评估经验，转化为可复用、可执行的看网报告</p>
          </div>
          <div class="welcome__cards">
            <div class="wcard" v-for="(g, gi) in exampleGroups" :key="gi">
              <div class="wcard__header">
                <span class="wcard__icon">{{ g.icon }}</span>
                <span class="wcard__label">{{ g.label }}</span>
              </div>
              <div class="wcard__item" v-for="e in g.items" :key="e" @click="send(e)">
                <span class="wcard__text">{{ e }}</span>
                <span class="wcard__arrow">→</span>
              </div>
            </div>
          </div>
          <p class="welcome__hint">输入分析需求开始对话，或点击上方示例快速体验</p>
        </div>
        <!-- 消息列表 -->
        <ChatMessage v-for="m in conv.messages.value" :key="m.id||m._tid" :msg="m" @confirm="onConfirm" />
        <div v-if="thinkSteps.length || streamReply || designSteps.length || conv.toolCalls.value.length" class="cur">
          <SkillFactoryProgress v-if="designSteps.length" :design-steps="designSteps" />
          <ThinkingBlock v-if="thinkSteps.length" :steps="thinkSteps" />
          <div v-if="conv.toolCalls.value.length" class="cur-toolcalls">
            <ToolCallBlock v-for="(tc, i) in conv.toolCalls.value" :key="i" :call="tc" />
          </div>
          <ChatMessage v-if="streamReply" :msg="{role:'assistant',content:streamReply,msg_type:'text',created_at:new Date().toISOString()}" />
        </div>
      </div>
      <QueryInput :loading="loading" @send="send" />
    </section>
    <div v-if="!showRight && (hasOutline || hasReport)" class="edge-tab" @click="showRight=true">
      <span class="edge-tab__icon">{{ hasReport ? '📊' : '📋' }}</span>
      <span class="edge-tab__text">{{ hasReport ? '报告' : '大纲' }}</span>
    </div>
    <transition name="sp">
      <section v-if="showRight" class="right-side">
        <RightPanel
          :outline-content="outContent" :outline-loading="outLoading" :anchor="conv.anchorInfo.value"
          :report-html="reportHtml" :report-title="reportTitle" :report-loading="reportLoading"
          :has-report="hasReport" :has-outline="hasOutline"
          @close="showRight=false" />

      </section>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import SessionList from '../components/SessionList.vue'
import ChatMessage from '../components/ChatMessage.vue'
import QueryInput from '../components/QueryInput.vue'
import RightPanel from '../components/RightPanel.vue'
import ThinkingBlock from '../components/ThinkingBlock.vue'
import SkillFactoryProgress from '../components/SkillFactoryProgress.vue'
import ToolCallBlock from '../components/ToolCallBlock.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import SkillsManager from '../components/SkillsManager.vue'
import { sendMessage, fetchSessions, deleteSession, fetchArtifacts } from '../utils/sse.js'
import { useConversation } from '../composables/useConversation.js'

const conv = useConversation()

const sessions = ref([]), sid = ref(''), loading = ref(false)
const outLoading = ref(false), streamReply = ref('')
const reportLoading = ref(false)
const msgsCtn = ref(null), showRight = ref(false)
const thinkSteps = ref([]), designSteps = ref([])
const sideTab = ref('sessions')
let ctrl = null

const hasOutline = computed(() => !!conv.outline.value)
const hasReport = computed(() => !!conv.report.value)
const outContent = computed(() => conv.outline.value ? rJson(conv.outline.value) : '')
const reportHtml = computed(() => conv.report.value?.html || '')
const reportTitle = computed(() => conv.report.value?.title || '')

const exampleGroups = [
  { icon: '🔍', label: '快速分析', items: ['帮我分析政企OTN升级的机会点', 'fgOTN部署，从时延方面分析'] },
  { icon: '🎯', label: '精准筛选', items: ['从传送网络容量角度分析fgOTN，不看低阶交叉，只看金融行业'] },
  { icon: '📝', label: '能力沉淀', items: ['输入看网逻辑文本，系统自动解析并生成可复用的分析能力'] },
]

onMounted(async () => { await loadSessions() })
async function loadSessions() { try { sessions.value = await fetchSessions() } catch { sessions.value = [] } }

async function switchSession(id) {
  if (ctrl) { ctrl.abort(); ctrl = null }
  loading.value = false; outLoading.value = false; reportLoading.value = false
  streamReply.value = ''; thinkSteps.value = []; designSteps.value = []
  sid.value = id
  await conv.loadSession(id)
  showRight.value = hasOutline.value || hasReport.value
  await scroll()
}

async function newSession() {
  sid.value = uuidv4()
  conv.reset()
  streamReply.value = ''; thinkSteps.value = []; designSteps.value = []
  showRight.value = false
  await loadSessions()
}
async function delSession(id) {
  try {
    await deleteSession(id); await loadSessions()
    if (id === sid.value) { sessions.value.length ? await switchSession(sessions.value[0].id) : await newSession() }
  } catch {}
}

function send(text) {
  if (!text.trim() || loading.value) return
  if (!sid.value) sid.value = uuidv4()
  conv.addMessage({ _tid: Date.now(), role: 'user', content: text, msg_type: 'text', created_at: new Date().toISOString() })
  scroll(); loading.value = true; streamReply.value = ''; outLoading.value = false; reportLoading.value = false
  thinkSteps.value = []; designSteps.value = []; conv.clearToolCalls()
  let outStarted = false, reportStarted = false, compThinking = null, outMdSnap = ''
  ctrl = sendMessage(sid.value, text, {
    onThinkingStep(d) {
      if (d.status === 'done') { for (let i = thinkSteps.value.length - 1; i >= 0; i--) { if (thinkSteps.value[i].step === d.step && thinkSteps.value[i].status === 'running') { thinkSteps.value[i] = d; scroll(); return } } }
      thinkSteps.value.push(d); scroll()
    },
    onThinkingComplete(t) { compThinking = t },
    onToolCall(d) { conv.onToolCall(d); scroll() },
    onToolResult(d) { conv.onToolResult(d); scroll() },
    onChatReply(c) { streamReply.value = c; scroll() },
    onOutlineChunk(c) {
      if (!outStarted) { conv.updateOutline(null, null); outLoading.value = true; outStarted = true; showRight.value = true; outMdSnap = '' }
      outMdSnap += c
    },
    onOutlineDone(a) {
      outLoading.value = false
      if (a) conv.anchorInfo.value = a
      // 大纲流结束后从 API 拉取 outline JSON，实时更新侧边栏（无需切换会话）
      fetchArtifacts(sid.value).then(artifacts => {
        if (artifacts.outline_json) {
          conv.updateOutline(artifacts.outline_json, artifacts.anchor_info || null)
          showRight.value = true
        }
      }).catch(() => {})
    },
    onOutlineUpdated(j) {
      if (j) { conv.updateOutline(j, conv.anchorInfo.value); showRight.value = true }
    },
    onOutlineClipped() {
      // clip 完成后也重新拉取最新 outline
      fetchArtifacts(sid.value).then(artifacts => {
        if (artifacts.outline_json) conv.updateOutline(artifacts.outline_json, artifacts.anchor_info || null)
      }).catch(() => {})
    },
    onReportChunk(c) {
      if (!reportStarted) {
        conv.updateReport('', '')
        reportLoading.value = true; reportStarted = true; showRight.value = true
      }
      if (conv.report.value) conv.report.value.html += c
    },
    onReportDone(d) { reportLoading.value = false; if (conv.report.value) conv.report.value.title = d?.title || '报告' },
    onDesignStep(d) {
      const existing = designSteps.value.find(s => s.step === d.step)
      if (existing) { Object.assign(existing, d) } else { designSteps.value.push(d) }
      scroll()
    },
    onPersistPrompt(d) {
      conv.addMessage({ _tid: Date.now(), role: 'assistant', content: d.message, msg_type: 'persist_prompt',
        metadata: { context_key: d.context_key }, created_at: new Date().toISOString() })
      scroll()
    },
    onSkillPersisted(d) {
      conv.addMessage({ _tid: Date.now(), role: 'assistant', content: `看网能力「${d.skill_name}」已沉淀到 ${d.skill_dir}`,
        msg_type: 'text', created_at: new Date().toISOString() })
    },
    onDataExecuting() {}, onDataExecuted() {}, onConfirmRequired() {},
    onError(m) {
      streamReply.value = ''
      conv.addMessage({ _tid: Date.now(), role: 'assistant', content: m, msg_type: 'error', created_at: new Date().toISOString() })
      scroll()
    },
    onDone() {
      loading.value = false; outLoading.value = false; reportLoading.value = false
      const meta = {}
      if (compThinking?.length) meta.thinking = compThinking; else if (thinkSteps.value.length) meta.thinking = [...thinkSteps.value]
      if (outMdSnap) meta.outline_md = outMdSnap
      if (designSteps.value.length) meta.design_steps = [...designSteps.value]
      if (conv.toolCalls.value.length) meta.tool_calls = [...conv.toolCalls.value]
      if (conv.report.value?.html) { meta.report_html = conv.report.value.html; meta.report_title = conv.report.value.title }
      const content = streamReply.value || (designSteps.value.length ? '看网能力分析完成' : '处理完成')
      conv.addMessage({
        _tid: Date.now(), role: 'assistant', content, msg_type: designSteps.value.length ? 'design_result' : 'text',
        created_at: new Date().toISOString(), metadata: Object.keys(meta).length ? meta : null
      })
      streamReply.value = ''; thinkSteps.value = []; designSteps.value = []; conv.clearToolCalls(); scroll(); loadSessions()
      // 每轮对话结束后同步最新产物（修复 skill-factory 等流程大纲不自动显示的问题）
      if (sid.value) {
        fetchArtifacts(sid.value).then(artifacts => {
          if (artifacts.outline_json) conv.updateOutline(artifacts.outline_json, artifacts.anchor_info || null)
          if (artifacts.report_html && !conv.report.value?.html) {
            conv.updateReport(artifacts.report_html, artifacts.report_title || '报告')
          }
        }).catch(() => {})
      }
    }
  })
}

function onConfirm(a) {
  if (a.action === 'persist') {
    for (let i = conv.messages.value.length - 1; i >= 0; i--) {
      const m = conv.messages.value[i]
      if (m.msg_type === 'persist_prompt' && m.metadata?.context_key) { send(`保存为看网能力，context_key=${m.metadata.context_key}`); return }
    }
    send('保存为看网能力')
  } else if (a.action === 'skip') { send('暂不保存') }
  else { send(`选择${a.label}：${a.name}`) }
}
async function scroll() { await nextTick(); const e = msgsCtn.value; if (e) e.scrollTop = e.scrollHeight }
function rJson(tree, d = 0) {
  if (!tree?.name) return ''; let md = ''; const p = '#'.repeat(Math.min(d + 1, 6))
  if (d === 0) {
    md += `${p} ${tree.name}\n\n`
  } else if (tree.level === 5) {
    md += `- **${tree.name}**`
    const para = tree.paragraph
    if (para?.content) {
      const preview = para.content.replace(/\{(\w+)\}/g, '[$1]')
      md += `：${preview}`
    }
    md += '\n'
  } else {
    md += `${p} ${tree.name}\n\n`
  }
  for (const c of tree.children || []) md += rJson(c, d + 1); return md
}
</script>

<style scoped>
.app { display: flex; height: 100vh; overflow: hidden; background: var(--c-bg); font-family: var(--font-sans) }
.sidebar { width: 260px; flex-shrink: 0; display: flex; flex-direction: column }
.sidebar__tabs { display: flex; gap: 2px; padding: 6px 8px; border-bottom: 1px solid var(--c-border); background: var(--c-bg-muted) }
.stab { flex: 1; background: transparent; border: none; cursor: pointer; padding: 6px; border-radius: 4px; font-size: 16px; transition: background 0.15s }
.stab:hover { background: var(--c-border) }
.stab.active { background: var(--c-primary-bg) }
.sidebar__body { flex: 1; overflow-y: auto }
.chat { flex: 4; min-width: 320px; display: flex; flex-direction: column; border-left: 1px solid var(--c-border); border-right: 1px solid var(--c-border); background: var(--c-bg-elevated); transition: flex .3s var(--ease) }
.chat--full { flex: 10 }
.chat__msgs { flex: 1; overflow-y: auto; padding: var(--sp-md) var(--sp-lg) }

/* ─── 欢迎页 ─── */
.welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: var(--sp-xl) }
.welcome__hero { text-align: center; margin-bottom: var(--sp-xl) }
.welcome__icon { margin-bottom: var(--sp-md) }
.welcome__title { font-size: 28px; font-weight: 700; color: var(--c-text); margin: 0 0 var(--sp-sm); letter-spacing: -0.5px }
.welcome__desc { font-size: var(--text-base); color: var(--c-text-secondary); margin: 0; max-width: 400px; line-height: 1.6 }

.welcome__cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--sp-md); width: 100%; max-width: 720px }
.wcard { background: var(--c-bg-elevated); border: 1px solid var(--c-border); border-radius: var(--r-md); overflow: hidden; transition: border-color var(--duration) var(--ease), box-shadow var(--duration) var(--ease) }
.wcard:hover { border-color: var(--c-primary-border); box-shadow: var(--shadow-md) }
.wcard__header { display: flex; align-items: center; gap: var(--sp-sm); padding: 12px var(--sp-md); border-bottom: 1px solid var(--c-border-light); background: var(--c-bg-muted) }
.wcard__icon { font-size: 16px }
.wcard__label { font-size: var(--text-sm); font-weight: 600; color: var(--c-text) }
.wcard__item { display: flex; align-items: center; padding: 10px var(--sp-md); cursor: pointer; transition: background var(--duration) var(--ease) }
.wcard__item:hover { background: var(--c-primary-bg) }
.wcard__item + .wcard__item { border-top: 1px solid var(--c-border-light) }
.wcard__text { flex: 1; font-size: var(--text-sm); color: var(--c-text-secondary); line-height: 1.5 }
.wcard__arrow { color: var(--c-text-tertiary); font-size: var(--text-sm); opacity: 0; transition: opacity var(--duration) var(--ease), transform var(--duration) var(--ease) }
.wcard__item:hover .wcard__arrow { opacity: 1; transform: translateX(2px); color: var(--c-primary) }

.welcome__hint { margin-top: var(--sp-lg); font-size: var(--text-xs); color: var(--c-text-tertiary) }

/* ─── 右侧贴边标签 ─── */
.edge-tab { flex-shrink: 0; width: 32px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; background: var(--c-primary); color: var(--c-text-inverse); cursor: pointer; writing-mode: vertical-rl; padding: 12px 4px; transition: background var(--duration) var(--ease) }
.edge-tab:hover { background: var(--c-primary-light) }
.edge-tab__icon { font-size: 16px; writing-mode: horizontal-tb }
.edge-tab__text { font-size: var(--text-xs); letter-spacing: 2px; font-weight: 500 }
.right-side { flex: 6; min-width: 400px }
.sp-enter-active, .sp-leave-active { transition: all .3s var(--ease) }
.sp-enter-from, .sp-leave-to { flex: 0!important; min-width: 0!important; opacity: 0; overflow: hidden }
</style>
