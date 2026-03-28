// 使用相对路径——通过 Vite proxy 转发到后端，无需写死 IP
const API = ''

export function sendMessage(sid, message, cb) {
  const ctrl = new AbortController()
  fetch(`${API}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sid, message }),
    signal: ctrl.signal,
  }).then(async res => {
    if (!res.ok) { cb.onError?.(`请求失败:${res.status}`); return }
    const reader = res.body.getReader(), dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read(); if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n'); buf = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const d = JSON.parse(line.slice(6))
          switch (d.type) {

            // ─── 新增：ReAct 通用工具事件 ─────────────────────────────────
            case 'tool_call':
              // { type: 'tool_call', name, args }
              cb.onToolCall?.(d)
              break

            case 'tool_result':
              // { type: 'tool_result', tool_name, content, error? }
              cb.onToolResult?.(d)
              break

            // ─── 保留：原有业务事件（向后兼容，一字不改）─────────────────

            case 'chat_reply':
              cb.onChatReply?.(d.content)
              break

            case 'thinking_step':
              cb.onThinkingStep?.(d)
              break

            case 'thinking_complete':
              cb.onThinkingComplete?.(d.thinking)
              break

            case 'outline_chunk':
              cb.onOutlineChunk?.(d.content)
              break

            case 'outline_done':
              cb.onOutlineDone?.(d.anchor)
              break

            case 'outline_updated':
              cb.onOutlineUpdated?.(d.outline_json)
              break

            case 'outline_clipped':
              cb.onOutlineClipped?.(d)
              break

            case 'report_chunk':
              cb.onReportChunk?.(d.content)
              break

            case 'report_done':
              cb.onReportDone?.(d)
              break

            case 'design_step':
              cb.onDesignStep?.(d)
              break

            case 'persist_prompt':
              cb.onPersistPrompt?.(d)
              break

            case 'skill_persisted':
              cb.onSkillPersisted?.(d)
              break

            case 'skill_factory_done':
              cb.onSkillFactoryDone?.(d)
              break

            case 'data_executing':
              cb.onDataExecuting?.(d)
              break

            case 'data_executed':
              cb.onDataExecuted?.(d)
              break

            case 'awaiting_confirm':
              cb.onAwaitingConfirm?.(d)
              break

            case 'confirm_required':
              cb.onConfirmRequired?.(d)
              break

            case 'error':
              cb.onError?.(d.message)
              break

            case 'done':
              cb.onDone?.()
              break
          }
        } catch { /* 忽略非 JSON 行 */ }
      }
    }
    cb.onDone?.()
  }).catch(e => {
    if (e.name !== 'AbortError') cb.onError?.(e.message)
  })
  return ctrl
}

export async function fetchSessions(limit = 50) {
  const r = await fetch(`${API}/api/v1/sessions?limit=${limit}`)
  return (await r.json()).sessions || []
}

export async function createSession() {
  const r = await fetch(`${API}/api/v1/sessions`, { method: 'POST' })
  return await r.json()
}

export async function fetchMessages(sid, limit = 100) {
  const r = await fetch(`${API}/api/v1/sessions/${sid}/messages?limit=${limit}`)
  return (await r.json()).messages || []
}

export async function fetchOutlineState(sid) {
  const r = await fetch(`${API}/api/v1/sessions/${sid}/outline`)
  return await r.json()
}

export async function deleteSession(sid) {
  await fetch(`${API}/api/v1/sessions/${sid}`, { method: 'DELETE' })
}
