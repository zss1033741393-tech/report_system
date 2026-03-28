<template>
  <div class="app">
    <aside class="sidebar">
      <SessionList
        :sessions="sessions" :active-id="sid"
        @select="switchSession" @new-session="newSession" @delete="delSession"
      />
    </aside>

    <section :class="['chat', { 'chat--full': !showRight }]">
      <div class="chat__msgs" ref="msgsCtn">

        <!-- 欢迎页 -->
        <div v-if="!messages.length && !thinkSteps.length && !toolCalls.length" class="welcome">
          <div class="welcome__hero">
            <div class="welcome__icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <rect width="48" height="48" rx="12" fill="var(--c-primary-bg)"/>
                <path d="M14 20h20M14 28h12M24 14l8 6-8 6" stroke="var(--c-primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
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

        <!-- 历史消息 -->
        <ChatMessage v-for="m in messages" :key="m.id || m._tid" :msg="m" @confirm="onConfirm" />

        <!-- 当前轮次（流式中）：工具调用 + 思考步骤 + 回复 -->
        <div v-if="thinkSteps.length || toolCalls.length || streamReply || designSteps.length" class="cur">
          <SkillFactoryProgress v-if="designSteps.length" :design-steps="designSteps" />
          <ThinkingBlock v-if="thinkSteps.length" :steps="thinkSteps" />

          <!-- ✨ 新增：ReAct 工具调用可视化 -->
          <ToolCallBlock v-if="toolCalls.length" :calls="toolCalls" />

          <ChatMessage
            v-if="streamReply"
            :msg="{ role: 'assistant', content: streamReply, msg_type: 'text', created_at: new Date().toISOString() }"
          />
        </div>
      </div>

      <QueryInput :loading="loading" @send="send" />
    </section>

    <!-- 右侧面板折叠 tab -->
    <div v-if="!showRight && (hasOutline || hasReport)" class="edge-tab" @click="showRight = true">
      <span class="edge-tab__icon">{{ hasReport ? '📊' : '📋' }}</span>
      <span class="edge-tab__text">{{ hasReport ? '报告' : '大纲' }}</span>
    </div>

    <transition name="sp">
      <section v-if="showRight" class="right-side">
        <RightPanel
          :outline-content="outContent" :outline-loading="outLoading" :anchor="anchor"
          :report-html="reportHtml" :report-title="reportTitle" :report-loading="reportLoading"
          :has-report="hasReport" :has-outline="hasOutline"
          @close="showRight = false"
        />
      </section>
    </transition>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import SessionList from '../components/SessionList.vue'
import ChatMessage from '../components/ChatMessage.vue'
import QueryInput from '../components/QueryInput.vue'
import RightPanel from '../components/RightPanel.vue'
import ThinkingBlock from '../components/ThinkingBlock.vue'
import SkillFactoryProgress from '../components/SkillFactoryProgress.vue'
import ToolCallBlock from '../components/ToolCallBlock.vue'
import { sendMessage, fetchSessions, fetchMessages, fetchOutlineState, deleteSession } from '../utils/sse.js'

// ─── 状态 ──────────────────────────────────────────────────────────────────
const sessions = ref([])
const sid = ref('')
const messages = ref([])
const loading = ref(false)

// 右侧面板
const outContent = ref('')
const outLoading = ref(false)
const anchor = ref(null)
const reportHtml = ref('')
const reportTitle = ref('')
const reportLoading = ref(false)
const hasOutline = ref(false)
const hasReport = ref(false)
const showRight = ref(false)

// 流式中间状态
const streamReply = ref('')
const thinkSteps = ref([])
const designSteps = ref([])
const toolCalls = ref([])   // ✨ 新增：当前轮次工具调用列表

const msgsCtn = ref(null)
let ctrl = null

