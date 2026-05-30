"""Todo-related DTOs."""
from nexusx import DefineSubset, SubsetConfig
from src.models import Audit, Todo


class TodoItem(DefineSubset):
    """Todo DTO — children auto-loaded from Todo.children relationship."""
    __subset__ = SubsetConfig(kls=Todo, fields=["id", "text", "desc", "done", "parent_id", "pinned", "created", "done_at"])
    children: list["TodoItem"] = []


class TodoBrief(DefineSubset):
    """Brief todo for list responses."""
    __subset__ = SubsetConfig(kls=Todo, fields=["id", "text", "done", "parent_id", "pinned"])


class AuditItem(DefineSubset):
    """Audit log DTO."""
    __subset__ = SubsetConfig(kls=Audit, fields=["id", "timestamp", "action", "todo_id", "details"])
