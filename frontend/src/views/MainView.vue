<template>
  <div class="app">
    <aside class="sidebar"><SessionList :sessions="sessions" :active-id="sid" @select="onSelectSession" @new-session="newSession" @delete="removeSession" /></aside>
    <section :class="['chat', {'chat--full': !showRight}]">
      <div class="chat__msgs" ref="msgsCtn">
        <!-- 欢迎页 -->
        <div v-if="!messages.length && !thinkSteps.length" class="welcome">
          <div class="welcome__hero">
            <div class="welcome__icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none"><rect width="48" height="48" rx="12" fill="var(--c-primary-bg)"/><path d="M14 20h20M14 28h12M24 14l8 6-8 6" stroke="var(--c-primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <h1 class="welcome__title">智能看网报告系统</h1>
            <p class="welcome__desc">将业务专家的网络评估经验，转化为可复用、可执行的看网报告</p>
          </div>
          <div class="welcome__cards">
            <div class="wcard" v-for="(g, gi) in exampleGroups" :key="gi">
              <div class="wcard__header">
                <span class="wcard__icon">{{ g.icon }}</span>
                <span class="wcard__label">{{ g.label }}</span>
              </div>
              <div class="wcard__item" v-for="e in g.items" :key="e" @click="send(e)">
                <span class="wcard__text">{{ e }}</span>
                <span class="wcard__arrow">→</span>
              </div>
            </div>
          </div>
          <p class="welcome__hint">输入分析需求开始对话，或点击上方示例快速体验</p>
        </div>
        <!-- 消息列表 -->
        <ChatMessage v-for="m in messages" :key="m.id||m._tid" :msg="m" @confirm="handleConfirm" />
        <div v-if="thinkSteps.length || streamReply || designSteps.length || toolCalls.length" class="cur">
          <SkillFactoryProgress v-if="designSteps.length" :design-steps="designSteps" />
          <ThinkingBlock v-if="thinkSteps.length" :steps="thinkSteps" />
          <ToolCallBlock v-if="toolCalls.length" :tool-calls="toolCalls" />
          <ChatMessage v-if="streamReply" :msg="{role:'assistant',content:streamReply,msg_type:'text',created_at:new Date().toISOString()}" />
        </div>
      </div>
      <QueryInput :loading="loading" @send="send" />
    </section>
    <div v-if="!showRight && hasArtifacts" class="edge-tab" @click="openRightPanel('artifacts')">
      <span class="edge-tab__icon">{{ hasReport ? '📊' : '📋' }}</span>
      <span class="edge-tab__text">{{ hasReport ? '报告' : '大纲' }}</span>
    </div>
    <transition name="sp">
      <section v-if="showRight" class="right-side">
        <!-- 右侧面板 Tab 导航 -->
        <div class="rp-nav">
          <button :class="['rp-nav__tab', { 'rp-nav__tab--active': rightTab === 'artifacts' }]" @click="rightTab='artifacts'" title="大纲/报告">
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="2" y="2" width="11" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M4.5 5.5h6M4.5 8h4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
          </button>
          <button :class="['rp-nav__tab', { 'rp-nav__tab--active': rightTab === 'memory' }]" @click="rightTab='memory'" title="跨对话记忆">
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="7.5" r="5.5" stroke="currentColor" stroke-width="1.3"/><path d="M7.5 4.5v3l2 2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button :class="['rp-nav__tab', { 'rp-nav__tab--active': rightTab === 'skills' }]" @click="rightTab='skills'" title="技能库">
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="2" y="2" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="8.5" y="2" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="2" y="8.5" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="8.5" y="8.5" width="4.5" height="4.5" rx="1" stroke="currentColor" stroke-width="1.3"/></svg>
          </button>
          <div class="rp-nav__spacer"></div>
          <button class="rp-nav__close" @click="showRight=false" title="关闭">✕</button>
        </div>
        <!-- 面板内容 -->
        <div class="rp-body">
          <RightPanel v-if="rightTab === 'artifacts'"
            :outline-content="outContent" :outline-loading="outLoading" :anchor="anchor"
            :report-html="reportHtml" :report-title="reportTitle" :report-loading="reportLoading"
            :has-report="hasReport" :has-outline="hasOutline"
            @close="showRight=false" />
          <MemoryPanel v-else-if="rightTab === 'memory'" :session-id="sid" />
          <SkillsManager v-else-if="rightTab === 'skills'" />
        </div>
      </section>
    </transition>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import SessionList from '../components/SessionList.vue'
import ChatMessage from '../components/ChatMessage.vue'
import QueryInput from '../components/QueryInput.vue'
import RightPanel from '../components/RightPanel.vue'
import ThinkingBlock from '../components/ThinkingBlock.vue'
import SkillFactoryProgress from '../components/SkillFactoryProgress.vue'
import ToolCallBlock from '../components/ToolCallBlock.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import SkillsManager from '../components/SkillsManager.vue'
import { useConversation } from '../composables/useConversation.js'

const msgsCtn = ref(null)
const showRight = ref(false)
const rightTab = ref('artifacts')   // 'artifacts' | 'memory' | 'skills'

const {
  sessions, sid, messages, loading, streamReply,
  thinkSteps, designSteps, toolCalls,
  outContent, outLoading, anchor,
  reportHtml, reportTitle, reportLoading,
  hasOutline, hasReport, hasArtifacts,
  loadSessions, switchSession, newSession, removeSession,
  send, handleConfirm,
} = useConversation(msgsCtn)

