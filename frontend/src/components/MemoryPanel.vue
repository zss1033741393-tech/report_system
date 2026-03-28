<template>
  <div class="mp">
    <!-- 顶部标题栏 -->
    <div class="mp__head">
      <div class="mp__title">
        <span class="mp__brain">🧠</span>
        <span>系统对你的了解</span>
      </div>
      <div class="mp__acts">
        <button class="mp__btn mp__btn--ghost" @click="refresh" :disabled="loading" title="刷新">
          <span :class="['mp__spin', { 'mp__spin--active': loading }]">↻</span>
        </button>
        <button class="mp__btn mp__btn--danger" @click="confirmClear" title="清除记忆">清除</button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && !memory" class="mp__empty">
      <div class="mp__spinner"></div>
      <span>加载中...</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="isEmpty" class="mp__empty">
      <div class="mp__empty-icon">🔍</div>
      <p>尚无记忆</p>
      <p class="mp__empty-hint">随着对话积累，系统会自动记住你的偏好和使用习惯</p>
    </div>

    <!-- 记忆内容 -->
    <div v-else class="mp__body">

      <!-- 工作上下文 -->
      <section v-if="workContext" class="mp__section">
        <div class="mp__section-title">工作上下文</div>
        <p class="mp__text">{{ workContext }}</p>
      </section>

      <!-- 当前关注 -->
      <section v-if="topOfMind" class="mp__section">
        <div class="mp__section-title">当前关注</div>
        <p class="mp__text">{{ topOfMind }}</p>
      </section>

      <!-- 近期规律 -->
      <section v-if="recentMonths" class="mp__section">
        <div class="mp__section-title">近期规律</div>
        <p class="mp__text">{{ recentMonths }}</p>
      </section>

      <!-- 已记住的偏好 -->
      <section v-if="facts.length" class="mp__section">
        <div class="mp__section-title">已记住的偏好</div>
        <div class="mp__facts">
          <div
            v-for="fact in facts"
            :key="fact.id"
            class="mp__fact"
            :title="`置信度: ${(fact.confidence * 100).toFixed(0)}%`"
          >
            <span class="mp__fact-dot" :class="`mp__fact-dot--${fact.category}`"></span>
            <span class="mp__fact-content">{{ fact.content }}</span>
            <span class="mp__fact-conf">{{ confBar(fact.confidence) }}</span>
          </div>
        </div>
      </section>

    </div>

    <!-- 底部时间戳 -->
    <div v-if="memory?.lastUpdated" class="mp__foot">
      上次更新：{{ fmtTime(memory.lastUpdated) }}
    </div>

    <!-- 确认清除对话框 -->
    <div v-if="showConfirm" class="mp__overlay" @click.self="showConfirm = false">
      <div class="mp__confirm">
        <p class="mp__confirm-title">确认清除所有记忆？</p>
        <p class="mp__confirm-hint">此操作不可恢复，系统将忘记所有已记录的偏好和习惯。</p>
        <div class="mp__confirm-acts">
          <button class="mp__btn mp__btn--ghost" @click="showConfirm = false">取消</button>
          <button class="mp__btn mp__btn--danger" @click="doClear">确认清除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const API = ''

// ─── 状态 ──────────────────────────────────────────────────────────────────
const memory = ref(null)
const loading = ref(false)
const showConfirm = ref(false)

// ─── 计算属性 ──────────────────────────────────────────────────────────────
const workContext = computed(() => memory.value?.user?.workContext?.summary || '')
const topOfMind  = computed(() => memory.value?.user?.topOfMind?.summary  || '')
const recentMonths = computed(() => memory.value?.history?.recentMonths?.summary || '')
const facts = computed(() =>
  (memory.value?.facts || []).filter(f => f.confidence >= 0.7)
)
const isEmpty = computed(() =>
  !workContext.value && !topOfMind.value && !recentMonths.value && !facts.value.length
)

// ─── 生命周期 ──────────────────────────────────────────────────────────────
onMounted(() => refresh())

