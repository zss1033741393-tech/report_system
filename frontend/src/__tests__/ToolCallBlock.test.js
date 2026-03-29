/**
 * ToolCallBlock.vue 组件测试
 *
 * 验证：
 *   - running 状态 UI（spinner + "执行中"）
 *   - done+success UI（✓ + "完成"）
 *   - done+success=false UI（✗ + "失败"）
 *   - session_id 参数被过滤，不显示
 *   - 详情/收起折叠交互
 *   - args 超 60 字符时截断
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolCallBlock from '../components/ToolCallBlock.vue'

function mountBlock(toolCalls) {
  return mount(ToolCallBlock, { props: { toolCalls } })
}

describe('ToolCallBlock - 运行态 UI', () => {
  it('running 状态显示 spinner', () => {
    const wrapper = mountBlock([{
      name: 'search_skill', args: { query: '容量' }, status: 'running', _expanded: false
    }])
    expect(wrapper.find('.tc-spinner').exists()).toBe(true)
  })

  it('running 状态显示"执行中"', () => {
    const wrapper = mountBlock([{
      name: 'get_session_status', args: {}, status: 'running', _expanded: false
    }])
    expect(wrapper.text()).toContain('执行中')
  })

  it('running 状态 item 有 tc-item--running class', () => {
    const wrapper = mountBlock([{
      name: 'execute_data', args: {}, status: 'running', _expanded: false
    }])
    expect(wrapper.find('.tc-item').classes()).toContain('tc-item--running')
  })
})

describe('ToolCallBlock - 成功态 UI', () => {
  it('done+success=true 显示 ✓', () => {
    const wrapper = mountBlock([{
      name: 'render_report', args: {}, status: 'done', success: true, result: '报告生成成功', _expanded: false
    }])
    expect(wrapper.text()).toContain('✓')
  })

  it('done+success=true 显示"完成"', () => {
    const wrapper = mountBlock([{
      name: 'render_report', args: {}, status: 'done', success: true, result: 'ok', _expanded: false
    }])
    expect(wrapper.text()).toContain('完成')
  })

  it('done+success=true 不显示 spinner', () => {
    const wrapper = mountBlock([{
      name: 'render_report', args: {}, status: 'done', success: true, _expanded: false
    }])
    expect(wrapper.find('.tc-spinner').exists()).toBe(false)
  })
})

describe('ToolCallBlock - 失败态 UI', () => {
  it('done+success=false 显示 ✗', () => {
    const wrapper = mountBlock([{
      name: 'execute_data', args: {}, status: 'done', success: false, result: '失败原因', _expanded: false
    }])
    expect(wrapper.text()).toContain('✗')
  })

  it('done+success=false 显示"失败"', () => {
    const wrapper = mountBlock([{
      name: 'execute_data', args: {}, status: 'done', success: false, _expanded: false
    }])
    expect(wrapper.text()).toContain('失败')
  })
})

describe('ToolCallBlock - 参数过滤', () => {
  it('session_id 不在 UI 中显示', () => {
    const wrapper = mountBlock([{
      name: 'search_skill',
      args: { session_id: 'my-secret-session', query: '容量分析' },
      status: 'done', success: true, _expanded: false
    }])
    expect(wrapper.text()).not.toContain('session_id')
    expect(wrapper.text()).not.toContain('my-secret-session')
  })

  it('其他参数正常显示', () => {
    const wrapper = mountBlock([{
      name: 'search_skill',
      args: { session_id: 'sid', query: '容量分析' },
      status: 'done', success: true, _expanded: false
    }])
    expect(wrapper.text()).toContain('容量分析')
  })

  it('只有 session_id 时不显示参数区', () => {
    const wrapper = mountBlock([{
      name: 'get_session_status',
      args: { session_id: 'sid' },
      status: 'done', success: true, _expanded: false
    }])
    expect(wrapper.find('.tc-args').exists()).toBe(false)
  })
})

describe('ToolCallBlock - 折叠交互', () => {
  it('有结果时显示"详情"按钮', () => {
    const wrapper = mountBlock([{
      name: 'search_skill', args: {}, status: 'done', success: true,
      result: '搜索结果内容', _expanded: false
    }])
    expect(wrapper.find('.tc-toggle').exists()).toBe(true)
    expect(wrapper.find('.tc-toggle').text()).toBe('详情')
  })

  it('点击"详情"按钮展开结果', async () => {
    const wrapper = mountBlock([{
      name: 'search_skill', args: {}, status: 'done', success: true,
      result: '展开后的结果', _expanded: false
    }])
    await wrapper.find('.tc-toggle').trigger('click')
    expect(wrapper.find('.tc-result').exists()).toBe(true)
    expect(wrapper.text()).toContain('展开后的结果')
  })

  it('展开后按钮变为"收起"', async () => {
    const wrapper = mountBlock([{
      name: 'search_skill', args: {}, status: 'done', success: true,
      result: '结果', _expanded: false
    }])
    await wrapper.find('.tc-toggle').trigger('click')
    expect(wrapper.find('.tc-toggle').text()).toBe('收起')
  })

  it('再次点击收起结果', async () => {
    const wrapper = mountBlock([{
      name: 'search_skill', args: {}, status: 'done', success: true,
      result: '结果', _expanded: false
    }])
    await wrapper.find('.tc-toggle').trigger('click')   // 展开
    await wrapper.find('.tc-toggle').trigger('click')   // 收起
    expect(wrapper.find('.tc-result').exists()).toBe(false)
  })

  it('无结果时不显示详情按钮', () => {
    const wrapper = mountBlock([{
      name: 'get_session_status', args: {}, status: 'running', _expanded: false
    }])
    expect(wrapper.find('.tc-toggle').exists()).toBe(false)
  })
})

describe('ToolCallBlock - 参数截断', () => {
  it('args 值超过 60 字符时截断显示省略号', () => {
    const longValue = 'A'.repeat(80)
    const wrapper = mountBlock([{
      name: 'search_skill',
      args: { query: longValue },
      status: 'done', success: true, _expanded: false
    }])
    const argsText = wrapper.find('.tc-args-text').text()
    expect(argsText).toContain('…')
    expect(argsText.length).toBeLessThan(longValue.length)
  })

  it('args 值不超过 60 字符时不截断', () => {
    const shortValue = '短文本'
    const wrapper = mountBlock([{
      name: 'search_skill',
      args: { query: shortValue },
      status: 'done', success: true, _expanded: false
    }])
    const argsText = wrapper.find('.tc-args-text').text()
    expect(argsText).toContain(shortValue)
    expect(argsText).not.toContain('…')
  })
})

describe('ToolCallBlock - 多工具调用', () => {
  it('多个工具调用都渲染', () => {
    const wrapper = mountBlock([
      { name: 'get_session_status', args: {}, status: 'done', success: true, _expanded: false },
      { name: 'search_skill', args: {}, status: 'running', _expanded: false },
    ])
    const items = wrapper.findAll('.tc-item')
    expect(items).toHaveLength(2)
  })
})
