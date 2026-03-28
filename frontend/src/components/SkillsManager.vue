<template>
  <div class="sm">
    <div class="sm__header">
      <div class="sm__title">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="5" height="5" rx="1" stroke="var(--c-primary)" stroke-width="1.5"/><rect x="9" y="2" width="5" height="5" rx="1" stroke="var(--c-primary)" stroke-width="1.5"/><rect x="2" y="9" width="5" height="5" rx="1" stroke="var(--c-primary)" stroke-width="1.5"/><rect x="9" y="9" width="5" height="5" rx="1" stroke="var(--c-primary)" stroke-width="1.5"/></svg>
        看网技能库
      </div>
      <button class="sm__refresh" @click="loadSkills" :disabled="loading" title="刷新">
        <svg :class="['sm__refresh-icon', { 'sm__refresh-icon--spin': loading }]" width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M12 7A5 5 0 1 1 7 2a5 5 0 0 1 3.5 1.5L12 2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 2v3h-3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </div>

    <div class="sm__tabs">
      <button :class="['sm__tab', { 'sm__tab--active': tab === 'builtin' }]" @click="tab='builtin'">
        内置 <span class="sm__count">{{ builtinSkills.length }}</span>
      </button>
      <button :class="['sm__tab', { 'sm__tab--active': tab === 'custom' }]" @click="tab='custom'">
        自定义 <span class="sm__count">{{ customSkills.length }}</span>
      </button>
    </div>

    <div v-if="loading" class="sm__loading">
      <span class="sm__spin"></span>
      加载中...
    </div>

    <div v-else-if="displaySkills.length === 0" class="sm__empty">
      <p>暂无{{ tab === 'builtin' ? '内置' : '自定义' }}技能</p>
    </div>

    <div v-else class="sm__list">
      <div
        v-for="skill in displaySkills"
        :key="skill.name"
        :class="['sm__item', { 'sm__item--active': selected === skill.name, 'sm__item--disabled': !skill.enabled }]"
        @click="selectSkill(skill.name)"
      >
        <div class="sm__item-main">
          <div class="sm__item-name">{{ skill.display_name || skill.name }}</div>
          <span :class="['sm__badge', skill.enabled ? 'sm__badge--on' : 'sm__badge--off']">
            {{ skill.enabled ? '启用' : '禁用' }}
          </span>
        </div>
        <div class="sm__item-desc">{{ skill.description }}</div>
        <div v-if="skill.executor" class="sm__item-meta">
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none"><rect x="1" y="1" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.2"/><path d="M3.5 5.5l1.5 1.5 2.5-3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          {{ skill.executor.cls }}
        </div>
      </div>
    </div>

    <div v-if="error" class="sm__error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const loading = ref(false)
const skills = ref([])
const error = ref('')
const tab = ref('builtin')
const selected = ref('')

const builtinSkills = computed(() => skills.value.filter(s => s.source === 'builtin'))
const customSkills = computed(() => skills.value.filter(s => s.source === 'custom'))
const displaySkills = computed(() => tab.value === 'builtin' ? builtinSkills.value : customSkills.value)

async function loadSkills() {
  loading.value = true; error.value = ''
  try {
    const res = await fetch('/api/v1/skills')
    const data = await res.json()
    skills.value = data?.skills || []
  } catch (e) {
    error.value = '加载技能失败'
    skills.value = []
  } finally {
    loading.value = false
  }
}

function selectSkill(name) {
  selected.value = selected.value === name ? '' : name
}

onMounted(loadSkills)
</script>

<style scoped>
.sm { display: flex; flex-direction: column; height: 100%; font-size: var(--text-sm) }

.sm__header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; border-bottom: 1px solid var(--c-border-light); flex-shrink: 0 }
.sm__title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--c-text); font-size: var(--text-base) }

.sm__refresh { width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--c-border); border-radius: var(--r-sm); background: transparent; color: var(--c-text-secondary); cursor: pointer; transition: all var(--duration) var(--ease) }
.sm__refresh:hover:not(:disabled) { border-color: var(--c-primary); color: var(--c-primary) }
.sm__refresh:disabled { opacity: 0.4; cursor: not-allowed }
.sm__refresh-icon { transition: transform var(--duration) var(--ease) }
.sm__refresh-icon--spin { animation: spin .7s linear infinite }
@keyframes spin { to { transform: rotate(360deg) } }

.sm__tabs { display: flex; gap: 4px; padding: 8px 12px; border-bottom: 1px solid var(--c-border-light); flex-shrink: 0 }
.sm__tab { flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px; padding: 5px 10px; border: 1px solid var(--c-border); border-radius: var(--r-sm); background: transparent; color: var(--c-text-secondary); cursor: pointer; font-size: var(--text-xs); font-weight: 500; transition: all var(--duration) var(--ease) }
.sm__tab:hover { background: var(--c-bg-muted) }
.sm__tab--active { background: var(--c-primary-bg); border-color: var(--c-primary-border); color: var(--c-primary) }
.sm__count { font-size: 10px; background: var(--c-border); border-radius: var(--r-full); padding: 0 5px; min-width: 16px; text-align: center; color: var(--c-text-tertiary) }
.sm__tab--active .sm__count { background: var(--c-primary-border); color: var(--c-primary) }

.sm__loading { flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--c-text-tertiary) }
.sm__spin { width: 14px; height: 14px; border: 2px solid var(--c-border); border-top-color: var(--c-primary); border-radius: 50%; animation: spin .7s linear infinite; flex-shrink: 0 }

.sm__empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--c-text-tertiary) }
.sm__empty p { margin: 0 }

.sm__list { flex: 1; overflow-y: auto; padding: 8px }
.sm__item { padding: 10px 12px; border: 1px solid var(--c-border-light); border-radius: var(--r-sm); margin-bottom: 6px; cursor: pointer; transition: all var(--duration) var(--ease) }
.sm__item:hover { border-color: var(--c-border); background: var(--c-bg-muted) }
.sm__item--active { border-color: var(--c-primary-border); background: var(--c-primary-bg) }
.sm__item--disabled { opacity: 0.5 }

.sm__item-main { display: flex; align-items: center; gap: 6px; margin-bottom: 4px }
.sm__item-name { flex: 1; font-weight: 500; color: var(--c-text) }
.sm__badge { font-size: 10px; padding: 1px 6px; border-radius: var(--r-full); border: 1px solid transparent }
.sm__badge--on { background: var(--c-success-bg, #f0fdf4); color: var(--c-success, #16a34a); border-color: #bbf7d0 }
.sm__badge--off { background: var(--c-bg-muted); color: var(--c-text-tertiary); border-color: var(--c-border) }

.sm__item-desc { color: var(--c-text-secondary); line-height: 1.5; margin-bottom: 4px; font-size: var(--text-xs) }
.sm__item-meta { display: flex; align-items: center; gap: 4px; color: var(--c-text-tertiary); font-size: 10px }

.sm__error { padding: 8px 16px; color: var(--c-danger, #ef4444); font-size: var(--text-xs); flex-shrink: 0 }
</style>
