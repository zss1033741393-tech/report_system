from typing import Optional, Generator
from models.outline_node import OutlineNode

class OutlineEditor:
    def delete_node(self, root, target_name):
        root.children = [self.delete_node(c, target_name) for c in root.children if c.name != target_name]
        return root
    def add_node(self, root, parent_name, new_node):
        if root.name == parent_name: root.children.append(new_node); return root
        for c in root.children: self.add_node(c, parent_name, new_node)
        return root
    def move_node(self, root, target_name, ref_name, position="before"):
        for node in self._all(root):
            names = [c.name for c in node.children]
            if target_name in names and ref_name in names:
                ch = node.children; tgt = next(c for c in ch if c.name == target_name); ch.remove(tgt)
                ri = next(i for i,c in enumerate(ch) if c.name == ref_name)
                ch.insert(ri if position == "before" else ri + 1, tgt); break
        return root
    def find_node(self, root, name) -> Optional[OutlineNode]:
        if root.name == name: return root
        for c in root.children:
            f = self.find_node(c, name)
            if f: return f
        return None
    def _all(self, node) -> Generator:
        yield node
        for c in node.children: yield from self._all(c)
