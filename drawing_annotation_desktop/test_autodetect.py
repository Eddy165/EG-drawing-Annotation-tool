import cv2
import sys
import os

sys.path.insert(0, os.path.abspath('d:/INTERNSHIP/FLECS autotech/EG SECTORIZING TOOL/drawing_annotation_desktop'))
from autodetect import (
    detect_paper_size_and_scale,
    preprocess_drawing_image,
    segment_drawing_zones_from_image,
    detect_all_lines,
    classify_dimension_lines,
    pair_extension_lines,
    extract_dimension_roi,
    run_ocr_on_roi,
    compute_detection_confidence,
    DimensionType, LineOrientation, DetectedDimension,
    compute_balloon_position,
    sequence_balloons_by_flow,
    debug_visualize_all,
    DetectedView
)

img_path = r"d:\INTERNSHIP\FLECS autotech\EG SECTORIZING TOOL\sample inputs\image (1).png"
print(f"Loading image from: {img_path}")
img_bgr = cv2.imread(img_path)

if img_bgr is None:
    print("Failed to load image.")
    sys.exit(1)

print("Image loaded. Converting to grayscale...")
img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

print("Detecting paper size and scale...")
paper_size, scale_factor, est_dpi = detect_paper_size_and_scale(img_gray)
print(f"Paper: {paper_size}, Scale: {scale_factor:.2f}, Est DPI: {est_dpi}")

print("Preprocessing image...")
preprocessed = preprocess_drawing_image(img_gray, scale_factor)

print("Segmenting drawing zones...")
zones_obj = segment_drawing_zones_from_image(img_gray, preprocessed, paper_size, scale_factor)
dz = zones_obj.drawing_zone
print(f"Drawing zone: {dz}")

print("Detecting lines...")
all_lines = detect_all_lines(preprocessed, dz, scale_factor)
print(f"Detected {len(all_lines)} lines.")

print("Classifying dimension lines...")
classified = classify_dimension_lines(all_lines, preprocessed["binary_inv"], scale_factor)

print("Pairing extension lines...")
paired = pair_extension_lines(classified, scale_factor)

dim_lines = [p.dim_line for p in paired if p.dim_line.is_dimension_line]
leader_lines = [l for l in classified if l.is_leader_line and l.length > int(20*scale_factor)]

print(f"Found {len(dim_lines)} dimension lines and {len(leader_lines)} leader lines.")

confirmed = []
placed = []

for line in dim_lines + leader_lines:
    try:
        roi, roi_coords = extract_dimension_roi(img_gray, line, scale_factor)
        value, ocr_conf, engine = run_ocr_on_roi(roi, roi_coords)
    except Exception as e:
        print(f"OCR Error: {e}")
        value, ocr_conf, engine = "", 0.0, "none"
        
    ext_pair = next((p for p in paired if p.dim_line is line), None)
    from autodetect import normalize_dimension_value
    conf = compute_detection_confidence(line, ext_pair, value, ocr_conf, scale_factor)
    
    if conf < 50 and not value:
        continue
        
    if value.upper().startswith('R'):  dt = DimensionType.RADIUS
    elif 'Ø' in value:                 dt = DimensionType.DIAMETER
    elif '°' in value:                 dt = DimensionType.ANGULAR
    elif line.orientation == LineOrientation.VERTICAL: dt = DimensionType.LINEAR_VERTICAL
    else:                              dt = DimensionType.LINEAR_HORIZONTAL
    
    view_id = "view_0"
    for vi, vz in enumerate(zones_obj.view_zones):
        if vz.contains_point(*line.midpoint):
            view_id = f"view_{vi}"; break
            
    dim = DetectedDimension(
        dim_type=dt, line=line, extension_pair=ext_pair,
        ocr_value_raw=value, ocr_value_clean=normalize_dimension_value(value),
        ocr_confidence=ocr_conf, ocr_engine_used=engine, ocr_bbox=roi_coords,
        anchor_point=(0,0), balloon_center=(0,0),
        detection_confidence=conf, view_id=view_id)
        
    anchor, bc = compute_balloon_position(dim, placed, dz, scale_factor, len(placed))
    dim.anchor_point = anchor; dim.balloon_center = bc
    confirmed.append(dim); placed.append(dim)

sequenced = sequence_balloons_by_flow(confirmed, dz, "clockwise")
print(f"Placed {len(sequenced)} balloons.")

# Mock views for visualization
views = []
for i, vz in enumerate(zones_obj.view_zones):
    views.append(DetectedView(view_id=i+1, label=f"VIEW {i+1}", bbox=vz.to_tuple(), confidence=0.8, label_source="inferred"))

print("Generating visualization...")
vis = debug_visualize_all(img_bgr, zones_obj, views, sequenced)

out_path = "debug_output.png"
cv2.imwrite(out_path, vis)
print(f"Saved debug output to {out_path}")
