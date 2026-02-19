
import pytest
import shutil
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.traversal_engine import TraversalEngine

def test_sequence_cw():
    engine = TraversalEngine()
    
    views = [{"view_id": "v1", "spatial_order": 1}]
    
    # Create dimensions in a grid:
    # (0,0)  (10,0)
    # (0,10) (10,10)
    dims = [
        {"dim_id": "d1", "bbox": [0, 0, 2, 2], "_center": (1, 1)},    # Top-Left
        {"dim_id": "d2", "bbox": [10, 0, 2, 2], "_center": (11, 1)},  # Top-Right
        {"dim_id": "d3", "bbox": [0, 10, 2, 2], "_center": (1, 11)},  # Bot-Left
        {"dim_id": "d4", "bbox": [10, 10, 2, 2], "_center": (11, 11)} # Bot-Right
    ]
    # Scramble input order
    input_dims = {"v1": [dims[3], dims[0], dims[2], dims[1]]}
    
    # CW Expectation: Start Top-Left (1,1), then closest?
    # From (1,1):
    # - to (11,1) is dist 10
    # - to (1,11) is dist 10
    # - to (11,11) is dist 14.1
    # Ties? Sort logic for start node: Y ASC, X ASC -> (1,1) is clearly first.
    # Next neighbor: if dists are equal, it depends on list order unless we stabilise sort.
    # But usually CW implies left-to-right then down?
    # My "Nearest Neighbor" logic doesn't strictly enforce left-right, just distance.
    # But let's see. 
    
    balloons = engine.sequence_balloons(views, input_dims, direction="CW")
    
    assert balloons[0]["dim_id"] == "d1" # Definitely first
    assert len(balloons) == 4
    
    # Check increasing balloon numbers
    nums = [b["balloon_no"] for b in balloons]
    assert nums == [1, 2, 3, 4]

def test_sequence_ccw():
    engine = TraversalEngine()
    views = [{"view_id": "v1", "spatial_order": 1}]
    
    # (0,0)  (10,0)
    # (0,10) (10,10)
    dims = [
        {"dim_id": "d1", "bbox": [0, 0, 2, 2], "_center": (1, 1)},    # Top-Left
        {"dim_id": "d2", "bbox": [10, 0, 2, 2], "_center": (11, 1)},  # Top-Right
    ]
    input_dims = {"v1": dims}
    
    # CCW Start: Top-Right (Y min, X max) -> d2
    balloons = engine.sequence_balloons(views, input_dims, direction="CCW")
    
    assert balloons[0]["dim_id"] == "d2"
    assert balloons[1]["dim_id"] == "d1"