// ─── 方法 ──────────────────────────────────────────────────────────────────
async function refresh() {
  loading.value = true
  try {
    const r = await fetch(`${API}/api/v1/memory`)
    if (r.ok) memory.value = await r.json()
  } catch (e) {
    console.warn('Memory load failed:', e)
  } finally {
    loading.value = false
  }
}

function confirmClear() {
  showConfirm.value = true
}

async function doClear() {
  showConfirm.value = false
  loading.value = true
  try {
    await fetch(`${API}/api/v1/memory`, { method: 'DELETE' })
    memory.value = null
  } catch (e) {
    console.warn('Memory clear failed:', e)
  } finally {
    loading.value = false
  }
}

function confBar(conf) {
  const filled = Math.round(conf * 5)
  return '●'.repeat(filled) + '○'.repeat(5 - filled)
}

function fmtTime(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit'
    })
  } catch { return iso }
}
</script>

<style scoped>
.mp {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--c-bg-elevated);
  font-size: 13px;
  position: relative;
  overflow: hidden;
}

/* 头部 */
.mp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--c-border);
  flex-shrink: 0;
}
.mp__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--c-text);
  font-size: 14px;
}
.mp__brain { font-size: 16px; }
.mp__acts { display: flex; gap: 6px; align-items: center; }

/* 按钮 */
.mp__btn {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--c-border);
  cursor: pointer;
  font-size: 12px;
  background: transparent;
  color: var(--c-text-secondary);
  transition: all 0.15s;
}
.mp__btn:hover { background: var(--c-bg-muted); }
.mp__btn--danger {
  border-color: #fca5a5;
  color: #dc2626;
}
.mp__btn--danger:hover { background: #fff5f5; }
.mp__btn--ghost { border-color: transparent; }

/* 刷新旋转 */
.mp__spin { display: inline-block; font-size: 16px; transition: transform 0.3s; }
.mp__spin--active { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 空状态 */
.mp__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--c-text-tertiary);
  padding: 24px;
  text-align: center;
}
.mp__empty-icon { font-size: 32px; opacity: 0.5; }
.mp__empty-hint { font-size: 12px; line-height: 1.6; max-width: 200px; }
.mp__spinner {
  width: 24px; height: 24px;
  border: 2px solid var(--c-border);
  border-top-color: var(--c-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* 主体 */
.mp__body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 分区 */
.mp__section { display: flex; flex-direction: column; gap: 6px; }
.mp__section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--c-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.mp__text {
  color: var(--c-text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Facts 列表 */
.mp__facts { display: flex; flex-direction: column; gap: 6px; }
.mp__fact {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 10px;
  background: var(--c-bg-muted);
  border-radius: 8px;
  border: 1px solid var(--c-border);
}
.mp__fact-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 4px;
}
.mp__fact-dot--preference { background: #3b82f6; }
.mp__fact-dot--behavior   { background: #22c55e; }
.mp__fact-dot--constraint { background: #f59e0b; }
.mp__fact-dot--context    { background: #8b5cf6; }
.mp__fact-content {
  flex: 1;
  color: var(--c-text);
  line-height: 1.5;
}
.mp__fact-conf {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--c-text-tertiary);
  letter-spacing: -1px;
  margin-top: 2px;
}

/* 底部 */
.mp__foot {
  padding: 8px 16px;
  border-top: 1px solid var(--c-border);
  color: var(--c-text-tertiary);
  font-size: 11px;
  flex-shrink: 0;
}

/* 确认弹层 */
.mp__overlay {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.mp__confirm {
  background: var(--c-bg-elevated);
  border: 1px solid var(--c-border);
  border-radius: 12px;
  padding: 20px;
  width: 240px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mp__confirm-title { font-weight: 600; color: var(--c-text); margin: 0; font-size: 14px; }
.mp__confirm-hint  { color: var(--c-text-secondary); margin: 0; line-height: 1.5; }
.mp__confirm-acts  { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
</style>
