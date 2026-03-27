<template>
  <div class="rp-container">
    <!-- Tab 切换栏（有大纲和报告时显示） -->
    <div v-if="hasOutline && hasReport" class="rp-tabs">
      <div :class="['rp-tab', { active: activeTab === 'outline' }]" @click="activeTab='outline'">
        <span>📋</span> 大纲
      </div>
      <div :class="['rp-tab', { active: activeTab === 'report' }]" @click="activeTab='report'">
        <span>📊</span> 报告
      </div>
      <div class="rp-tab-spacer"></div>
      <div class="rp-tab-close" @click="$emit('close')">✕</div>
    </div>

    <!-- 大纲模式 -->
    <OutlineDisplay v-if="activeTab==='outline' && (hasOutline || outlineContent)"
      :content="outlineContent" :loading="outlineLoading" :anchor="anchor"
      @close="$emit('close')" :show-header="!(hasOutline && hasReport)" />

    <!-- 报告模式 -->
    <ReportPreview v-else-if="activeTab==='report' && (hasReport || reportHtml)"
      :html-content="reportHtml" :title="reportTitle" :loading="reportLoading"
      @close="$emit('close')" :show-header="!(hasOutline && hasReport)" />

    <!-- 空状态 -->
    <div v-else class="rp-empty">
      <div class="rp-empty__icon">📋</div>
      <p>大纲或报告将在这里展示</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
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

// 默认显示最新内容：有报告显示报告，否则大纲
const activeTab = ref('outline')

watch(() => props.hasReport, (v) => {
  if (v) activeTab.value = 'report'
})
watch(() => props.hasOutline, (v) => {
  if (v && !props.hasReport) activeTab.value = 'outline'
})
</script>

<style scoped>
.rp-container { height: 100%; display: flex; flex-direction: column }
.rp-tabs { display: flex; align-items: center; border-bottom: 1px solid var(--c-border); background: #fff; padding: 0 8px; flex-shrink: 0 }
.rp-tab { padding: 10px 16px; cursor: pointer; font-size: 13px; color: var(--c-text-tertiary); border-bottom: 2px solid transparent; transition: all .2s; display: flex; align-items: center; gap: 4px }
.rp-tab:hover { color: var(--c-primary) }
.rp-tab.active { color: var(--c-primary); border-bottom-color: var(--c-primary); font-weight: 600 }
.rp-tab-spacer { flex: 1 }
.rp-tab-close { padding: 8px; cursor: pointer; color: var(--c-text-tertiary); font-size: 14px }
.rp-tab-close:hover { color: var(--c-text-tertiary) }
.rp-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--c-text-tertiary); background: #fff }
.rp-empty__icon { font-size: 48px; margin-bottom: 12px; opacity: .5 }
</style>