const exampleGroups = [
  { icon: '🔍', label: '快速分析', items: ['帮我分析政企OTN升级的机会点', 'fgOTN部署，从时延方面分析'] },
  { icon: '🎯', label: '精准筛选', items: ['从传送网络容量角度分析fgOTN，不看低阶交叉，只看金融行业'] },
  { icon: '📝', label: '能力沉淀', items: ['输入看网逻辑文本，系统自动解析并生成可复用的分析能力'] },
]

// ─── 生命周期 ──────────────────────────────────────────────────────────────
onMounted(async () => { await loadSessions() })

// ─── 会话管理 ──────────────────────────────────────────────────────────────
async function loadSessions() {
  try { sessions.value = await fetchSessions() } catch { sessions.value = [] }
}

async function switchSession(id) {
  if (ctrl) { ctrl.abort(); ctrl = null }
  // 重置流式状态
  loading.value = false
  outLoading.value = false
  reportLoading.value = false
  streamReply.value = ''
  thinkSteps.value = []
  designSteps.value = []
  toolCalls.value = []           // ✨ 重置工具调用
  reportHtml.value = ''
  reportTitle.value = ''

  sid.value = id
  try { messages.value = await fetchMessages(id) } catch { messages.value = [] }

  // 加载大纲状态
  try {
    const s = await fetchOutlineState(id)
    if (s?.outline_json) {
      outContent.value = rJson(s.outline_json)
      anchor.value = s.anchor_info
      hasOutline.value = true
    } else {
      outContent.value = ''
      anchor.value = null
      hasOutline.value = false
    }
  } catch {
    outContent.value = ''
    anchor.value = null
    hasOutline.value = false
  }

  // 从历史消息逆向查找报告（保持原有兼容逻辑）
  hasReport.value = false
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const meta = messages.value[i].metadata
    if (meta?.report_html) {
      reportHtml.value = meta.report_html
      reportTitle.value = meta.report_title || '报告'
      hasReport.value = true
      break
    }
  }

  showRight.value = hasOutline.value || hasReport.value
  await scroll()
}

async function newSession() {
  sid.value = uuidv4()
  messages.value = []
  outContent.value = ''
  anchor.value = null
  streamReply.value = ''
  thinkSteps.value = []
  designSteps.value = []
  toolCalls.value = []           // ✨ 重置工具调用
  reportHtml.value = ''
  reportTitle.value = ''
  hasOutline.value = false
  hasReport.value = false
  showRight.value = false
  await loadSessions()
}

async function delSession(id) {
  try {
    await deleteSession(id)
    await loadSessions()
    if (id === sid.value) {
      sessions.value.length ? await switchSession(sessions.value[0].id) : await newSession()
    }
  } catch {}
}

