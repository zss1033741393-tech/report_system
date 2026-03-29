/**
 * useConversation composable 测试
 *
 * 验证：
 *   - 初始状态所有 ref 为空/false/[]
 *   - send() 触发后 loading=true，消息列表追加 user 消息
 *   - onToolCall 回调追加 {status:'running'} 的工具调用
 *   - onToolResult 更新对应工具状态为 done
 *   - onDone 后 loading=false，streamReply 追加到 messages
 *   - hasArtifacts = hasOutline || hasReport
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

// vi.mock is hoisted — define mock functions with vi.hoisted
const mocks = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  fetchSessions: vi.fn(),
  fetchMessages: vi.fn(),
  fetchArtifacts: vi.fn(),
  deleteSession: vi.fn(),
}))

vi.mock('../utils/sse.js', () => ({
  sendMessage: mocks.sendMessage,
  fetchSessions: mocks.fetchSessions,
  fetchMessages: mocks.fetchMessages,
  fetchArtifacts: mocks.fetchArtifacts,
  deleteSession: mocks.deleteSession,
}))

vi.mock('uuid', () => ({ v4: () => 'test-uuid-1234' }))

import { useConversation } from '../composables/useConversation.js'

function makeComposable() {
  const msgsCtnRef = ref(null)
  return useConversation(msgsCtnRef)
}

// Helper: get the handlers passed to the last sendMessage call
function getHandlers() {
  const calls = mocks.sendMessage.mock.calls
  if (!calls.length) return {}
  return calls[calls.length - 1][2] || {}
}

beforeEach(() => {
  vi.clearAllMocks()
  // Setup default mock return values
  mocks.sendMessage.mockImplementation((_sid, _text, handlers) => ({ abort: vi.fn() }))
  mocks.fetchSessions.mockResolvedValue([])
  mocks.fetchMessages.mockResolvedValue([])
  mocks.fetchArtifacts.mockResolvedValue({})
  mocks.deleteSession.mockResolvedValue({})
})

describe('useConversation - 初始状态', () => {
  it('sessions 初始为空数组', () => {
    const { sessions } = makeComposable()
    expect(sessions.value).toEqual([])
  })

  it('messages 初始为空数组', () => {
    const { messages } = makeComposable()
    expect(messages.value).toEqual([])
  })

  it('loading 初始为 false', () => {
    const { loading } = makeComposable()
    expect(loading.value).toBe(false)
  })

  it('toolCalls 初始为空数组', () => {
    const { toolCalls } = makeComposable()
    expect(toolCalls.value).toEqual([])
  })

  it('hasOutline 初始为 false', () => {
    const { hasOutline } = makeComposable()
    expect(hasOutline.value).toBe(false)
  })

  it('hasReport 初始为 false', () => {
    const { hasReport } = makeComposable()
    expect(hasReport.value).toBe(false)
  })

  it('hasArtifacts 初始为 false', () => {
    const { hasArtifacts } = makeComposable()
    expect(hasArtifacts.value).toBe(false)
  })

  it('streamReply 初始为空字符串', () => {
    const { streamReply } = makeComposable()
    expect(streamReply.value).toBe('')
  })
})

describe('useConversation - send()', () => {
  it('send() 后 loading 变为 true', () => {
    const { send, loading } = makeComposable()
    send('测试消息')
    expect(loading.value).toBe(true)
  })

  it('send() 后 messages 追加 user 消息', () => {
    const { send, messages } = makeComposable()
    send('用户输入')
    expect(messages.value.length).toBe(1)
    expect(messages.value[0].role).toBe('user')
    expect(messages.value[0].content).toBe('用户输入')
  })

  it('send() 调用 sendMessage()', () => {
    const { send } = makeComposable()
    send('测试内容')
    expect(mocks.sendMessage).toHaveBeenCalledTimes(1)
  })

  it('send() 空字符串不触发', () => {
    const { send, loading } = makeComposable()
    send('   ')
    expect(loading.value).toBe(false)
    expect(mocks.sendMessage).not.toHaveBeenCalled()
  })

  it('loading 为 true 时不再次触发 send()', () => {
    const { send } = makeComposable()
    send('第一条')
    send('第二条')
    expect(mocks.sendMessage).toHaveBeenCalledTimes(1)
  })
})

describe('useConversation - onToolCall', () => {
  it('onToolCall 追加 status=running 的工具调用', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall } = getHandlers()
    onToolCall?.({ name: 'search_skill', args: { query: '容量' } })
    expect(toolCalls.value.length).toBe(1)
    expect(toolCalls.value[0].name).toBe('search_skill')
    expect(toolCalls.value[0].status).toBe('running')
  })

  it('onToolCall 多次调用追加多个工具', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall } = getHandlers()
    onToolCall?.({ name: 'get_session_status', args: {} })
    onToolCall?.({ name: 'search_skill', args: { query: '分析' } })
    expect(toolCalls.value.length).toBe(2)
  })

  it('onToolCall 追加的项有 _expanded=false', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall } = getHandlers()
    onToolCall?.({ name: 'execute_data', args: {} })
    expect(toolCalls.value[0]._expanded).toBe(false)
  })
})

describe('useConversation - onToolResult', () => {
  it('onToolResult 将对应工具 status 更新为 done', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall, onToolResult } = getHandlers()
    onToolCall?.({ name: 'search_skill', args: {} })
    onToolResult?.({ name: 'search_skill', content: '搜索结果', success: true })
    expect(toolCalls.value[0].status).toBe('done')
  })

  it('onToolResult 设置 result 和 success', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall, onToolResult } = getHandlers()
    onToolCall?.({ name: 'search_skill', args: {} })
    onToolResult?.({ name: 'search_skill', content: '结果内容', success: true })
    expect(toolCalls.value[0].result).toBe('结果内容')
    expect(toolCalls.value[0].success).toBe(true)
  })

  it('success=false 时正确标记失败', () => {
    const { send, toolCalls } = makeComposable()
    send('触发工具')
    const { onToolCall, onToolResult } = getHandlers()
    onToolCall?.({ name: 'execute_data', args: {} })
    onToolResult?.({ name: 'execute_data', content: '执行失败', success: false })
    expect(toolCalls.value[0].success).toBe(false)
  })
})

describe('useConversation - onDone', () => {
  it('onDone 后 loading 变为 false', () => {
    const { send, loading } = makeComposable()
    send('测试')
    expect(loading.value).toBe(true)
    const { onDone } = getHandlers()
    onDone?.()
    expect(loading.value).toBe(false)
  })

  it('onDone 后 streamReply 内容追加到 messages', () => {
    const { send, messages } = makeComposable()
    send('问题')
    const { onChatReply, onDone } = getHandlers()
    onChatReply?.('这是 AI 的回答')
    onDone?.()
    const assistantMsgs = messages.value.filter(m => m.role === 'assistant')
    expect(assistantMsgs.length).toBe(1)
    expect(assistantMsgs[0].content).toBe('这是 AI 的回答')
  })

  it('onDone 后 streamReply 清空', () => {
    const { send, streamReply } = makeComposable()
    send('问题')
    const { onChatReply, onDone } = getHandlers()
    onChatReply?.('回答内容')
    onDone?.()
    expect(streamReply.value).toBe('')
  })

  it('onDone 后 toolCalls 清空', () => {
    const { send, toolCalls } = makeComposable()
    send('问题')
    const { onToolCall, onDone } = getHandlers()
    onToolCall?.({ name: 'search_skill', args: {} })
    onDone?.()
    expect(toolCalls.value).toEqual([])
  })
})

describe('useConversation - hasArtifacts 计算属性', () => {
  it('hasOutline=true 时 hasArtifacts=true', () => {
    const { send, hasArtifacts } = makeComposable()
    send('生成大纲')
    const { onOutlineChunk } = getHandlers()
    onOutlineChunk?.('第一节')
    expect(hasArtifacts.value).toBe(true)
  })

  it('hasReport=true 时 hasArtifacts=true', () => {
    const { send, hasArtifacts } = makeComposable()
    send('生成报告')
    const { onReportChunk } = getHandlers()
    onReportChunk?.('<html>报告内容')
    expect(hasArtifacts.value).toBe(true)
  })

  it('两者均为 false 时 hasArtifacts=false', () => {
    const { hasArtifacts } = makeComposable()
    expect(hasArtifacts.value).toBe(false)
  })
})

describe('useConversation - handleConfirm', () => {
  it('action=persist 时调用 send()', () => {
    const { handleConfirm } = makeComposable()
    handleConfirm({ action: 'persist' })
    expect(mocks.sendMessage).toHaveBeenCalled()
  })

  it('action=skip 时调用 send()', () => {
    const { handleConfirm } = makeComposable()
    handleConfirm({ action: 'skip' })
    expect(mocks.sendMessage).toHaveBeenCalled()
  })
})
