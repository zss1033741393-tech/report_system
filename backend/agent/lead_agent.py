"""Lead Agent —— Plan → Execute → Reflect 循环。

v4.1: Planner 拥有完整上下文信息（has_outline/has_report/has_cached_context），
所有路由决策由 LLM 完成，代码层面只做"执行"不做"决策"。
"""
import json, logging
from typing import AsyncGenerator
from agent.context import AgentContext, SkillContext, SkillResult, Plan, PlanStep, ReflectAction
from agent.middleware.base import MiddlewareChain
from agent.skill_registry import SkillRegistry
from agent.skill_loader import SkillLoader
from llm.agent_llm import AgentLLM
from llm.config import PLANNER_CONFIG, REFLECTOR_CONFIG
from llm.service import LLMService
from services.chat_history import ChatHistoryService
from services.session_service import SessionService
from utils.trace_logger import TraceLogger

logger = logging.getLogger(__name__)

# ─── Planner Prompt ───
# 完整的状态信息 + 规则都在 Prompt 里，代码不做业务路由决策
PLANNER_BASE = """\
你是任务规划器。根据用户消息、历史对话和当前状态，判断用户意图并输出执行计划。

## 当前状态（每次请求动态注入）
状态信息在用户消息前的"## 状态"段落中提供，包含：
- 有大纲: 当前会话是否已有大纲
- 有报告: 当前会话是否已有报告
- 有缓存context: 是否有未沉淀的 skill-factory 预览缓存（用于 persist_only）
- 缓存context_key: 缓存的 key（persist_only 模式需要）
- 待确认: 是否有 L5 层级待确认
- 大纲摘要: 当前大纲内容概要

## 意图分类与路由规则

### 1. 创建/沉淀看网能力（skill-factory）
- **用户输入长文本看网逻辑（>100字）且不确定是否沉淀** → skill-factory, mode=preview_only, expert_input=用户文本
- **用户输入长文本且明确要沉淀** → skill-factory, mode=full, expert_input=用户文本
- **用户说"保存"/"沉淀" + 消息中有 context_key=xxx** → skill-factory, mode=persist_only, saved_context=xxx
- **用户说"保存"/"沉淀" + 当前有大纲但没有 context_key** → skill-factory, mode=persist_current
  （persist_current 模式会从当前会话大纲直接沉淀，适用于用户裁剪后再保存的场景）

### 2. 查询/生成看网报告（运行态）
- **常规短文本提问** → outline-generate（内部自动匹配已沉淀 Skill）
- **用户明确要生成报告** → outline-generate + data-execute + report-generate

### 3. 大纲裁剪（需要已有大纲）
- **用户说"删除XX"/"不看XX"/"去掉XX"** → outline-clip
- **重要：如果当前已有报告，裁剪后必须追加 data-execute + report-generate 重新生成报告**
  例："删除低阶交叉" 且 有报告=True → outline-clip + data-execute + report-generate

### 4. 参数注入（需要已有大纲）
- **用户修改参数/阈值** → param-inject
- 同理，如果有报告，注入后也要追加 data-execute + report-generate

### 5. 多步组合
- "从容量角度分析fgOTN，不看低阶交叉，只看金融行业"
  → outline-generate + outline-clip + param-inject + data-execute + report-generate

{skills_section}

## 内部技能
- outline-confirm: L5确认层级选择。参数: selected_level(2/3/4)。仅当"待确认"为true时可用。

## 规则
- 技能名用连字符格式
- 多步骤按序执行，顺序：outline-generate → outline-clip → param-inject → data-execute → report-generate
- skill-factory 是独立入口，不与其他运行态步骤组合
- **裁剪/参数注入后如果"有报告"=True，必须追加 data-execute + report-generate**
- **保存/沉淀时优先检查：有 context_key 用 persist_only，有大纲无 context_key 用 persist_current**
- 无法理解时 steps 留空，reply_before 友好回复

## 输出要求
用 ```json ``` 代码块包裹输出，不要加其他解释文字。
```json
{{"intent":"描述","steps":[{{"skill":"名","params":{{}}}}],"reply_before":"提示(可选)"}}
```
"""

REFLECTOR_P = """你是质量评估器。用 ```json ``` 代码块包裹输出，不要加解释文字。
格式:
```json
{"action":"pass|retry|replan|abort|ask_user","reason":"理由","retry_params":{},"new_steps":[],"user_question":""}
```"""


