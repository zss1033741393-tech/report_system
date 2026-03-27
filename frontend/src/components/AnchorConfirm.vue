<template>
  <el-dialog
    v-model="visible"
    title="选择大纲起始层级"
    width="560px"
    :close-on-click-modal="false"
  >
    <div class="confirm-content">
      <p class="indicator-info">
        我找到了「<strong>{{ data?.indicator_name }}</strong>」这个评估指标，它属于以下知识库路径：
      </p>

      <div class="full-path">
        <el-tag
          v-for="(segment, idx) in pathSegments"
          :key="idx"
          :type="idx === pathSegments.length - 1 ? 'warning' : 'info'"
          size="small"
          class="path-segment"
        >
          {{ segment }}
        </el-tag>
      </div>

      <p class="prompt">您希望从哪个层级开始生成大纲？</p>

      <div class="options">
        <el-radio-group v-model="selectedNodeId" class="option-group">
          <el-radio
            v-for="ancestor in data?.ancestors"
            :key="ancestor.id"
            :value="ancestor.id"
            class="option-item"
          >
            <span class="option-label">{{ ancestor.label }}</span>
            <span class="option-name">{{ ancestor.name }}</span>
            <span class="option-desc">
              {{ getOptionDesc(ancestor.level) }}
            </span>
          </el-radio>
        </el-radio-group>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button
        type="primary"
        :disabled="!selectedNodeId"
        @click="handleConfirm"
      >
        确认生成
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  data: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const selectedNodeId = ref('')

// 重置选中状态
watch(
  () => props.modelValue,
  (val) => {
    if (val) selectedNodeId.value = ''
  }
)

const pathSegments = computed(() => {
  if (!props.data?.full_path) return []
  return props.data.full_path.split(' > ')
})

function getOptionDesc(level) {
  const descMap = {
    2: '生成该子场景下所有内容',
    3: '生成该维度下所有评估项',
    4: '生成该评估项下所有指标',
  }
  return descMap[level] || ''
}

function handleConfirm() {
  if (!selectedNodeId.value) return
  emit('confirm', selectedNodeId.value)
  visible.value = false
}

function handleCancel() {
  emit('cancel')
  visible.value = false
}
</script>

<style scoped>
.confirm-content {
  padding: 0 8px;
}

.indicator-info {
  font-size: 14px;
  color: #303133;
  line-height: 1.6;
  margin-bottom: 12px;
}

.full-path {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 16px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.path-segment::after {
  content: ' >';
  margin-left: 4px;
  color: #c0c4cc;
}

.path-segment:last-child::after {
  content: '';
}

.prompt {
  font-size: 14px;
  color: #606266;
  margin-bottom: 12px;
}

.option-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.option-item {
  display: flex;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  transition: border-color 0.2s;
}

.option-item:hover {
  border-color: #409eff;
}

.option-label {
  display: inline-block;
  min-width: 80px;
  font-weight: 600;
  color: #303133;
}

.option-name {
  color: #409eff;
  margin: 0 8px;
}

.option-desc {
  font-size: 12px;
  color: #909399;
}
</style>
