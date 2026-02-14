"""
Deterministic JSON export for auditability.
"""
import json
import time
from pathlib import Path

from state import state


def build_export_data() -> dict:
    """Build full export dict from state. Deterministic, human-readable."""
    dim_breakdown = {
        "linear": sum(1 for b in state["balloons"] if b.get("type") == "dimension" and b.get("dimensionType") == "linear"),
        "angular": sum(1 for b in state["balloons"] if b.get("type") == "dimension" and b.get("dimensionType") == "angular"),
        "radius": sum(1 for b in state["balloons"] if b.get("type") == "dimension" and b.get("dimensionType") == "radius"),
        "circular": sum(1 for b in state["balloons"] if b.get("type") == "dimension" and b.get("dimensionType") == "circular"),
    }
    views_export = []
    for v in state["views"]:
        count = sum(1 for b in state["balloons"] if b.get("viewId") == v["id"])
        views_export.append({
            "id": v["id"],
            "name": v["name"],
            "type": v["type"],
            "balloonCount": count,
        })
    balloons_export = []
    for b in state["balloons"]:
        out = {
            "id": b["id"],
            "number": b["number"],
            "type": b["type"],
            "x": b["x"],
            "y": b["y"],
            "viewId": b.get("viewId"),
        }
        if b.get("type") == "dimension":
            out["dimensionType"] = b.get("dimensionType", "")
            out["value"] = b.get("value", "")
            out["flowDirection"] = b.get("flowDirection", "")
        elif b.get("type") == "note":
            out["text"] = b.get("text", "")
        elif b.get("type") == "bom":
            out["itemNumber"] = b.get("itemNumber", "")
            out["description"] = b.get("description", "")
            out["material"] = b.get("material", "")
            out["quantity"] = b.get("quantity", "")
            out["notes"] = b.get("notes", "")
        balloons_export.append(out)

    return {
        "metadata": {
            "exportDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "drawingName": state["drawing_meta"].get("name") or "Unnamed Drawing",
            "scale": state["drawing_meta"].get("scale") or "1:1",
            "canvasSize": {"width": state["scene_width"], "height": state["scene_height"]},
            "imageSize": {"width": state["image_width"], "height": state["image_height"]},
        },
        "views": views_export,
        "summary": {
            "totalBalloons": len(state["balloons"]),
            "dimensions": sum(1 for b in state["balloons"] if b.get("type") == "dimension"),
            "notes": sum(1 for b in state["balloons"] if b.get("type") == "note"),
            "bomItems": sum(1 for b in state["balloons"] if b.get("type") == "bom"),
            "dimensionBreakdown": dim_breakdown,
        },
        "detectionFlow": {
            "description": "Manual annotation system - Dimensions → Notes → BOM",
            "flowDirection": "User-controlled placement with global sequential numbering",
        },
        "balloons": balloons_export,
    }


def export_to_file(file_path: str | Path) -> None:
    """Write JSON to file. File name should be drawing-annotation-<timestamp>.json."""
    data = build_export_data()
    path = Path(file_path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
