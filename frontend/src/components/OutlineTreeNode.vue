<template>
  <div :class="['otn', `otn--l${node.level}`]" :style="{ paddingLeft: depth * 16 + 'px' }">
    <div class="otn__row" @click="expanded = !expanded">
      <span v-if="hasChildren" class="otn__arrow">{{ expanded ? '▼' : '▶' }}</span>
      <span v-else class="otn__dot">●</span>
      <span v-if="!editing" class="otn__name">{{ node.name }}</span>
      <input v-else v-model="editName" class="otn__input" @keyup.enter="finishRename" @blur="finishRename" ref="inputRef" />
      <span class="otn__level">L{{ node.level }}</span>
      <span v-if="node.source === 'llm_generated'" class="otn__badge">AI生成</span>
      <div v-if="editable" class="otn__ops">
        <span class="otn__op" @click.stop="startRename" title="重命名">✏️</span>
        <span class="otn__op" @click.stop="$emit('delete', node.name)" title="删除">🗑️</span>
      </div>
    </div>
    <div v-if="expanded && hasChildren">
      <OutlineTreeNode v-for="child in node.children" :key="child.id||child.name"
        :node="child" :depth="depth+1" :editable="editable"
        @delete="(n) => $emit('delete', n)" @rename="(o,n) => $emit('rename', o, n)" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['delete', 'rename'])

const expanded = ref(props.depth < 2)
const editing = ref(false)
const editName = ref('')
const inputRef = ref(null)
const hasChildren = computed(() => props.node.children?.length > 0)

function startRename() {
  editName.value = props.node.name
  editing.value = true
  nextTick(() => inputRef.value?.focus())
}
function finishRename() {
  if (editing.value && editName.value && editName.value !== props.node.name) {
    emit('rename', props.node.name, editName.value)
  }
  editing.value = false
}
</script>

<style scoped>
.otn__row { display: flex; align-items: center; gap: 6px; padding: 4px 0; cursor: pointer; border-radius: 4px; transition: background .2s }
.otn__row:hover { background: var(--c-bg-muted) }
.otn__arrow { font-size: 10px; color: var(--c-text-tertiary); width: 14px; text-align: center }
.otn__dot { font-size: 6px; color: var(--c-text-tertiary); width: 14px; text-align: center }
.otn__name { font-size: 13px; color: var(--c-text); flex: 1 }
.otn__input { font-size: 13px; border: 1px solid var(--c-primary); border-radius: 4px; padding: 2px 6px; flex: 1; outline: none }
.otn__level { font-size: 10px; color: var(--c-text-tertiary); padding: 1px 4px; background: var(--c-bg-subtle); border-radius: 3px }
.otn__badge { font-size: 10px; color: var(--c-warning); padding: 1px 4px; background: var(--c-warning-bg); border-radius: 3px }
.otn__ops { display: none; gap: 4px }
.otn__row:hover .otn__ops { display: flex }
.otn__op { cursor: pointer; font-size: 12px; opacity: .6; transition: opacity .2s }
.otn__op:hover { opacity: 1 }
.otn--l3 .otn__name { font-weight: 600 }
.otn--l5 .otn__name { color: var(--c-text-tertiary); font-size: 12px }
</style>
