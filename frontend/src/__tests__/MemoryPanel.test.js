/**
 * MemoryPanel.vue 组件测试
 *
 * 验证：
 *   - sessionId 变化时自动调用 GET /api/v1/memory/{id}
 *   - 空 facts 显示"暂无跨对话记忆"
 *   - confidence >= 0.8 显示"高置信"
 *   - 点击"清除"按钮调用 DELETE /api/v1/memory/{id}
 *   - 清除后 facts 为空
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MemoryPanel from '../components/MemoryPanel.vue'

// Mock global fetch
function mockFetch(responses) {
  let callIndex = 0
  global.fetch = vi.fn().mockImplementation(() => {
    const resp = Array.isArray(responses) ? responses[callIndex++] : responses
    return Promise.resolve({
      json: () => Promise.resolve(resp),
      ok: true,
    })
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('MemoryPanel - 初始加载', () => {
  it('sessionId 为空时不请求 API，显示空状态', async () => {
    global.fetch = vi.fn()
    const wrapper = mount(MemoryPanel, { props: { sessionId: '' } })
    await flushPromises()
    expect(global.fetch).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('暂无跨对话记忆')
  })

  it('sessionId 非空时自动调用 GET /api/v1/memory/{id}', async () => {
    mockFetch({ memory: { facts: [] } })
    mount(MemoryPanel, { props: { sessionId: 'session-123' } })
    await flushPromises()
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/memory/session-123')
  })

  it('有 facts 时渲染列表', async () => {
    mockFetch({
      memory: {
        facts: [
          { content: '用户偏好金融行业分析', confidence: 0.9, source: 'conversation' },
        ]
      }
    })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-1' } })
    await flushPromises()
    expect(wrapper.text()).toContain('用户偏好金融行业分析')
  })
})

describe('MemoryPanel - 空状态', () => {
  it('facts 为空时显示"暂无跨对话记忆"', async () => {
    mockFetch({ memory: { facts: [] } })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-empty' } })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无跨对话记忆')
  })

  it('空状态不渲染 fact 列表', async () => {
    mockFetch({ memory: { facts: [] } })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-empty2' } })
    await flushPromises()
    expect(wrapper.findAll('.mp__fact')).toHaveLength(0)
  })
})

describe('MemoryPanel - 置信度分级', () => {
  it('confidence >= 0.8 显示"高置信"', async () => {
    mockFetch({
      memory: {
        facts: [{ content: '高置信内容', confidence: 0.9 }]
      }
    })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-high' } })
    await flushPromises()
    expect(wrapper.text()).toContain('高置信')
  })

  it('confidence >= 0.8 有 mp__fact-conf--high class', async () => {
    mockFetch({
      memory: {
        facts: [{ content: '高置信内容', confidence: 0.85 }]
      }
    })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-high2' } })
    await flushPromises()
    expect(wrapper.find('.mp__fact-conf--high').exists()).toBe(true)
  })

  it('0.5 <= confidence < 0.8 显示"中等"', async () => {
    mockFetch({
      memory: {
        facts: [{ content: '中等内容', confidence: 0.6 }]
      }
    })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-med' } })
    await flushPromises()
    expect(wrapper.text()).toContain('中等')
  })

  it('confidence < 0.5 显示"低置信"', async () => {
    mockFetch({
      memory: {
        facts: [{ content: '低置信内容', confidence: 0.3 }]
      }
    })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-low' } })
    await flushPromises()
    expect(wrapper.text()).toContain('低置信')
  })
})

describe('MemoryPanel - 清除操作', () => {
  it('点击清除按钮调用 DELETE /api/v1/memory/{id}', async () => {
    let deleteCalledUrl = null
    global.fetch = vi.fn().mockImplementation((url, opts) => {
      if (opts?.method === 'DELETE') {
        deleteCalledUrl = url
      }
      return Promise.resolve({
        json: () => Promise.resolve({ memory: { facts: [{ content: '记忆1', confidence: 0.9 }] } }),
        ok: true,
      })
    })

    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-del' } })
    await flushPromises()

    await wrapper.find('.mp__clear').trigger('click')
    await flushPromises()

    expect(deleteCalledUrl).toBe('/api/v1/memory/sid-del')
  })

  it('清除后 facts 变为空，显示"暂无跨对话记忆"', async () => {
    let callCount = 0
    global.fetch = vi.fn().mockImplementation((url, opts) => {
      if (opts?.method === 'DELETE') {
        return Promise.resolve({ json: () => Promise.resolve({ success: true }), ok: true })
      }
      // GET 请求
      callCount++
      const facts = callCount === 1 ? [{ content: '记忆内容', confidence: 0.9 }] : []
      return Promise.resolve({
        json: () => Promise.resolve({ memory: { facts } }),
        ok: true,
      })
    })

    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-del2' } })
    await flushPromises()
    expect(wrapper.text()).toContain('记忆内容')

    await wrapper.find('.mp__clear').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无跨对话记忆')
  })

  it('无 facts 时清除按钮处于禁用状态', async () => {
    mockFetch({ memory: { facts: [] } })
    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-empty-btn' } })
    await flushPromises()
    expect(wrapper.find('.mp__clear').attributes('disabled')).toBeDefined()
  })
})

describe('MemoryPanel - sessionId 变化', () => {
  it('sessionId 改变后重新加载数据', async () => {
    let fetchCount = 0
    global.fetch = vi.fn().mockImplementation(() => {
      fetchCount++
      return Promise.resolve({
        json: () => Promise.resolve({ memory: { facts: [] } }),
        ok: true,
      })
    })

    const wrapper = mount(MemoryPanel, { props: { sessionId: 'sid-a' } })
    await flushPromises()
    const countAfterFirst = fetchCount

    await wrapper.setProps({ sessionId: 'sid-b' })
    await flushPromises()

    expect(fetchCount).toBeGreaterThan(countAfterFirst)
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/memory/sid-b')
  })
})
