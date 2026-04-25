"""
Centralized state (single source of truth) for the Engineering Drawing Annotation Tool.
No derived state stored separately.
"""
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional
import numpy as np
from PyQt6.QtCore import QPointF

def generate_id() -> str:
    return str(uuid.uuid4())

class Phase(Enum):
    PHASE_0_INPUT = 0
    PHASE_1_ZONE_DETECT = 1
    PHASE_2_VIEW_DETECT = 2
    PHASE_3_VIEW_CONFIRM = 3   # NEW: user must confirm/edit views before proceeding
    PHASE_4_FLOW_SELECT = 4
    PHASE_5_DIM_DETECT = 5
    PHASE_6_NOTES_DETECT = 6
    PHASE_7_BOM_DETECT = 7
    PHASE_8_MANUAL_OVERRIDE = 8
    PHASE_9_EXPORT = 9

PHASES = list(Phase)

PHASE_0_INPUT = Phase.PHASE_0_INPUT
PHASE_1_ZONE_DETECT = Phase.PHASE_1_ZONE_DETECT
PHASE_2_VIEW_DETECT = Phase.PHASE_2_VIEW_DETECT
PHASE_3_FLOW_SELECT = Phase.PHASE_4_FLOW_SELECT
PHASE_4_DIM_DETECT = Phase.PHASE_5_DIM_DETECT
PHASE_5_NOTES_DETECT = Phase.PHASE_6_NOTES_DETECT
PHASE_6_BOM_DETECT = Phase.PHASE_7_BOM_DETECT
PHASE_7_MANUAL_OVERRIDE = Phase.PHASE_8_MANUAL_OVERRIDE
PHASE_8_EXPORT = Phase.PHASE_9_EXPORT

@dataclass
class DetectedView:
    view_id: int
    label: str                    # e.g. "FRONT VIEW", "SECTION A-A", "UNKNOWN_1"
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in original image coordinates
    confidence: float             # 0.0 to 1.0
    label_source: str             # "ocr" | "manual" | "inferred"
    is_confirmed: bool = False
    is_manually_edited: bool = False

@dataclass  
class Balloon:
    balloon_id: int
    view_id: int                  # which DetectedView this belongs to
    dim_type: str                 # "linear_h" | "linear_v" | "angular" | "radial" 
                                  # | "circular" | "tolerance" | "alphanumeric" 
                                  # | "notes" | "bom" | "manual"
    value: str                    # raw OCR string e.g. "25.5"
    tolerance: str                # e.g. "±0.2" or "" if none
    unit: str                     # "mm" | "deg" | "" 
    confidence: int               # 0-100
    position_scene: QPointF       # position on QGraphicsScene
    position_image: tuple[int, int] # position in original image pixels
    is_flagged: bool = False
    is_manual: bool = False
    sequence_number: int = 0      # final display number after CW/ACW sort

