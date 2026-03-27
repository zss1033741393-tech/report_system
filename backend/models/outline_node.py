from dataclasses import dataclass, field
from typing import List
import uuid

@dataclass
class OutlineNode:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    neo4j_id: str = ""; name: str = ""; level: int = 0; intro_text: str = ""
    children: List["OutlineNode"] = field(default_factory=list)

    def to_dict(self):
        return {"id":self.id,"neo4j_id":self.neo4j_id,"name":self.name,"level":self.level,
                "intro_text":self.intro_text,"children":[c.to_dict() for c in self.children]}

    @classmethod
    def from_dict(cls, d):
        n = cls(id=d["id"],neo4j_id=d["neo4j_id"],name=d["name"],level=d["level"],intro_text=d.get("intro_text",""))
        n.children = [cls.from_dict(c) for c in d.get("children",[])]
        return n

    @classmethod
    def from_subtree(cls, s):
        n = cls(neo4j_id=s.get("id",""),name=s.get("name",""),level=s.get("level",0),intro_text=s.get("intro_text",""))
        for c in s.get("children",[]): n.children.append(cls.from_subtree(c))
        return n
