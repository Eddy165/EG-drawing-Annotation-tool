"""
Centralized state (single source of truth) for the Engineering Drawing Annotation Tool.
No derived state stored separately.
"""
import uuid
from typing import Any


def generate_id() -> str:
    return str(uuid.uuid4())


# Single global state object
state: dict[str, Any] = {
    "image_loaded": False,
    "image_data": None,  # QPixmap reference
    "scene_width": 0,
    "scene_height": 0,
    "image_width": 0,
    "image_height": 0,
    "scale": 1.0,
    "balloons": [],
    "next_balloon_number": 1,
    "undo_stack": [],
    "views": [],
    "selected_view_id": None,
    "next_view_id": 1,
    "mode": "dimension",  # dimension | note | bom
    "dimension_type": "linear",
    "flow_direction": "clockwise",
    "drawing_meta": {
        "name": "",
        "scale": "1:1",
    },
}


def add_view(name: str, view_type: str) -> dict:
    """Add a view and return it."""
    view = {
        "id": state["next_view_id"],
        "name": name,
        "type": view_type,
        "balloonCount": 0,
    }
    state["next_view_id"] += 1
    state["views"].append(view)
    state["selected_view_id"] = view["id"]
    return view


def remove_view(view_id: int) -> None:
    """Remove view by id. Balloons keep their viewId (orphaned)."""
    state["views"] = [v for v in state["views"] if v["id"] != view_id]
    if state["selected_view_id"] == view_id:
        state["selected_view_id"] = state["views"][0]["id"] if state["views"] else None


def get_balloon_count_for_view(view_id: int) -> int:
    return sum(1 for b in state["balloons"] if b.get("viewId") == view_id)


def renumber_all_balloons() -> None:
    """Renumber balloons 1..n with no gaps. Call after delete."""
    state["next_balloon_number"] = 1
    for b in state["balloons"]:
        b["number"] = state["next_balloon_number"]
        state["next_balloon_number"] += 1
    state["next_balloon_number"] = len(state["balloons"]) + 1
