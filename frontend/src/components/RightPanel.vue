<template>
  <div class="rp-container">
    <!-- 顶部栏：始终渲染，关闭按钮永远可见 -->
    <div class="rp-tabs">
      <div v-if="hasOutline || outlineContent || outlineLoading"
           :class="['rp-tab', { active: activeTab === 'outline' }]"
           @click="activeTab = 'outline'">
        <span>📋</span> 大纲
      </div>
      <div v-if="hasReport || reportHtml || reportLoading"
           :class="['rp-tab', { active: activeTab === 'report' }]"
           @click="activeTab = 'report'">
        <span>📊</span> 报告
      </div>
      <div class="rp-tab-spacer"></div>
      <div class="rp-tab-close" @click="$emit('close')" title="关闭">✕</div>
    </div>

    <!-- 大纲内容 -->
    <OutlineDisplay v-if="activeTab === 'outline'"
      :content="outlineContent" :loading="outlineLoading" :anchor="anchor"
      :show-header="false" />

    <!-- 报告内容 -->
    <ReportPreview v-else-if="activeTab === 'report'"
      :html-content="reportHtml" :title="reportTitle" :loading="reportLoading"
      :show-header="false" />

    <!-- 空状态（两个 tab 都不存在时） -->
    <div v-else class="rp-empty">
      <div class="rp-empty__icon">📋</div>
      <p>大纲或报告将在这里展示</p>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import OutlineDisplay from './OutlineDisplay.vue'
import ReportPreview from './ReportPreview.vue'

const props = defineProps({
  outlineContent: { type: String, default: '' },
  outlineLoading: { type: Boolean, default: false },
  anchor: { type: Object, default: null },
  reportHtml: { type: String, default: '' },
  reportTitle: { type: String, default: '' },
  reportLoading: { type: Boolean, default: false },
  hasReport: { type: Boolean, default: false },
  hasOutline: { type: Boolean, default: false },
})
defineEmits(['close'])

// 初始化：优先显示已有内容的那个 tab
const activeTab = ref(props.hasReport ? 'report' : 'outline')

// 有新报告时自动切到报告 tab
watch(() => props.hasReport, (v) => { if (v) activeTab.value = 'report' })
// 有新大纲且无报告时切到大纲 tab
watch(() => props.hasOutline, (v) => { if (v && !props.hasReport) activeTab.value = 'outline' })
// 报告开始加载时切到报告 tab
watch(() => props.reportLoading, (v) => { if (v) activeTab.value = 'report' })
// 大纲开始加载时切到大纲 tab（除非已有报告）
watch(() => props.outlineLoading, (v) => { if (v && !props.hasReport) activeTab.value = 'outline' })
</script>

<style scoped>
.rp-container { height: 100%; display: flex; flex-direction: column }
.rp-tabs { display: flex; align-items: center; border-bottom: 1px solid var(--c-border); background: #fff; padding: 0 8px; flex-shrink: 0; min-height: 42px }
.rp-tab { padding: 10px 16px; cursor: pointer; font-size: 13px; color: var(--c-text-tertiary); border-bottom: 2px solid transparent; transition: all .2s; display: flex; align-items: center; gap: 4px; user-select: none }
.rp-tab:hover { color: var(--c-primary) }
.rp-tab.active { color: var(--c-primary); border-bottom-color: var(--c-primary); font-weight: 600 }
.rp-tab-spacer { flex: 1 }
.rp-tab-close { padding: 8px 10px; cursor: pointer; color: var(--c-text-tertiary); font-size: 16px; border-radius: 4px; transition: background .15s, color .15s; line-height: 1 }
.rp-tab-close:hover { background: var(--c-border); color: var(--c-text) }
.rp-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--c-text-tertiary); background: #fff }
.rp-empty__icon { font-size: 48px; margin-bottom: 12px; opacity: .5 }
</style>
