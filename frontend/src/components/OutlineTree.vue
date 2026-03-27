<template>
  <div class="ot">
    <div class="ot__header">
      <h3>报告大纲</h3>
      <div class="ot__actions">
        <el-button v-if="treeData" size="small" text @click="$emit('copy')"><el-icon><CopyDocument /></el-icon></el-button>
        <el-button size="small" text @click="$emit('close')"><el-icon><Close /></el-icon></el-button>
      </div>
    </div>
    <div v-if="!treeData" class="ot__empty"><p>大纲将在这里展示</p></div>
    <div v-else class="ot__body">
      <OutlineTreeNode v-for="child in treeData.children" :key="child.id||child.name" :node="child" :depth="0"
        :editable="editable" @delete="onDelete" @rename="onRename" />
    </div>
  </div>
</template>

<script setup>
import { Close, CopyDocument } from '@element-plus/icons-vue'
import OutlineTreeNode from './OutlineTreeNode.vue'

const props = defineProps({
  treeData: { type: Object, default: null },
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'copy', 'update', 'delete', 'rename'])

function onDelete(nodeName) { emit('delete', nodeName) }
function onRename(oldName, newName) { emit('rename', oldName, newName) }
</script>

<style scoped>
.ot { height: 100%; display: flex; flex-direction: column; background: #fff }
.ot__header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--c-border) }
.ot__header h3 { margin: 0; font-size: 15px }
.ot__empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--c-text-tertiary) }
.ot__body { flex: 1; overflow-y: auto; padding: 12px 16px }
</style>
