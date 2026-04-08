<template>
  <div class="skill-candidates">
    <div class="skill-candidates__header">
      <span class="skill-candidates__title">为您找到以下已沉淀的看网能力，请选择：</span>
    </div>
    <div class="skill-candidates__list">
      <div
        v-for="c in candidates"
        :key="c.skill_id"
        class="skill-card"
        @click="onSelect(c)"
      >
        <div class="skill-card__label">{{ c.label }}</div>
        <div class="skill-card__body">
          <div class="skill-card__name">{{ c.display_name }}</div>
          <div v-if="c.scene_intro" class="skill-card__intro">{{ c.scene_intro }}</div>
          <div v-if="c.description" class="skill-card__desc">
            <span class="skill-card__desc-label">差异点：</span>{{ c.description }}
          </div>
          <div v-if="c.keywords && c.keywords.length" class="skill-card__keywords">
            <span
              v-for="kw in c.keywords.slice(0, 5)"
              :key="kw"
              class="skill-card__kw"
            >{{ kw }}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="skill-candidates__fallback" @click="onFallback">
      <span>以上均不符合，直接搜索知识库</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  candidates: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['select', 'fallback'])

function onSelect(candidate) {
  emit('select', candidate)
}

function onFallback() {
  emit('fallback')
}
</script>

<style scoped>
.skill-candidates {
  margin: 8px 0;
  border: 1px solid var(--c-border, #e5e7eb);
  border-radius: 8px;
  overflow: hidden;
  background: var(--c-bg, #fff);
}

.skill-candidates__header {
  padding: 10px 14px 8px;
  border-bottom: 1px solid var(--c-border, #e5e7eb);
  background: var(--c-bg-subtle, #f9fafb);
}

.skill-candidates__title {
  font-size: 13px;
  color: var(--c-text-secondary, #6b7280);
  font-weight: 500;
}

.skill-candidates__list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.skill-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--c-border, #e5e7eb);
  transition: background 0.15s;
}

.skill-card:last-child {
  border-bottom: none;
}

.skill-card:hover {
  background: var(--c-primary-bg, #eff6ff);
}

.skill-card__label {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--c-primary, #3b82f6);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}

.skill-card__body {
  flex: 1;
  min-width: 0;
}

.skill-card__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text, #111827);
  margin-bottom: 2px;
}

.skill-card__intro {
  font-size: 12px;
  color: var(--c-text-secondary, #6b7280);
  margin-bottom: 4px;
  line-height: 1.4;
}

.skill-card__desc {
  font-size: 12px;
  color: var(--c-text, #374151);
  background: var(--c-primary-bg, #eff6ff);
  border-radius: 4px;
  padding: 3px 8px;
  margin-bottom: 4px;
  line-height: 1.4;
}

.skill-card__desc-label {
  color: var(--c-primary, #3b82f6);
  font-weight: 600;
}

.skill-card__keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.skill-card__kw {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--c-tag-bg, #e5e7eb);
  color: var(--c-text-secondary, #6b7280);
}

.skill-candidates__fallback {
  padding: 8px 14px;
  font-size: 12px;
  color: var(--c-text-secondary, #9ca3af);
  cursor: pointer;
  text-align: center;
  background: var(--c-bg-subtle, #f9fafb);
  border-top: 1px solid var(--c-border, #e5e7eb);
  transition: color 0.15s;
}

.skill-candidates__fallback:hover {
  color: var(--c-primary, #3b82f6);
}
</style>
