<template>
  <div class="op">
    <div v-if="showHeader" class="op__h">
      <h3>报告大纲</h3>
      <div class="op__acts">
        <el-button v-if="content&&!loading" size="small" text @click="copy"><el-icon><CopyDocument /></el-icon>复制</el-button>
        <el-button size="small" text @click="$emit('close')"><el-icon><Close /></el-icon></el-button>
      </div>
    </div>
    <div v-if="!content&&!loading" class="op__empty"><div class="ei">📋</div><p>大纲将在这里展示</p></div>
    <div v-else class="op__content">
      <div class="md" v-html="html"></div>
      <div v-if="loading" class="lb"><div class="lb__in"></div></div>
    </div>
    <div v-if="anchor&&!loading" class="op__foot">
      <el-tag type="success" size="small">{{ anchor.name }} (L{{ anchor.level }})</el-tag>
      <el-button size="small" type="primary" plain disabled>生成报告（即将上线）</el-button>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'; import { CopyDocument, Close } from '@element-plus/icons-vue'; import { ElMessage } from 'element-plus'
defineEmits(['close'])
const props = defineProps({ content:{type:String,default:''},loading:Boolean,anchor:{type:Object,default:null},showHeader:{type:Boolean,default:true} })
const html = computed(() => props.content?props.content.split('\n').map(l=>{const m=l.match(/^(#{1,6})\s+(.*)/);if(m) return `<h${m[1].length}>${m[2]}</h${m[1].length}>`;if(l.trim()) return `<p>${l}</p>`;return ''}).join(''):'')
async function copy() { try{await navigator.clipboard.writeText(props.content);ElMessage.success('已复制')}catch{ElMessage.error('复制失败')} }
</script>
<style scoped>
.op{height:100%;display:flex;flex-direction:column;background:#fff}
.op__h{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--c-border)}
.op__h h3{margin:0;font-size:16px;color:var(--c-text)}
.op__empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--c-text-tertiary)}
.ei{font-size:48px;margin-bottom:12px;opacity:.5}
.op__content{flex:1;overflow-y:auto;padding:20px}
.md{line-height:1.8;color:var(--c-text)}
.md :deep(h1){font-size:22px;margin:0 0 16px;border-bottom:2px solid var(--c-primary);padding-bottom:8px}
.md :deep(h2){font-size:18px;margin:20px 0 8px}
.md :deep(h3){font-size:16px;margin:14px 0 6px;color:var(--c-text-secondary)}
.md :deep(p){margin:4px 0;font-size:14px;color:var(--c-text-secondary)}
.lb{height:3px;background:var(--c-border);border-radius:2px;overflow:hidden;margin-top:12px}
.lb__in{height:100%;width:40%;background:linear-gradient(90deg,var(--c-primary),var(--c-primary-light));animation:slide 1.5s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
.op__foot{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;border-top:1px solid var(--c-border)}
</style>
