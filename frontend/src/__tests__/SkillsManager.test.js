/**
 * SkillsManager.vue 组件测试
 *
 * 验证：
 *   - mount 时自动调用 GET /api/v1/skills
 *   - 切换 tab 正确过滤 builtin/custom
 *   - 点击技能项切换 active 状态（toggle）
 *   - 点击刷新按钮重新加载技能列表
 *   - disabled 技能显示"禁用"徽标
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SkillsManager from '../components/SkillsManager.vue'

const MOCK_SKILLS = [
  { name: 'outline-generate', display_name: '大纲生成', description: '生成报告大纲', enabled: true, source: 'builtin', executor: null },
  { name: 'report-generate', display_name: '报告生成', description: '生成最终报告', enabled: true, source: 'builtin', executor: null },
  { name: 'data-execute', display_name: '数据执行', description: '执行数据查询', enabled: true, source: 'builtin', executor: null },
  { name: 'disabled-skill', display_name: '禁用技能', description: '已禁用', enabled: false, source: 'builtin', executor: null },
  { name: 'custom-skill-1', display_name: '自定义技能1', description: '用户沉淀的技能', enabled: true, source: 'custom', executor: { cls: 'CustomExecutor', module: 'skills.custom' } },
  { name: 'custom-skill-2', display_name: '自定义技能2', description: '另一个自定义技能', enabled: true, source: 'custom', executor: null },
]

function mockFetch(skills = MOCK_SKILLS) {
  global.fetch = vi.fn().mockResolvedValue({
    json: () => Promise.resolve({ skills }),
    ok: true,
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('SkillsManager - 初始加载', () => {
  it('mount 时自动调用 GET /api/v1/skills', async () => {
    mockFetch()
    mount(SkillsManager)
    await flushPromises()
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/skills')
  })

  it('加载后显示内置技能（默认 tab=builtin）', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()
    expect(wrapper.text()).toContain('大纲生成')
  })
})

describe('SkillsManager - Tab 过滤', () => {
  it('默认显示内置技能', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()
    const items = wrapper.findAll('.sm__item')
    // 内置有 4 个（含禁用）
    expect(items.length).toBe(4)
  })

  it('切换到自定义 tab 显示 custom 技能', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    // 点击自定义 tab
    const tabs = wrapper.findAll('.sm__tab')
    await tabs[1].trigger('click')
    await flushPromises()

    const items = wrapper.findAll('.sm__item')
    expect(items.length).toBe(2)
    expect(wrapper.text()).toContain('自定义技能1')
  })

  it('切换回内置 tab 正确显示内置技能', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const tabs = wrapper.findAll('.sm__tab')
    await tabs[1].trigger('click')  // 切换到 custom
    await tabs[0].trigger('click')  // 切换回 builtin
    await flushPromises()

    expect(wrapper.findAll('.sm__item').length).toBe(4)
  })

  it('tab 上显示正确数量', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()
    const tabTexts = wrapper.findAll('.sm__tab').map(t => t.text())
    // 内置 4 个, 自定义 2 个
    expect(tabTexts[0]).toContain('4')
    expect(tabTexts[1]).toContain('2')
  })
})

describe('SkillsManager - 选中交互', () => {
  it('点击技能项，该技能变为 active', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const items = wrapper.findAll('.sm__item')
    await items[0].trigger('click')
    expect(items[0].classes()).toContain('sm__item--active')
  })

  it('再次点击同一技能取消 active（toggle）', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const items = wrapper.findAll('.sm__item')
    await items[0].trigger('click')  // 选中
    await items[0].trigger('click')  // 取消
    expect(items[0].classes()).not.toContain('sm__item--active')
  })

  it('点击另一个技能时切换 active', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const items = wrapper.findAll('.sm__item')
    await items[0].trigger('click')
    await items[1].trigger('click')

    expect(items[0].classes()).not.toContain('sm__item--active')
    expect(items[1].classes()).toContain('sm__item--active')
  })
})

describe('SkillsManager - 刷新', () => {
  it('点击刷新按钮重新调用 GET /api/v1/skills', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const beforeCount = global.fetch.mock.calls.length
    await wrapper.find('.sm__refresh').trigger('click')
    await flushPromises()

    expect(global.fetch.mock.calls.length).toBeGreaterThan(beforeCount)
    expect(global.fetch).toHaveBeenLastCalledWith('/api/v1/skills')
  })
})

describe('SkillsManager - 禁用技能', () => {
  it('disabled 技能显示"禁用"徽标', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    // 找到禁用徽标
    const offBadges = wrapper.findAll('.sm__badge--off')
    expect(offBadges.length).toBeGreaterThan(0)
    expect(offBadges[0].text()).toBe('禁用')
  })

  it('disabled 技能有 sm__item--disabled class', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const disabledItems = wrapper.findAll('.sm__item--disabled')
    expect(disabledItems.length).toBe(1)
  })

  it('启用技能显示"启用"徽标', async () => {
    mockFetch()
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const onBadges = wrapper.findAll('.sm__badge--on')
    expect(onBadges.length).toBeGreaterThan(0)
    expect(onBadges[0].text()).toBe('启用')
  })
})

describe('SkillsManager - 空状态', () => {
  it('无自定义技能时显示空提示', async () => {
    const skills = MOCK_SKILLS.filter(s => s.source === 'builtin')
    mockFetch(skills)
    const wrapper = mount(SkillsManager)
    await flushPromises()

    const tabs = wrapper.findAll('.sm__tab')
    await tabs[1].trigger('click')
    await flushPromises()

    expect(wrapper.find('.sm__empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无自定义技能')
  })
})