// ─── 发送消息 ──────────────────────────────────────────────────────────────
function send(text) {
  if (!text.trim() || loading.value) return
  if (!sid.value) sid.value = uuidv4()

  messages.value.push({
    _tid: Date.now(), role: 'user', content: text,
    msg_type: 'text', created_at: new Date().toISOString()
  })
  scroll()

  loading.value = true
  streamReply.value = ''
  outLoading.value = false
  reportLoading.value = false
  thinkSteps.value = []
  designSteps.value = []
  toolCalls.value = []           // ✨ 每次发送清空工具调用

  let outStarted = false, reportStarted = false, compThinking = null, outMdSnap = ''

  ctrl = sendMessage(sid.value, text, {

    // ─── ✨ 新增：ReAct 工具事件处理 ────────────────────────────────────

    onToolCall(d) {
      // 新工具调用开始：追加一个 running 状态的条目
      toolCalls.value.push({
        id: `${d.name}_${Date.now()}`,
        name: d.name,
        args: d.args || {},
        status: 'running',
        result: null,
        error: false,
      })
      scroll()
    },

    onToolResult(d) {
      // 找到对应的 running 条目，更新状态和结果
      const tool_name = d.tool_name || d.name
      for (let i = toolCalls.value.length - 1; i >= 0; i--) {
        if (toolCalls.value[i].name === tool_name && toolCalls.value[i].status === 'running') {
          toolCalls.value[i] = {
            ...toolCalls.value[i],
            status: d.error ? 'error' : 'done',
            result: d.content || '',
            error: !!d.error,
          }
          break
        }
      }
      scroll()
    },

    // ─── 原有业务事件（向后兼容，原封不动）─────────────────────────────

    onThinkingStep(d) {
      if (d.status === 'done') {
        for (let i = thinkSteps.value.length - 1; i >= 0; i--) {
          if (thinkSteps.value[i].step === d.step && thinkSteps.value[i].status === 'running') {
            thinkSteps.value[i] = d; scroll(); return
          }
        }
      }
      thinkSteps.value.push(d); scroll()
    },

    onThinkingComplete(t) { compThinking = t },

    onChatReply(c) { streamReply.value = c; scroll() },

    onOutlineChunk(c) {
      if (!outStarted) {
        outContent.value = ''; outLoading.value = true
        outStarted = true; showRight.value = true; hasOutline.value = true; outMdSnap = ''
      }
      outContent.value += c; outMdSnap += c
    },

    onOutlineDone(a) { outLoading.value = false; anchor.value = a },

    onOutlineUpdated(j) {
      if (j) {
        const md = rJson(j); outContent.value = md; outMdSnap = md
        hasOutline.value = true; showRight.value = true
      }
    },

    onOutlineClipped() {},

    onReportChunk(c) {
      if (!reportStarted) {
        reportHtml.value = ''; reportLoading.value = true
        reportStarted = true; showRight.value = true; hasReport.value = true
      }
      reportHtml.value += c
    },

    onReportDone(d) {
      reportLoading.value = false
      reportTitle.value = d?.title || '报告'
      hasReport.value = true
    },

    onDesignStep(d) {
      const existing = designSteps.value.find(s => s.step === d.step)
      if (existing) { Object.assign(existing, d) } else { designSteps.value.push(d) }
      scroll()
    },

    onPersistPrompt(d) {
      messages.value.push({
        _tid: Date.now(), role: 'assistant', content: d.message,
        msg_type: 'persist_prompt', metadata: { context_key: d.context_key },
        created_at: new Date().toISOString()
      })
      scroll()
    },

    onSkillPersisted(d) {
      messages.value.push({
        _tid: Date.now(), role: 'assistant',
        content: `看网能力「${d.skill_name}」已沉淀到 ${d.skill_dir}`,
        msg_type: 'text', created_at: new Date().toISOString()
      })
    },

    onDataExecuting() {},
    onDataExecuted() {},
    onConfirmRequired() {},
    onAwaitingConfirm() {},

    onError(m) {
      streamReply.value = ''
      messages.value.push({
        _tid: Date.now(), role: 'assistant', content: m,
        msg_type: 'error', created_at: new Date().toISOString()
      })
      scroll()
    },

    onDone() {
      loading.value = false; outLoading.value = false; reportLoading.value = false

      const meta = {}
      if (compThinking?.length) meta.thinking = compThinking
      else if (thinkSteps.value.length) meta.thinking = [...thinkSteps.value]
      if (outMdSnap) meta.outline_md = outMdSnap
      if (designSteps.value.length) meta.design_steps = [...designSteps.value]
      if (reportHtml.value) meta.report_html = reportHtml.value
      if (reportTitle.value) meta.report_title = reportTitle.value
      // ✨ 将本轮工具调用记录存入 metadata（可在消息历史中查看）
      if (toolCalls.value.length) meta.tool_calls = [...toolCalls.value]

      const content = streamReply.value || (designSteps.value.length ? '看网能力分析完成' : '处理完成')
      messages.value.push({
        _tid: Date.now(), role: 'assistant', content,
        msg_type: designSteps.value.length ? 'design_result' : 'text',
        created_at: new Date().toISOString(),
        metadata: Object.keys(meta).length ? meta : null
      })

      streamReply.value = ''
      thinkSteps.value = []
      designSteps.value = []
      toolCalls.value = []        // ✨ 本轮工具调用已存入消息，清空流式状态

      scroll(); loadSessions()
    },
  })
}

