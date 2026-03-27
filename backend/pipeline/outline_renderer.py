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
            if subtree.get("intro_text"): yield f"{subtree['intro_text']}\n\n"
            return
        async for c in self._children(children, 1, ""): yield c

    async def _children(self, children, depth, pn):
        for i, child in enumerate(children, 1):
            num = f"{pn}{i}" if pn else str(i)
            async for c in self._node(child, depth, num): yield c

    async def _node(self, node, depth, num):
        if node.get("level",0) == 5: return
        prefix = "#" * min(depth+1, 6)
        yield f"{prefix} {num}. {node.get('name','')}\n\n"
        if node.get("level",0) == 3 and node.get("intro_text"):
            yield f"{node['intro_text']}\n\n"
        children = node.get("children", [])
        if children:
            async for c in self._children(children, depth+1, f"{num}."): yield c
