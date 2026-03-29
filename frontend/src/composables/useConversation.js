import { ref } from 'vue'
import { fetchMessages, fetchArtifacts } from '../utils/sse.js'

export function useConversation() {
  const messages = ref([])
  const outline = ref(null)       // parsed outline JSON
  const anchorInfo = ref(null)
  const report = ref(null)        // { html, title }
  const toolCalls = ref([])       // current-turn tool call records
  const isLoading = ref(false)

  function reset() {
    messages.value = []
    outline.value = null
    anchorInfo.value = null
    report.value = null
    toolCalls.value = []
    isLoading.value = false
  }

  async function loadSession(sid) {
    reset()
    isLoading.value = true
    try {
      const [msgs, artifacts] = await Promise.all([
        fetchMessages(sid),
        fetchArtifacts(sid),
      ])
      messages.value = msgs
      if (artifacts.outline_json) {
        outline.value = artifacts.outline_json
        anchorInfo.value = artifacts.anchor_info || null
      }
      if (artifacts.report_html) {
        report.value = { html: artifacts.report_html, title: artifacts.report_title || '报告' }
      }
    } finally {
      isLoading.value = false
    }
  }

  function addMessage(msg) {
    messages.value.push(msg)
  }

  function onToolCall(d) {
    toolCalls.value.push({
      id: d.id || d.name + '_' + Date.now(),
      name: d.name,
      args: d.args || d.arguments || {},
      status: 'running',
      summary: '',
      success: true,
    })
  }

  function onToolResult(d) {
    const tc = toolCalls.value.find(t => t.name === d.name && t.status === 'running')
    if (tc) {
      tc.status = 'done'
      tc.summary = d.summary || ''
      tc.success = d.success !== false
      if (!tc.success) tc.status = 'error'
    }
  }

  function clearToolCalls() {
    toolCalls.value = []
  }

  function updateOutline(outlineJson, anchor) {
    outline.value = outlineJson
    if (anchor !== undefined) anchorInfo.value = anchor
  }

  function updateReport(html, title) {
    report.value = { html, title: title || '报告' }
  }

  return {
    messages,
    outline,
    anchorInfo,
    report,
    toolCalls,
    isLoading,
    reset,
    loadSession,
    addMessage,
    onToolCall,
    onToolResult,
    clearToolCalls,
    updateOutline,
    updateReport,
  }
}