class State:
    def __init__(self):
        # NEW V2 FIELDS
        self.current_phase = Phase.PHASE_0_INPUT
        self.detected_views: list[DetectedView] = []
        self.views_confirmed: bool = False
        self.zones: dict = {}             # keys: "drawing", "notes", "bom" → each a (x,y,w,h) tuple
        self.flow_direction: str = "CW"  # "CW" | "ACW"
        self.balloons: list[Balloon] = []
        self.preprocessed_image: np.ndarray | None = None  # 300 DPI normalized grayscale
        self.binary_image: np.ndarray | None = None        # Sauvola threshold output
        self.cv_image: np.ndarray | None = None            # Needed for gates check

        # EXISTING KEYS that are not being replaced
        self.phase_results: dict[str, Any] = {}
        self.image_loaded: bool = False
        self.image_data: Any = None
        self.scene_width: int = 0
        self.scene_height: int = 0
        self.image_width: int = 0
        self.image_height: int = 0
        self.scale: float = 1.0
        self.next_balloon_number: int = 1
        self.undo_stack: list = []
        self.detected_zones: dict = {}
        self.views: list = []
        self.view_boundaries: list = []
        self.selected_view_id: Optional[int] = None
        self.next_view_id: int = 1
        self.mode: str = "dimension"
        self.dimension_type: str = "linear"
        self.ordering_mode: str = "top-to-bottom"
        self.drawing_meta: dict = {
            "name": "",
            "scale": "1:1",
        }
        self.view_isolated: Optional[int] = None
        
    def can_advance_to(self, target: Phase) -> tuple[bool, str]:
        """Returns (allowed: bool, reason: str). reason is shown to user if not allowed."""
        gates = {
            Phase.PHASE_1_ZONE_DETECT: lambda: (self.cv_image is not None, "Please upload a drawing first."),
            Phase.PHASE_2_VIEW_DETECT: lambda: (len(self.zones) == 3, "Zone detection must complete first."),
            Phase.PHASE_3_VIEW_CONFIRM: lambda: (len(self.detected_views) > 0, "No views detected. Run view detection first."),
            Phase.PHASE_4_FLOW_SELECT: lambda: (self.views_confirmed, "Please confirm or edit the detected views."),
            Phase.PHASE_5_DIM_DETECT: lambda: (self.flow_direction is not None, "Please select CW or ACW flow direction."),
            Phase.PHASE_9_EXPORT: lambda: (len(self.balloons) > 0, "No balloons to export. Run detection first."),
        }
        if target in gates:
            result, msg = gates[target]()
            return result, msg
        return True, ""

    def reset_from_phase(self, phase: Phase) -> None:
        """Clears all state derived at or after the given phase, so the user can go back and re-run a step."""
        val = phase.value
        
        # If we are resetting back to a phase, clear state generated at or after that phase
        if val <= Phase.PHASE_1_ZONE_DETECT.value:
            self.zones = {}
            self.detected_zones = {}
            
        if val <= Phase.PHASE_2_VIEW_DETECT.value:
            self.detected_views = []
            self.views = []
            self.view_boundaries = []
            
        if val <= Phase.PHASE_3_VIEW_CONFIRM.value:
            self.views_confirmed = False
            
        if val <= Phase.PHASE_4_FLOW_SELECT.value:
            self.flow_direction = "CW"
            
        if val <= Phase.PHASE_5_DIM_DETECT.value:
            self.balloons = []
            self.next_balloon_number = 1
            
        self.current_phase = phase

    # Magic methods to keep backward compatibility with dict access like state["image_loaded"]
    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)
        
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


# Single global state object
state = State()

def advance_phase() -> bool:
    """Move to the next phase if possible."""
    try:
        current_val = state.current_phase.value
        if current_val < Phase.PHASE_9_EXPORT.value:
            next_phase = Phase(current_val + 1)
            allowed, _ = state.can_advance_to(next_phase)
            if allowed:
                state.current_phase = next_phase
                return True
    except ValueError:
        pass
    return False

def go_back_to_phase(phase_idx: int) -> bool:
    """Jump back to a specific phase by index."""
    try:
        target_phase = Phase(phase_idx)
        state.reset_from_phase(target_phase)
        return True
    except ValueError:
        return False

def add_view(name: str, view_type: str) -> dict:
    """Add a backward-compatible view and return it."""
    view = {
        "id": state.next_view_id,
        "name": name,
        "type": view_type,
        "balloonCount": 0,
    }
    state.next_view_id += 1
    state.views.append(view)
    state.selected_view_id = view["id"]
    return view

def remove_view(view_id: int) -> None:
    """Remove view by id. Balloons keep their viewId (orphaned)."""
    state.views = [v for v in state.views if v.get("id") != view_id]
    if state.selected_view_id == view_id:
        state.selected_view_id = state.views[0]["id"] if state.views else None

def get_balloon_count_for_view(view_id: int) -> int:
    count = 0
    for b in state.balloons:
        if isinstance(b, dict):
            if b.get("viewId") == view_id:
                count += 1
        elif isinstance(b, Balloon):
            if b.view_id == view_id:
                count += 1
    return count

def renumber_all_balloons() -> None:
    """Renumber balloons 1..n with no gaps. Call after delete."""
    state.next_balloon_number = 1
    
    def get_num(b):
        if isinstance(b, dict):
            return b.get("number", 0)
        elif isinstance(b, Balloon):
            return b.sequence_number
        return 0
            
    # Sort balloons by current number or creation order to maintain sequence
    state.balloons.sort(key=get_num)
    
    for b in state.balloons:
        if isinstance(b, dict):
            b["number"] = state.next_balloon_number
        elif isinstance(b, Balloon):
            b.sequence_number = state.next_balloon_number
        state.next_balloon_number += 1
    state.next_balloon_number = len(state.balloons) + 1
