<template>
  <div class="memory-panel">
    <div class="memory-header">
      <span class="memory-title">记忆</span>
      <button class="clear-btn" @click="handleClear" :disabled="clearing" title="清除记忆">
        {{ clearing ? '清除中...' : '清除' }}
      </button>
    </div>

    <div v-if="loading" class="memory-loading">加载中...</div>
    <div v-else-if="empty" class="memory-empty">暂无记忆内容</div>
    <div v-else class="memory-content">
      <div v-if="memory.user?.workContext?.summary" class="memory-section">
        <div class="section-label">工作上下文</div>
        <div class="section-text">{{ memory.user.workContext.summary }}</div>
      </div>
      <div v-if="memory.user?.topOfMind?.summary" class="memory-section">
        <div class="section-label">当前关注</div>
        <div class="section-text">{{ memory.user.topOfMind.summary }}</div>
      </div>
      <div v-if="memory.history?.recentMonths?.summary" class="memory-section">
        <div class="section-label">近期历史</div>
        <div class="section-text">{{ memory.history.recentMonths.summary }}</div>
      </div>
      <div v-if="memory.facts?.length" class="memory-section">
        <div class="section-label">已记住的偏好 ({{ memory.facts.length }})</div>
        <div
          v-for="fact in memory.facts"
          :key="fact.id"
          class="fact-item"
        >
          <span class="fact-category" :class="'cat-' + fact.category">{{ fact.category }}</span>
          <span class="fact-content">{{ fact.content }}</span>
          <span class="fact-confidence">{{ (fact.confidence * 100).toFixed(0) }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchMemory, clearMemory } from '../utils/sse.js'

const memory = ref({})
const loading = ref(false)
const clearing = ref(false)

const empty = computed(() => {
  const m = memory.value
  return !m.user?.workContext?.summary &&
    !m.user?.topOfMind?.summary &&
    !m.history?.recentMonths?.summary &&
    !(m.facts?.length)
})

async function load() {
  loading.value = true
  try {
    memory.value = await fetchMemory()
  } catch (e) {
    console.error('获取记忆失败', e)
  } finally {
    loading.value = false
  }
}

async function handleClear() {
  clearing.value = true
  try {
    await clearMemory()
    memory.value = {}
  } catch (e) {
    console.error('清除记忆失败', e)
  } finally {
    clearing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.memory-panel {
  padding: 12px;
  font-size: 13px;
  color: #e0e0e0;
}
.memory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.memory-title {
  font-weight: 600;
  font-size: 14px;
}
.clear-btn {
  background: transparent;
  border: 1px solid #555;
  color: #aaa;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
}
.clear-btn:hover:not(:disabled) {
  border-color: #e74c3c;
  color: #e74c3c;
}
.clear-btn:disabled { opacity: 0.5; cursor: default; }
.memory-loading,
.memory-empty {
  color: #666;
  font-size: 12px;
  text-align: center;
  padding: 20px 0;
}
.memory-section {
  margin-bottom: 12px;
}
.section-label {
  font-size: 11px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.section-text {
  line-height: 1.5;
  color: #ccc;
}
.fact-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 4px;
  padding: 4px 6px;
  background: #1e1e1e;
  border-radius: 4px;
}
.fact-category {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
  margin-top: 1px;
}
.cat-preference { background: #1a3a5c; color: #6bb3f0; }
.cat-behavior   { background: #1a3a2a; color: #5dc97a; }
.cat-context    { background: #3a2a1a; color: #d4924a; }
.fact-content {
  flex: 1;
  line-height: 1.4;
  color: #ccc;
  font-size: 12px;
}
.fact-confidence {
  font-size: 11px;
  color: #666;
  flex-shrink: 0;
}
</style>
