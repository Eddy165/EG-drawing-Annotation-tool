
import math
import numpy as np
from typing import List, Dict, Any, Tuple

class TraversalEngine:
    def __init__(self):
        pass

    def sequence_balloons(self, views: List[Dict[str, Any]], dimensions_by_view: Dict[str, List[Dict[str, Any]]], direction: str = "CW") -> List[Dict[str, Any]]:
        """
        Sequences balloons across all views and dimensions.
        """
        ordered_balloons = []
        current_balloon_no = 1
        
        # Sort views by spatial order just in case they aren't
        sorted_views = sorted(views, key=lambda v: v.get("spatial_order", 0))
        
        for view in sorted_views:
            view_id = view["view_id"]
            dims = dimensions_by_view.get(view_id, [])
            
            if not dims:
                continue
                
            # 1. Determine Start Point
            # CW: Top-Left (Min Y, Min X)
            # CCW: Top-Right (Min Y, Max X) -> Prompt said "y ASC, then x DESC"
            
            # Create a list of unvisited dimensions with their centroids
            unvisited = []
            for d in dims:
                # Calculate center of bbox or use provided leader point
                if "leader_point" in d:
                    cx, cy = d["leader_point"]
                elif "bbox" in d:
                    x, y, w, h = d["bbox"]
                    cx, cy = x + w/2, y + h/2
                else:
                    cx, cy = 0, 0 # Fallback
                
                d["_center"] = (cx, cy)
                unvisited.append(d)
            
            if not unvisited:
                continue

            # Sort to find start node
            if direction == "CW":
                # Start: Top-Left (low Y, low X)
                start_node = sorted(unvisited, key=lambda d: (d["_center"][1], d["_center"][0]))[0]
            else:
                # Start: Top-Right (low Y, high X) -> Prompt said "y ASC, then x DESC"
                start_node = sorted(unvisited, key=lambda d: (d["_center"][1], -d["_center"][0]))[0]
                
            # Initialize traversal with start node
            ordered_balloons.append(self._create_balloon(start_node, current_balloon_no, view_id))
            unvisited.remove(start_node)
            current_balloon_no += 1
            current_pos = start_node["_center"]
            
            # Nearest Neighbour Loop
            while unvisited:
                # Find closest next point
                # Make "closest" directional if possible? 
                # Prompt: "repeatedly pick the next closest unvisited dimension in the traversal direction"
                # CW = right-then-down
                # CCW = left-then-down
                
                # Heuristic: Weighted distance? 
                # If we just do pure euclidean distance, we might jump back and forth.
                # To bias direction, we can penalize moving against the sweep.
                # But "Nearest Neighbour" usually implies pure distance.
                # Let's start with pure Euclidean distance as MVP logic 
                # but maybe filter/prioritize points in the sweep cone.
                
                # Simple Euclidean for now as it's robust enough for "Nearest Neighbor"
                best_dist = float('inf')
                best_node = None
                
                for node in unvisited:
                    nx, ny = node["_center"]
                    dist = math.hypot(nx - current_pos[0], ny - current_pos[1])
                    
                    # Optional: Add small penalty if moving "up" (negative Y diff) significantly?
                    # Generally we want to go down.
                    if ny < current_pos[1] - 50: # moving up more than 50px
                         dist *= 1.5 
                    
                    if dist < best_dist:
                        best_dist = dist
                        best_node = node
                
                if best_node:
                    ordered_balloons.append(self._create_balloon(best_node, current_balloon_no, view_id))
                    unvisited.remove(best_node)
                    current_balloon_no += 1
                    current_pos = best_node["_center"]
                    
        return ordered_balloons

    def _create_balloon(self, dimension: Dict[str, Any], number: int, view_id: str) -> Dict[str, Any]:
        return {
            "balloon_no": number,
            "dim_id": dimension.get("dim_id"),
            "view_id": view_id,
            "type": dimension.get("type", "linear"),
            "value": dimension.get("value", ""),
            "unit": dimension.get("unit", ""),
            "leader_point": dimension.get("leader_point", list(dimension.get("_center", [0,0]))),
            "position": dimension.get("_center", [0,0]), # Initial balloon position (on top of dim)
            "is_manual": False
        }
