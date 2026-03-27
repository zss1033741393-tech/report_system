<template>
  <div class="ci">
    <el-input v-model="msg" :placeholder="placeholder" :disabled="loading" :autosize="{minRows:1,maxRows:4}" type="textarea" resize="none" @keydown.enter.exact.prevent="send" />
    <el-button class="ci__btn" type="primary" :loading="loading" :disabled="!msg.trim()" circle @click="send">
      <el-icon v-if="!loading"><Promotion /></el-icon>
    </el-button>
  </div>
</template>
<script setup>
import { ref } from 'vue'; import { Promotion } from '@element-plus/icons-vue'
const props = defineProps({ loading: Boolean, placeholder: { type: String, default: '输入您的分析需求...' } })
const emit = defineEmits(['send']); const msg = ref('')
function send() { const t = msg.value.trim(); if (!t || props.loading) return; emit('send', t); msg.value = '' }
</script>
<style scoped>
.ci { display: flex; align-items: flex-end; gap: var(--sp-sm); padding: 12px var(--sp-md); background: var(--c-bg-elevated); border-top: 1px solid var(--c-border) }
.ci :deep(.el-textarea__inner) { border-radius: var(--r-md); padding: 10px 14px; font-size: var(--text-base); border-color: var(--c-border); box-shadow: var(--shadow-sm) }
.ci :deep(.el-textarea__inner:focus) { border-color: var(--c-primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.1) }
.ci__btn { flex-shrink: 0; width: 40px; height: 40px }
</style>
