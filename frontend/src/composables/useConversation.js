/**
 * useConversation —— 会话状态管理 Composable
 *
 * 将 MainView.vue 中 20+ 个 flat ref 封装为一个可组合单元，
 * 提供完整的会话生命周期管理：切换/新建/删除会话，发送消息，SSE 事件分发。
 */
import { ref, computed, nextTick } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import {
  sendMessage,
  fetchSessions,
  fetchMessages,
  fetchArtifacts,
  deleteSession,
} from '../utils/sse.js'

export function useConversation(msgsCtnRef) {
  // ─── 会话列表 ───────────────────────────────────────────────
  const sessions = ref([])
  const sid = ref('')

  // ─── 消息 & 流式状态 ─────────────────────────────────────────
  const messages = ref([])
  const loading = ref(false)
  const streamReply = ref('')
  const thinkSteps = ref([])
  const designSteps = ref([])
  const toolCalls = ref([])   // [{name, args, status, result, success, _expanded}]

  // ─── 大纲 & 报告 ─────────────────────────────────────────────
  const outContent = ref('')
  const outLoading = ref(false)
  const anchor = ref(null)
  const reportHtml = ref('')
  const reportTitle = ref('')
  const reportLoading = ref(false)
  const hasOutline = ref(false)
  const hasReport = ref(false)

  let ctrl = null   // AbortController for current SSE stream

  // ─── 计算属性 ─────────────────────────────────────────────────
  const hasArtifacts = computed(() => hasOutline.value || hasReport.value)
  const isStreaming = computed(() => loading.value)

  // ─── 滚动到底 ─────────────────────────────────────────────────
  async function scroll() {
    await nextTick()
    const el = msgsCtnRef?.value
    if (el) el.scrollTop = el.scrollHeight
  }

  // ─── 会话列表 ─────────────────────────────────────────────────
  async function loadSessions() {
    try { sessions.value = await fetchSessions() } catch { sessions.value = [] }
  }

  async function switchSession(id) {
    if (ctrl) { ctrl.abort(); ctrl = null }
    _resetStreamState()
    sid.value = id
    try { messages.value = await fetchMessages(id) } catch { messages.value = [] }
    try {
      const art = await fetchArtifacts(id)
      if (art?.outline_json) {
        outContent.value = _rJson(art.outline_json)
        anchor.value = art.anchor_info
        hasOutline.value = true
      } else {
        outContent.value = ''; anchor.value = null; hasOutline.value = false
      }
      if (art?.report?.html) {
        reportHtml.value = art.report.html
        reportTitle.value = art.report.title || '报告'
        hasReport.value = true
      } else { hasReport.value = false }
    } catch {
      outContent.value = ''; anchor.value = null
      hasOutline.value = false; hasReport.value = false
    }
    await scroll()
  }

  async function newSession() {
    sid.value = uuidv4()
    messages.value = []
    _resetArtifacts()
    _resetStreamState()
    await loadSessions()
  }

  async function removeSession(id) {
    try {
      await deleteSession(id)
      await loadSessions()
      if (id === sid.value) {
        sessions.value.length ? await switchSession(sessions.value[0].id) : await newSession()
      }
    } catch {}
  }

  // ─── 发送消息 ─────────────────────────────────────────────────
  function send(text) {
    if (!text.trim() || loading.value) return
    if (!sid.value) sid.value = uuidv4()
    messages.value.push({
      _tid: Date.now(), role: 'user', content: text,
      msg_type: 'text', created_at: new Date().toISOString(),
    })
    scroll()
    loading.value = true
    streamReply.value = ''
    outLoading.value = false
    reportLoading.value = false
    thinkSteps.value = []
    designSteps.value = []
    toolCalls.value = []

    let outStarted = false, reportStarted = false, compThinking = null, outMdSnap = ''

    ctrl = sendMessage(sid.value, text, {
      onToolCall(d) {
        toolCalls.value.push({ name: d.name, args: d.args, status: 'running', _expanded: false })
        scroll()
      },
      onToolResult(d) {
        for (let i = toolCalls.value.length - 1; i >= 0; i--) {
          if (toolCalls.value[i].name === d.name && toolCalls.value[i].status === 'running') {
            toolCalls.value[i] = { ...toolCalls.value[i], status: 'done', result: d.content, success: d.success !== false, _expanded: false }
            scroll(); return
          }
        }
      },
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
        if (!outStarted) { outContent.value = ''; outLoading.value = true; outStarted = true; hasOutline.value = true; outMdSnap = '' }
        outContent.value += c; outMdSnap += c
      },
      onOutlineDone(a) { outLoading.value = false; anchor.value = a },
      onOutlineUpdated(j) {
        if (j) { const md = _rJson(j); outContent.value = md; outMdSnap = md; hasOutline.value = true }
      },
      onOutlineClipped() {},
      onReportChunk(c) {
        if (!reportStarted) { reportHtml.value = ''; reportLoading.value = true; reportStarted = true; hasReport.value = true }
        reportHtml.value += c
      },
      onReportDone(d) { reportLoading.value = false; reportTitle.value = d?.title || '报告'; hasReport.value = true },
      onDesignStep(d) {
        const existing = designSteps.value.find(s => s.step === d.step)
        if (existing) { Object.assign(existing, d) } else { designSteps.value.push(d) }
        scroll()
      },
      onPersistPrompt(d) {
        messages.value.push({
          _tid: Date.now(), role: 'assistant', content: d.message,
          msg_type: 'persist_prompt', metadata: { context_key: d.context_key },
          created_at: new Date().toISOString(),
        })
        scroll()
      },
      onSkillPersisted(d) {
        messages.value.push({
          _tid: Date.now(), role: 'assistant',
          content: `看网能力「${d.skill_name}」已沉淀到 ${d.skill_dir}`,
          msg_type: 'text', created_at: new Date().toISOString(),
        })
      },
      onDataExecuting() {}, onDataExecuted() {}, onConfirmRequired() {},
      onError(m) {
        streamReply.value = ''
        messages.value.push({
          _tid: Date.now(), role: 'assistant', content: m,
          msg_type: 'error', created_at: new Date().toISOString(),
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
        if (toolCalls.value.length) meta.tool_calls = toolCalls.value.map(tc => ({ name: tc.name, status: tc.status, success: tc.success }))
        if (reportHtml.value) meta.report_html = reportHtml.value
        if (reportTitle.value) meta.report_title = reportTitle.value
        const content = streamReply.value || (designSteps.value.length ? '看网能力分析完成' : '处理完成')
        messages.value.push({
          _tid: Date.now(), role: 'assistant', content,
          msg_type: designSteps.value.length ? 'design_result' : 'text',
          created_at: new Date().toISOString(),
          metadata: Object.keys(meta).length ? meta : null,
        })
        streamReply.value = ''; thinkSteps.value = []; designSteps.value = []; toolCalls.value = []
        scroll(); loadSessions()
      },
    })
  }

  // ─── Confirm 处理 ─────────────────────────────────────────────
  function handleConfirm(action) {
    if (action.action === 'persist') {
      for (let i = messages.value.length - 1; i >= 0; i--) {
        const m = messages.value[i]
        if (m.msg_type === 'persist_prompt' && m.metadata?.context_key) {
          send(`保存为看网能力，context_key=${m.metadata.context_key}`); return
        }
      }
      send('保存为看网能力')
    } else if (action.action === 'skip') {
      send('暂不保存')
    } else {
      send(`选择${action.label}：${action.name}`)
    }
  }

  // ─── 内部工具 ─────────────────────────────────────────────────
  function _resetStreamState() {
    loading.value = false; outLoading.value = false; reportLoading.value = false
    streamReply.value = ''; thinkSteps.value = []; designSteps.value = []; toolCalls.value = []
  }
  function _resetArtifacts() {
    outContent.value = ''; anchor.value = null
    reportHtml.value = ''; reportTitle.value = ''
    hasOutline.value = false; hasReport.value = false
  }

  function _rJson(tree, d = 0) {
    if (!tree?.name) return ''
    let md = ''
    const p = '#'.repeat(Math.min(d + 1, 6))
    if (d === 0) md += `${p} ${tree.name}\n\n`
    else if (tree.level !== 5) { md += `${p} ${tree.name}\n\n`; if (tree.intro_text) md += `${tree.intro_text}\n\n` }
    for (const c of tree.children || []) md += _rJson(c, d + 1)
    return md
  }

  return {
    // state
    sessions, sid, messages, loading, streamReply,
    thinkSteps, designSteps, toolCalls,
    outContent, outLoading, anchor,
    reportHtml, reportTitle, reportLoading,
    hasOutline, hasReport,
    // computed
    hasArtifacts, isStreaming,
    // actions
    loadSessions, switchSession, newSession, removeSession,
    send, handleConfirm, scroll,
  }
}
