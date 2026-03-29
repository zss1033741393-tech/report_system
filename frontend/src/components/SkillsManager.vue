<template>
  <div class="skills-manager">
    <div class="skills-header">
      <span class="skills-title">技能管理</span>
      <button class="refresh-btn" @click="load" :disabled="loading">刷新</button>
    </div>
    <div v-if="loading" class="skills-loading">加载中...</div>
    <div v-else-if="!skills.length" class="skills-empty">暂无技能</div>
    <div v-else class="skills-list">
      <div
        v-for="skill in skills"
        :key="skill.name"
        class="skill-item"
        :class="{ disabled: !skill.enabled }"
      >
        <div class="skill-info">
          <div class="skill-name">{{ skill.display_name || skill.name }}</div>
          <div class="skill-desc">{{ skill.description }}</div>
          <div class="skill-meta">
            <span class="skill-source" :class="'src-' + skill.source">{{ skill.source }}</span>
          </div>
        </div>
        <label class="toggle-switch" :title="skill.enabled ? '点击禁用' : '点击启用'">
          <input
            type="checkbox"
            :checked="skill.enabled"
            @change="toggleSkillItem(skill)"
          />
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchSkills, toggleSkill } from '../utils/sse.js'

const skills = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    skills.value = await fetchSkills()
  } catch (e) {
    console.error('获取技能列表失败', e)
  } finally {
    loading.value = false
  }
}

async function toggleSkillItem(skill) {
  const newEnabled = !skill.enabled
  try {
    await toggleSkill(skill.name, newEnabled)
    skill.enabled = newEnabled
  } catch (e) {
    console.error('更新技能状态失败', e)
  }
}

onMounted(load)
</script>

<style scoped>
.skills-manager {
  padding: 12px;
  font-size: 13px;
  color: #e0e0e0;
}
.skills-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.skills-title {
  font-weight: 600;
  font-size: 14px;
}
.refresh-btn {
  background: transparent;
  border: 1px solid #555;
  color: #aaa;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
}
.refresh-btn:hover:not(:disabled) { border-color: #888; color: #ccc; }
.refresh-btn:disabled { opacity: 0.5; cursor: default; }
.skills-loading,
.skills-empty {
  color: #666;
  font-size: 12px;
  text-align: center;
  padding: 20px 0;
}
.skills-list { display: flex; flex-direction: column; gap: 8px; }
.skill-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  background: #1e1e1e;
  border-radius: 6px;
  border: 1px solid #333;
  transition: opacity 0.2s;
}
.skill-item.disabled { opacity: 0.5; }
.skill-info { flex: 1; min-width: 0; }
.skill-name {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 2px;
}
.skill-desc {
  font-size: 12px;
  color: #888;
  line-height: 1.4;
  margin-bottom: 4px;
}
.skill-meta { display: flex; gap: 6px; }
.skill-source {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}
.src-builtin { background: #1a3a5c; color: #6bb3f0; }
.src-custom  { background: #1a3a2a; color: #5dc97a; }

/* Toggle switch */
.toggle-switch {
  position: relative;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
  cursor: pointer;
}
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
  position: absolute;
  inset: 0;
  background: #444;
  border-radius: 10px;
  transition: background 0.2s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 3px;
  top: 3px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}
.toggle-switch input:checked + .toggle-slider { background: #4a90d9; }
.toggle-switch input:checked + .toggle-slider::before { transform: translateX(16px); }
</style>
