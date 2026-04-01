<template>
  <div class="app">
    <aside class="sidebar">
      <SessionList
        :sessions="sessions"
        :active-id="sid"
        @select="switchSession"
        @new-session="newSession"
        @delete="delSession"
      />
    </aside>

    <section :class="['chat', { 'chat--full': !showOutline }]">
      <div class="chat__msgs" ref="msgsCtn">
        <div v-if="!messages.length && !thinkSteps.length" class="chat__welcome">
          <h2>智能报告大纲生成</h2>
          <p>描述您的分析需求</p>
          <div class="exs">
            <div v-for="e in examples" :key="e" class="ex" @click="send(e)">{{ e }}</div>
          </div>
        </div>

        <ChatMessage
          v-for="m in messages"
          :key="m.id || m._tid"
          :msg="m"
          @confirm="onConfirm"
        />

        <div v-if="thinkSteps.length || streamReply" class="cur">
          <ThinkingBlock v-if="thinkSteps.length" :steps="thinkSteps" />
          <ChatMessage
            v-if="streamReply"
            :msg="{ role: 'assistant', content: streamReply, msg_type: 'text', created_at: new Date().toISOString() }"
          />
        </div>
      </div>
      <QueryInput :loading="loading" @send="send" />
    </section>

    <div v-if="!showOutline && hasOutline" class="edge-tab" @click="showOutline = true">
      <span class="edge-tab__icon">📋</span>
      <span class="edge-tab__text">大纲</span>
    </div>

    <transition name="sp">
      <section v-if="showOutline" class="outline-side">
        <OutlineDisplay
          :content="outContent"
          :loading="outLoading"
          :anchor="anchor"
          @close="showOutline = false"
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
import OutlineDisplay from '../components/OutlineDisplay.vue'
import ThinkingBlock from '../components/ThinkingBlock.vue'
import { sendMessage, fetchSessions, fetchMessages, fetchOutlineState, deleteSession } from '../utils/sse.js'

const sessions = ref([])
const sid = ref('')
const messages = ref([])
const loading = ref(false)
const outContent = ref('')
const outLoading = ref(false)
const anchor = ref(null)
const streamReply = ref('')
const msgsCtn = ref(null)
const showOutline = ref(false)
const hasOutline = ref(false)
const thinkSteps = ref([])
let ctrl = null

const examples = [
  '帮我分析光纤网络升级方案',
  '企业行业分布怎么分析？',
  '政企OTN升级的评估维度有哪些？',
]

onMounted(async () => {
  await loadSessions()
  if (sessions.value.length) await switchSession(sessions.value[0].id)
})

async function loadSessions() {
  try {
    sessions.value = await fetchSessions()
  } catch {
    sessions.value = []
  }
}

async function switchSession(id) {
  if (ctrl) { ctrl.abort(); ctrl = null }
  loading.value = false
  outLoading.value = false
  streamReply.value = ''
  thinkSteps.value = []
  sid.value = id

  try {
    messages.value = await fetchMessages(id)
  } catch {
    messages.value = []
  }

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
      showOutline.value = false
    }
  } catch {
    outContent.value = ''
    anchor.value = null
    hasOutline.value = false
    showOutline.value = false
  }

  await scroll()
}

