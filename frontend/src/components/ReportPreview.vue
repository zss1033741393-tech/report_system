<template>
  <div class="rp">
    <div v-if="showHeader" class="rp__header">
      <h3>{{ title || '报告预览' }}</h3>
      <div class="rp__actions">
        <el-button v-if="htmlContent && !loading" size="small" text @click="openNew"><el-icon><FullScreen /></el-icon>新窗口</el-button>
        <el-button size="small" text @click="$emit('close')"><el-icon><Close /></el-icon></el-button>
      </div>
    </div>
    <div v-if="!htmlContent && !loading" class="rp__empty">
      <div class="rp__icon">📊</div>
      <p>报告将在这里预览</p>
    </div>
    <div v-else class="rp__body">
      <iframe ref="iframeRef" class="rp__iframe" sandbox="allow-same-origin allow-scripts" :srcdoc="htmlContent"></iframe>
      <div v-if="loading" class="rp__loading"><div class="rp__bar"><div class="rp__bar-inner"></div></div></div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { FullScreen, Close } from '@element-plus/icons-vue'

const props = defineProps({
  htmlContent: { type: String, default: '' },
  title: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  showHeader: { type: Boolean, default: true },
})
defineEmits(['close'])

const iframeRef = ref(null)

function openNew() {
  const w = window.open('', '_blank')
  if (w) { w.document.write(props.htmlContent); w.document.close() }
}
</script>

<style scoped>
.rp { height: 100%; display: flex; flex-direction: column; background: #fff }
.rp__header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--c-border) }
.rp__header h3 { margin: 0; font-size: 15px; color: var(--c-text) }
.rp__empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--c-text-tertiary) }
.rp__icon { font-size: 48px; margin-bottom: 12px; opacity: .5 }
.rp__body { flex: 1; position: relative; overflow: hidden }
.rp__iframe { width: 100%; height: 100%; border: none }
.rp__loading { position: absolute; bottom: 0; left: 0; right: 0; height: 3px; background: var(--c-border) }
.rp__bar { height: 100%; overflow: hidden }
.rp__bar-inner { height: 100%; width: 40%; background: linear-gradient(90deg, var(--c-primary), var(--c-primary-light)); animation: slide 1.5s ease-in-out infinite }
@keyframes slide { 0%{transform:translateX(-100%)} 100%{transform:translateX(350%)} }
</style>