const exampleGroups = [
  { icon: '🔍', label: '快速分析', items: ['帮我分析政企OTN升级的机会点', 'fgOTN部署，从时延方面分析'] },
  { icon: '🎯', label: '精准筛选', items: ['从传送网络容量角度分析fgOTN，不看低阶交叉，只看金融行业'] },
  { icon: '📝', label: '能力沉淀', items: ['输入看网逻辑文本，系统自动解析并生成可复用的分析能力'] },
]

function openRightPanel(tab) {
  rightTab.value = tab
  showRight.value = true
}

// 切换会话时同步更新右侧面板显示
async function onSelectSession(id) {
  await switchSession(id)
  if (hasArtifacts.value) { rightTab.value = 'artifacts'; showRight.value = true }
  else showRight.value = false
}

onMounted(async () => { await loadSessions() })
</script>

<style scoped>
.app { display: flex; height: 100vh; overflow: hidden; background: var(--c-bg); font-family: var(--font-sans) }
.sidebar { width: 260px; flex-shrink: 0 }
.chat { flex: 4; min-width: 320px; display: flex; flex-direction: column; border-left: 1px solid var(--c-border); border-right: 1px solid var(--c-border); background: var(--c-bg-elevated); transition: flex .3s var(--ease) }
.chat--full { flex: 10 }
.chat__msgs { flex: 1; overflow-y: auto; padding: var(--sp-md) var(--sp-lg) }

/* ─── 欢迎页 ─── */
.welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: var(--sp-xl) }
.welcome__hero { text-align: center; margin-bottom: var(--sp-xl) }
.welcome__icon { margin-bottom: var(--sp-md) }
.welcome__title { font-size: 28px; font-weight: 700; color: var(--c-text); margin: 0 0 var(--sp-sm); letter-spacing: -0.5px }
.welcome__desc { font-size: var(--text-base); color: var(--c-text-secondary); margin: 0; max-width: 400px; line-height: 1.6 }

.welcome__cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--sp-md); width: 100%; max-width: 720px }
.wcard { background: var(--c-bg-elevated); border: 1px solid var(--c-border); border-radius: var(--r-md); overflow: hidden; transition: border-color var(--duration) var(--ease), box-shadow var(--duration) var(--ease) }
.wcard:hover { border-color: var(--c-primary-border); box-shadow: var(--shadow-md) }
.wcard__header { display: flex; align-items: center; gap: var(--sp-sm); padding: 12px var(--sp-md); border-bottom: 1px solid var(--c-border-light); background: var(--c-bg-muted) }
.wcard__icon { font-size: 16px }
.wcard__label { font-size: var(--text-sm); font-weight: 600; color: var(--c-text) }
.wcard__item { display: flex; align-items: center; padding: 10px var(--sp-md); cursor: pointer; transition: background var(--duration) var(--ease) }
.wcard__item:hover { background: var(--c-primary-bg) }
.wcard__item + .wcard__item { border-top: 1px solid var(--c-border-light) }
.wcard__text { flex: 1; font-size: var(--text-sm); color: var(--c-text-secondary); line-height: 1.5 }
.wcard__arrow { color: var(--c-text-tertiary); font-size: var(--text-sm); opacity: 0; transition: opacity var(--duration) var(--ease), transform var(--duration) var(--ease) }
.wcard__item:hover .wcard__arrow { opacity: 1; transform: translateX(2px); color: var(--c-primary) }

.welcome__hint { margin-top: var(--sp-lg); font-size: var(--text-xs); color: var(--c-text-tertiary) }

/* ─── 右侧贴边标签 ─── */
.edge-tab { flex-shrink: 0; width: 32px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; background: var(--c-primary); color: var(--c-text-inverse); cursor: pointer; writing-mode: vertical-rl; padding: 12px 4px; transition: background var(--duration) var(--ease) }
.edge-tab:hover { background: var(--c-primary-light) }
.edge-tab__icon { font-size: 16px; writing-mode: horizontal-tb }
.edge-tab__text { font-size: var(--text-xs); letter-spacing: 2px; font-weight: 500 }

/* ─── 右侧面板 ─── */
.right-side { flex: 6; min-width: 400px; display: flex; flex-direction: column }
.sp-enter-active, .sp-leave-active { transition: all .3s var(--ease) }
.sp-enter-from, .sp-leave-to { flex: 0!important; min-width: 0!important; opacity: 0; overflow: hidden }

.rp-nav { display: flex; align-items: center; gap: 2px; padding: 6px 8px; border-bottom: 1px solid var(--c-border); background: var(--c-bg-elevated); flex-shrink: 0 }
.rp-nav__tab { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border: 1px solid transparent; border-radius: var(--r-sm); background: transparent; color: var(--c-text-tertiary); cursor: pointer; transition: all var(--duration) var(--ease) }
.rp-nav__tab:hover { background: var(--c-bg-muted); color: var(--c-text-secondary) }
.rp-nav__tab--active { background: var(--c-primary-bg); border-color: var(--c-primary-border); color: var(--c-primary) }
.rp-nav__spacer { flex: 1 }
.rp-nav__close { width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; border: none; background: transparent; color: var(--c-text-tertiary); cursor: pointer; font-size: 14px; border-radius: var(--r-sm); transition: all var(--duration) var(--ease) }
.rp-nav__close:hover { background: var(--c-bg-muted); color: var(--c-text) }

.rp-body { flex: 1; overflow: hidden; display: flex; flex-direction: column }
</style>