// ─── 确认动作 ──────────────────────────────────────────────────────────────
function onConfirm(a) {
  if (a.action === 'persist') {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.msg_type === 'persist_prompt' && m.metadata?.context_key) {
        send(`保存为看网能力，context_key=${m.metadata.context_key}`); return
      }
    }
    send('保存为看网能力')
  } else if (a.action === 'skip') {
    send('暂不保存')
  } else {
    send(`选择${a.label}：${a.name}`)
  }
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────
async function scroll() {
  await nextTick()
  const e = msgsCtn.value; if (e) e.scrollTop = e.scrollHeight
}

function rJson(tree, d = 0) {
  if (!tree?.name) return ''
  let md = ''; const p = '#'.repeat(Math.min(d + 1, 6))
  if (d === 0) md += `${p} ${tree.name}\n\n`
  else if (tree.level !== 5) { md += `${p} ${tree.name}\n\n`; if (tree.intro_text) md += `${tree.intro_text}\n\n` }
  for (const c of tree.children || []) md += rJson(c, d + 1)
  return md
}
</script>

<style scoped>
.app { display: flex; height: 100vh; overflow: hidden; background: var(--c-bg); font-family: var(--font-sans) }
.sidebar { width: 260px; flex-shrink: 0 }
.chat { flex: 4; min-width: 320px; display: flex; flex-direction: column; border-left: 1px solid var(--c-border); border-right: 1px solid var(--c-border); background: var(--c-bg-elevated); transition: flex .3s var(--ease) }
.chat--full { flex: 10 }
.chat__msgs { flex: 1; overflow-y: auto; padding: 24px var(--sp-md) }
.cur { padding: 14px 0 }
.right-side { flex: 5; min-width: 340px; overflow: hidden; border-left: 1px solid var(--c-border) }

/* 欢迎页 */
.welcome { display: flex; flex-direction: column; align-items: center; padding: 40px 16px; gap: 32px }
.welcome__hero { display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center }
.welcome__title { font-size: 24px; font-weight: 700; color: var(--c-text); margin: 0 }
.welcome__desc { font-size: 14px; color: var(--c-text-secondary); margin: 0; max-width: 400px; line-height: 1.6 }
.welcome__cards { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; max-width: 680px }
.welcome__hint { font-size: 12px; color: var(--c-text-tertiary) }
.wcard { background: var(--c-bg); border: 1px solid var(--c-border); border-radius: 12px; padding: 16px; min-width: 200px; flex: 1; max-width: 240px }
.wcard__header { display: flex; align-items: center; gap: 6px; margin-bottom: 10px }
.wcard__icon { font-size: 16px }
.wcard__label { font-size: 13px; font-weight: 600; color: var(--c-text) }
.wcard__item { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 8px; cursor: pointer; transition: background .15s; gap: 8px }
.wcard__item:hover { background: var(--c-primary-bg) }
.wcard__text { font-size: 12px; color: var(--c-text-secondary); line-height: 1.5 }
.wcard__arrow { color: var(--c-text-tertiary); font-size: 13px; flex-shrink: 0 }

/* Edge tab */
.edge-tab { position: fixed; right: 0; top: 50%; transform: translateY(-50%); background: var(--c-primary); color: #fff; padding: 12px 6px; border-radius: 8px 0 0 8px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 4px; box-shadow: var(--shadow-md); z-index: 10 }
.edge-tab__icon { font-size: 16px }
.edge-tab__text { font-size: 11px; writing-mode: vertical-rl; font-weight: 500 }

/* 动画 */
.sp-enter-active, .sp-leave-active { transition: all .3s var(--ease) }
.sp-enter-from, .sp-leave-to { opacity: 0; transform: translateX(40px) }
</style>