async function newSession() {
  sid.value = uuidv4()
  messages.value = []
  outContent.value = ''
  anchor.value = null
  streamReply.value = ''
  thinkSteps.value = []
  hasOutline.value = false
  showOutline.value = false
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

function send(text) {
  if (!text.trim() || loading.value) return
  if (!sid.value) sid.value = uuidv4()

  messages.value.push({
    _tid: Date.now(),
    role: 'user',
    content: text,
    msg_type: 'text',
    created_at: new Date().toISOString(),
  })
  scroll()
  loading.value = true
  streamReply.value = ''
  outLoading.value = false
  thinkSteps.value = []

  let outStarted = false
  let compThinking = null
  let outMdSnap = ''

  ctrl = sendMessage(sid.value, text, {
    onThinkingStep(d) {
      if (d.status === 'done') {
        for (let i = thinkSteps.value.length - 1; i >= 0; i--) {
          if (thinkSteps.value[i].step === d.step && thinkSteps.value[i].status === 'running') {
            thinkSteps.value[i] = d
            scroll()
            return
          }
        }
      }
      thinkSteps.value.push(d)
      scroll()
    },
    onThinkingComplete(t) {
      compThinking = t
    },
    onChatReply(c) {
      streamReply.value = c
      scroll()
    },
    onOutlineChunk(c) {
      if (!outStarted) {
        outContent.value = ''
        outLoading.value = true
        outStarted = true
        showOutline.value = true
        hasOutline.value = true
        outMdSnap = ''
      }
      outContent.value += c
      outMdSnap += c
    },
    onOutlineDone(a) {
      outLoading.value = false
      anchor.value = a
    },
    onOutlineUpdated(j) {
      if (j) {
        const md = rJson(j)
        outContent.value = md
        outMdSnap = md
        hasOutline.value = true
        showOutline.value = true
      }
    },
    onConfirmRequired() {},
    onError(m) {
      streamReply.value = ''
      messages.value.push({
        _tid: Date.now(),
        role: 'assistant',
        content: m,
        msg_type: 'error',
        created_at: new Date().toISOString(),
      })
      scroll()
    },
    onDone() {
      loading.value = false
      outLoading.value = false
      if (streamReply.value) {
        const meta = {}
        if (compThinking?.length) meta.thinking = compThinking
        else if (thinkSteps.value.length) meta.thinking = [...thinkSteps.value]
        if (outMdSnap) meta.outline_md = outMdSnap
        messages.value.push({
          _tid: Date.now(),
          role: 'assistant',
          content: streamReply.value,
          msg_type: 'text',
          created_at: new Date().toISOString(),
          metadata: Object.keys(meta).length ? meta : null,
        })
        streamReply.value = ''
      }
      thinkSteps.value = []
      scroll()
      loadSessions()
    },
  })
}

function onConfirm(a) {
  send(`选择${a.label}：${a.name}`)
}

async function scroll() {
  await nextTick()
  const el = msgsCtn.value
  if (el) el.scrollTop = el.scrollHeight
}

function rJson(tree, d = 0) {
  if (!tree?.name) return ''
  let md = ''
  const p = '#'.repeat(Math.min(d + 1, 6))

  if (d === 0) {
    md += `${p} ${tree.name}\n\n`
  } else if (tree.level === 5) {
    md += `- **${tree.name}**`
    const para = tree.paragraph
    if (para?.content) {
      const params = para.params || {}
      const preview = para.content.replace(/\{(\w+)\}/g, (match, key) => {
        const val = params[key]
        if (val == null) return `[${key}]`
        if (typeof val === 'object' && val !== null) return String(val.value ?? `[${key}]`)
        return String(val)
      })
      md += `：${preview}`
    }
    md += '\n'
  } else {
    md += `${p} ${tree.name}\n\n`
  }

  for (const c of tree.children || []) md += rJson(c, d + 1)
  return md
}
</script>

<style scoped>
.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: #f5f7fa;
}

.sidebar {
  width: 240px;
  flex-shrink: 0;
}

.chat {
  flex: 4;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e4e7ed;
  border-right: 1px solid #e4e7ed;
  background: #fff;
  transition: flex 0.3s;
}

.chat--full {
  flex: 10;
}

.chat__msgs {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.chat__welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
}

.chat__welcome h2 {
  font-size: 24px;
  color: #1a1a2e;
  margin: 0 0 8px;
}

.chat__welcome p {
  color: #909399;
  font-size: 14px;
  margin: 0 0 24px;
}

.exs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 360px;
}

.ex {
  padding: 12px 16px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

.ex:hover {
  border-color: #409eff;
  background: #ecf5ff;
  color: #409eff;
}

.edge-tab {
  flex-shrink: 0;
  width: 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: #409eff;
  color: #fff;
  cursor: pointer;
  writing-mode: vertical-rl;
  padding: 12px 4px;
  transition: background 0.2s;
}

.edge-tab:hover {
  background: #66b1ff;
}

.edge-tab__icon {
  font-size: 16px;
  writing-mode: horizontal-tb;
}

.edge-tab__text {
  font-size: 12px;
  letter-spacing: 2px;
  font-weight: 500;
}

.outline-side {
  flex: 6;
  min-width: 400px;
}

.sp-enter-active,
.sp-leave-active {
  transition: all 0.3s ease;
}

.sp-enter-from,
.sp-leave-to {
  flex: 0 !important;
  min-width: 0 !important;
  opacity: 0;
  overflow: hidden;
}
</style>
