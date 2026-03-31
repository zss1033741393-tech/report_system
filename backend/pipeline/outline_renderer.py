import re
from typing import AsyncGenerator

class OutlineRenderer:
    def get_outline_title(self, subtree):
        l, n = subtree.get("level",0), subtree.get("name","")
        if l==1: return f"{n} 分析报告大纲"
        elif l==2: return f"从 {n} 拓展分析"
        elif l==3: return f"{n} 评估大纲"
        return n

    async def render_stream(self, subtree, anchor) -> AsyncGenerator[str, None]:
        yield f"# {self.get_outline_title(subtree)}\n\n"
        children = subtree.get("children", [])
        if not children:
            return
        async for c in self._children(children, 1, ""): yield c

    async def _children(self, children, depth, pn):
        for i, child in enumerate(children, 1):
            num = f"{pn}{i}" if pn else str(i)
            async for c in self._node(child, depth, num): yield c

    async def _node(self, node, depth, num):
        level = node.get("level", 0)
        if level == 5:
            paragraph = node.get("paragraph", {})
            content = paragraph.get("content", "")
            if content:
                params = paragraph.get("params", {})
                text = self._replace_params(content, params)
                yield f"- **{node.get('name','')}**：{text}\n"
            else:
                yield f"- **{node.get('name','')}**\n"
            return
        prefix = "#" * min(depth+1, 6)
        yield f"{prefix} {num}. {node.get('name','')}\n\n"
        children = node.get("children", [])
        if children:
            async for c in self._children(children, depth+1, f"{num}."): yield c

    @staticmethod
    def _replace_params(content: str, params: dict) -> str:
        """将 content 中的 {key} 占位符替换为 params 中的值，未匹配的保持原样。"""
        def replacer(m):
            key = m.group(1)
            val = params.get(key)
            if val is None:
                return m.group(0)
            if isinstance(val, dict):
                return str(val.get("value", m.group(0)))
            return str(val)
        return re.sub(r'\{(\w+)\}', replacer, content)