class LeadAgent:
    def __init__(self, llm_service, middleware_chain, skill_registry, skill_loader, chat_history, session_service):
        self._llm = llm_service; self._mw = middleware_chain; self._reg = skill_registry
        self._loader = skill_loader; self._ch = chat_history; self._ss = session_service
        prompt = PLANNER_BASE.format(skills_section=self._reg.get_skills_prompt_section())
        self._planner_prompt = prompt

    def _make_trace_callback(self, session_id: str, trace_id: str):
        ch = self._ch
        async def callback(llm_type, step_name, request_messages, response_content,
                           reasoning_content, model, temperature, elapsed_ms, success, error):
            await ch.save_llm_trace(
                session_id=session_id, trace_id=trace_id,
                llm_type=llm_type, step_name=step_name,
                request_messages=request_messages, response_content=response_content,
                reasoning_content=reasoning_content, model=model, temperature=temperature,
                elapsed_ms=elapsed_ms, success=success, error=error,
            )
        return callback

    async def handle_message(self, session_id, user_message) -> AsyncGenerator[str, None]:
        await self._ch.ensure_session(session_id)
        await self._ch.add_message(session_id, "user", user_message)
        trace = TraceLogger(session_id=session_id)
        trace.log("request.start", data={"user_message": user_message})
        collected_thinking, collected_outline_md = [], ""

        trace_cb = self._make_trace_callback(session_id, trace.trace_id)
        planner = AgentLLM(self._llm, self._planner_prompt, PLANNER_CONFIG,
                           trace_callback=trace_cb, llm_type="planner", step_name="intent_analysis")
        reflector = AgentLLM(self._llm, REFLECTOR_P, REFLECTOR_CONFIG,
                             trace_callback=trace_cb, llm_type="reflector", step_name="quality_check")

        def _yt(step, status, detail, data=None):
            evt = self._ts(step, status, detail, data)
            entry = {"step":step,"status":status,"detail":detail,"data":data}
            if status == "done":
                for idx in range(len(collected_thinking)-1,-1,-1):
                    if collected_thinking[idx]["step"]==step and collected_thinking[idx]["status"]=="running":
                        collected_thinking[idx] = entry; return evt
            collected_thinking.append(entry); return evt

        msgs = await self._ch.get_messages(session_id, limit=2)
        if len(msgs) <= 1:
            await self._ch.update_session_title(session_id, user_message[:20]+("..." if len(user_message)>20 else ""))

        ctx = AgentContext(session_id=session_id, user_message=user_message, trace_id=trace.trace_id)
        ctx = await self._mw.run_before(ctx)

        # 检查 Redis 是否有缓存的 skill-factory context
        cached_ctx_key = ""
        try:
            cached = await self._ss.redis.get(f"skill_factory_ctx:{session_id}")
            if cached:
                cached_ctx_key = session_id
        except Exception:
            pass

        yield _yt("intent_analysis","running","正在理解您的意图...")
        plan = await self._plan(ctx, planner, cached_ctx_key)
        sd = "、".join(self._sl(s.skill) for s in plan.steps) if plan.steps else "无"
        yield _yt("intent_analysis","done",f"意图：{plan.intent}",data={"steps":sd})
        logger.info(f"[{session_id}] Plan: {plan.intent}, {len(plan.steps)} steps")

        if plan.reply_before: yield self._ev("chat_reply", content=plan.reply_before)
        if not plan.steps:
            if not plan.reply_before: yield self._ev("chat_reply", content="请描述您的分析需求。")
            await self._ch.add_message(session_id, "assistant", plan.reply_before or plan.intent)
            yield self._ev("done"); return

        # ─── 执行循环（纯执行，不做路由决策）───
        results, steps, i, mr = {}, list(plan.steps), 0, 1
        while i < len(steps):
            step = steps[i]; sn = step.skill
            executor = self._loader.get_executor(sn)
            if not executor:
                if sn in ("outline-confirm","outline_confirm"):
                    async for ev in self._confirm(ctx, step.params, trace, trace_cb): yield ev
                    yield self._ev("done"); return
                meta = self._reg.get(sn)
                yield self._ev("chat_reply", content=f"「{meta.display_name}」开发中" if meta and not meta.enabled else f"不支持「{sn}」")
                i += 1; continue

            logger.info(f"[{session_id}] Execute: {sn}")
            trace.start_timer(f"skill.{sn}")
            result = None
            async for item in executor.execute(SkillContext(
                session_id=session_id, user_message=user_message, params=step.params,
                chat_history=ctx.chat_history, current_outline=ctx.current_outline,
                outline_summary=ctx.outline_summary, has_pending_confirm=ctx.has_pending_confirm,
                pending_confirm_options=ctx.pending_confirm_options, step_results=results,
                trace_callback=trace_cb)):
                if isinstance(item, SkillResult):
                    result = item
                    if result.data.get("outline_md"): collected_outline_md = result.data["outline_md"]
                    elif result.data.get("updated_outline"): collected_outline_md = self._tree_md(result.data["updated_outline"])
                elif isinstance(item, str):
                    yield item
                    try:
                        p = json.loads(item)
                        if p.get("type")=="thinking_step":
                            e = {"step":p["step"],"status":p["status"],"detail":p["detail"],"data":p.get("data")}
                            if e["status"]=="done":
                                for idx in range(len(collected_thinking)-1,-1,-1):
                                    if collected_thinking[idx]["step"]==e["step"] and collected_thinking[idx]["status"]=="running":
                                        collected_thinking[idx]=e; break
                                else: collected_thinking.append(e)
                            else: collected_thinking.append(e)
                    except: pass
            if not result: result = SkillResult(False, "Skill未返回结果")
            trace.log_timed(f"skill.{sn}.done", f"skill.{sn}", data={"success":result.success})

            yield _yt("quality_check","running","检查结果质量...")
            action = await self._reflect(sn, result, plan.intent, i, len(steps), reflector)
            icons = {"pass":"✅","retry":"🔄","replan":"📋","abort":"❌","ask_user":"❓"}
            yield _yt("quality_check","done",f"{icons.get(action.action,'ℹ️')} {action.reason}")

            if action.action == "pass":
                results[i] = result; await self._persist(session_id, sn, result)
                # 更新上下文（纯数据传递，不做路由决策）
                self._update_ctx_after_skill(ctx, sn, result)
                i += 1
            elif action.action == "retry" and mr > 0:
                mr -= 1; step.params.update(action.retry_params)
            elif action.action == "ask_user":
                q = action.user_question or result.user_prompt or "请提供更多信息。"
                yield self._ev("chat_reply", content=q)
                await self._ch.add_message(session_id, "assistant", q)
                yield self._ev("done"); return
            elif action.action == "abort":
                m = action.reason or result.summary
                yield self._ev("chat_reply", content=m)
                await self._ch.add_message(session_id, "assistant", m)
                yield self._ev("done"); return
            else:
                results[i] = result; await self._persist(session_id, sn, result)
                self._update_ctx_after_skill(ctx, sn, result)
                i += 1

        # ─── 最终回复 ───
        reply = self._final(plan, results)
        meta = {"intent": plan.intent}
        if collected_thinking: meta["thinking"] = collected_thinking
        if collected_outline_md: meta["outline_md"] = collected_outline_md
        for r in results.values():
            if r and r.data.get("report_html"):
                meta["report_html"] = r.data["report_html"]
                meta["report_title"] = r.data.get("title", "报告")
                break
        if collected_thinking: yield self._ev("thinking_complete", thinking=collected_thinking)
        yield self._ev("chat_reply", content=reply)
        await self._ch.add_message(session_id, "assistant", reply, msg_type="text", metadata=meta)
        yield self._ev("done")

    # ─── Plan（LLM 决策，完整状态注入）───

    async def _plan(self, ctx, planner, cached_ctx_key=""):
        planner.reset()
        # 构建完整状态信息（LLM 做所有决策所需的全部信息）
        st = (
            f"有大纲:{ctx.has_outline}\n"
            f"有报告:{ctx.has_report}\n"
            f"有缓存context:{bool(cached_ctx_key)}\n"
            f"缓存context_key:{cached_ctx_key or '无'}\n"
            f"待确认:{ctx.has_pending_confirm}\n"
            f"大纲摘要:{ctx.outline_summary or '无'}\n"
        )
        if ctx.has_pending_confirm and ctx.pending_confirm_options:
            st += "选项:" + ",".join(f'{o.get("label","")}:{o.get("name","")}' for o in ctx.pending_confirm_options) + "\n"
        hist = "\n".join(f'{m["role"]}:{m["content"]}' for m in ctx.chat_history[-10:]) if ctx.chat_history else "无"
        try:
            r = await planner.chat_json(f"## 状态\n{st}\n## 历史\n{hist}\n\n## 消息\n{ctx.user_message}")
            return Plan(intent=r.get("intent",""), steps=[PlanStep(s["skill"],s.get("params",{})) for s in r.get("steps",[])],
                        reply_before=r.get("reply_before",""), raw=r)
        except Exception as e:
            logger.warning(f"Planner失败:{e}"); return self._fb(ctx)

    def _fb(self, ctx):
        """Planner LLM 调用失败时的最简 fallback（仅异常兜底，不做业务判断）。"""
        msg = ctx.user_message.strip()
        if ctx.has_pending_confirm:
            return Plan("确认",[PlanStep("outline-confirm",{"selected_level":3})])
        if len(msg) > 100:
            return Plan("分析看网逻辑",[PlanStep("skill-factory",{"mode":"preview_only","expert_input":msg})])
        return Plan("生成大纲",[PlanStep("outline-generate",{"query":msg})])

    # ─── 辅助方法 ───

    def _update_ctx_after_skill(self, ctx, sn, result):
        """Skill 执行成功后更新上下文（纯数据传递）。"""
        if not result.success:
            return
        if sn == "outline-generate" and result.data.get("subtree"):
            ctx.current_outline = result.data["subtree"]
            ctx.has_outline = True
            ctx.outline_summary = result.data.get("outline_md", "")[:200]
        elif sn == "outline-clip" and result.data.get("updated_outline"):
            ctx.current_outline = result.data["updated_outline"]
        elif sn == "skill-factory" and result.data.get("outline_json"):
            ctx.current_outline = result.data["outline_json"]
            ctx.has_outline = True
        elif sn == "report-generate" and result.data.get("report_html"):
            ctx.has_report = True

    async def _reflect(self, sn, result, intent, idx, total, reflector):
        reflector.reset()
        p = f"技能:{sn}\nsuccess:{result.success}\nsummary:{result.summary}\nneed_input:{result.need_user_input}\n意图:{intent}\n{idx+1}/{total}"
        try:
            r = await reflector.chat_json(p)
            return ReflectAction(r.get("action","pass"),r.get("reason",""),r.get("retry_params",{}),
                                 [PlanStep(s["skill"],s.get("params",{})) for s in r.get("new_steps",[])],r.get("user_question",""))
        except:
            return ReflectAction("pass","OK") if result.success else ReflectAction(
                "ask_user" if result.need_user_input else "abort", result.summary, user_question=result.user_prompt)

    async def _confirm(self, ctx, params, trace=None, trace_cb=None):
        pending = ctx.pending_confirm_options
        if not pending: yield self._ev("chat_reply", content="确认已超时。"); return
        node_id = None; sl = params.get("selected_level")
        if sl:
            for o in pending:
                if o.get("level") == sl: node_id = o["id"]; break
        if not node_id: yield self._ev("chat_reply", content="未识别选择，请选A/B/C。"); return
        await self._ss.delete_pending_confirm(ctx.session_id)
        yield self._ev("chat_reply", content="正在生成大纲...")
        executor = self._loader.get_executor("outline-generate")
        if executor and hasattr(executor, "execute_from_node"):
            result = None
            async for item in executor.execute_from_node(SkillContext(session_id=ctx.session_id, user_message="", trace_callback=trace_cb), node_id):
                if isinstance(item, SkillResult): result = item
                elif isinstance(item, str): yield item
            if result and result.success:
                await self._persist(ctx.session_id, "outline-generate", result)
                yield self._ev("chat_reply", content="大纲已生成，请查看右侧。")
                await self._ch.add_message(ctx.session_id, "assistant", "已生成大纲", msg_type="outline")

    async def _persist(self, sid, sn, result):
        n = sn.replace("-","_")
        if n == "outline_generate" and result.success:
            d = result.data
            if "subtree" in d and "anchor" in d:
                await self._ch.save_outline_state(sid, d["subtree"], d["anchor"])
        elif n in ("outline_modify", "outline_clip") and result.success:
            if "updated_outline" in result.data:
                await self._ch.save_outline_state(sid, result.data["updated_outline"])
        elif n == "skill_factory" and result.success:
            d = result.data
            if d.get("outline_json"):
                await self._ch.save_outline_state(sid, d["outline_json"],
                    {"name": d.get("skill_name", ""), "level": 2})

    def _final(self, plan, results):
        sums = [r.summary for r in results.values() if r and r.summary]
        if not sums: return plan.intent or "完成。"
        reply = sums[0] if len(sums)==1 else "已完成：\n"+"\n".join(f"• {s}" for s in sums)
        if any(s.skill in ("outline-generate","outline-modify","outline-clip","skill-factory") for s in plan.steps):
            reply += "\n\n请查看右侧面板。"
        return reply

    @staticmethod
    def _ev(t, **kw): return json.dumps({"type":t,**kw}, ensure_ascii=False)
    @staticmethod
    def _ts(step, status, detail, data=None):
        p = {"type":"thinking_step","step":step,"status":status,"detail":detail}
        if data: p["data"] = data
        return json.dumps(p, ensure_ascii=False)
    @staticmethod
    def _sl(n): return {"outline-generate":"大纲生成","outline-clip":"大纲裁剪","param-inject":"参数注入",
                        "data-execute":"数据执行","report-generate":"报告生成","skill-factory":"能力工厂",
                        "outline-confirm":"层级确认"}.get(n,n)
    @staticmethod
    def _tree_md(tree, d=0):
        if not tree or not tree.get("name"): return ""
        md=""; p="#"*min(d+1,6)
        if tree.get("level",0)!=5: md+=f"{p} {tree['name']}\n\n"
        if tree.get("intro_text"): md+=f"{tree['intro_text']}\n\n"
        for c in tree.get("children",[]): md+=LeadAgent._tree_md(c,d+1)
        return md
