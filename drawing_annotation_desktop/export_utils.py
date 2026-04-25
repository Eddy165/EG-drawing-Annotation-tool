"""
export_utils.py - Exporting data models into JSON, PNG, and PDF formats.
"""

import os
import json
import cv2
import numpy as np
from datetime import datetime
from PIL import Image

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    Image as RLImage, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

from typing import Dict, Any

# Map to BGR for OpenCV overlaid drawing
DIM_TYPE_COLORS = {
    "linear_h": (255, 0, 0),     # Blue
    "linear_v": (0, 255, 0),     # Green
    "angular": (0, 255, 255),    # Yellow
    "radial": (255, 0, 255),     # Magenta
    "circular": (0, 165, 255),   # Orange
    "tolerance": (128, 0, 128),  # Purple
    "alphanumeric": (255, 255, 0), # Cyan
    "note": (0, 140, 200),       # Amber-ish
    "bom": (0, 80, 100),         # Dark Amber
    "manual": (255, 255, 255),   # White
    "unknown": (128, 128, 128)   # Gray
}

def export_json(state: Any, filepath: str) -> None:
    high_conf = sum(1 for b in state.balloons if b.confidence >= 75)
    med_conf = sum(1 for b in state.balloons if 50 <= b.confidence < 75)
    low_conf = sum(1 for b in state.balloons if b.confidence < 50)
    
    export_data = {
        "schema_version": "2.0",
        "export_timestamp": datetime.utcnow().isoformat(),
        "drawing_meta": {
            "paper_size": state.drawing_meta.get("paper_size", "A4") if hasattr(state, 'drawing_meta') else "A4",
            "flow_direction": state.flow_direction or "CW",
            "total_balloons": len(state.balloons),
            "views_count": len(state.detected_views),
            "confidence_summary": {
                "high": high_conf,
                "medium": med_conf,
                "low": low_conf
            }
        },
        "views": [],
        "notes": [],
        "bom": []
    }
    
    # Process balloons
    notes_balloons = [b for b in state.balloons if getattr(b, 'dim_type', '') in ("note", "notes")]
    bom_balloons = [b for b in state.balloons if getattr(b, 'dim_type', '') == "bom"]
    
    def balloon_to_dict(b):
        return {
            "balloon_id": b.balloon_id,
            "sequence": getattr(b, 'sequence_number', 0),
            "dim_type": b.dim_type,
            "value": b.value,
            "tolerance": getattr(b, 'tolerance', ''),
            "unit": getattr(b, 'unit', ''),
            "confidence": b.confidence,
            "position": {"image_x": int(b.position_image[0]), "image_y": int(b.position_image[1])},
            "is_flagged": getattr(b, 'is_flagged', False),
            "is_manual": getattr(b, 'is_manual', False)
        }
        
    export_data["notes"] = [balloon_to_dict(b) for b in sorted(notes_balloons, key=lambda x: getattr(x, 'sequence_number', 0))]
    export_data["bom"] = [balloon_to_dict(b) for b in sorted(bom_balloons, key=lambda x: getattr(x, 'sequence_number', 0))]
    
    for view in state.detected_views:
        view_balloons = [b for b in state.balloons if b.view_id == view.view_id and b.dim_type not in ("note", "notes", "bom")]
        
        view_data = {
            "view_id": view.view_id,
            "label": view.label,
            "bbox": view.bbox,
            "confidence": round(view.confidence, 2),
            "dimensions": [balloon_to_dict(b) for b in sorted(view_balloons, key=lambda x: getattr(x, 'sequence_number', 0))]
        }
        export_data["views"].append(view_data)
        
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

def export_annotated_image(state: Any, filepath: str) -> None:
    if state.cv_image is None:
        raise ValueError("Original image is missing from state.")
        
    img = state.cv_image.copy() # Native BGR map
    
    # b. Draw zone boundaries
    zones = state.zones
    if dz := zones.get("drawing"):
        cv2.rectangle(img, (dz[0], dz[1]), (dz[0]+dz[2], dz[1]+dz[3]), (0, 120, 0), 2)
    if nz := zones.get("notes"):
        cv2.rectangle(img, (nz[0], nz[1]), (nz[0]+nz[2], nz[1]+nz[3]), (0, 140, 200), 2)
    if bz := zones.get("bom"):
        cv2.rectangle(img, (bz[0], bz[1]), (bz[0]+bz[2], bz[1]+bz[3]), (100, 80, 0), 2)
        
    # c. Draw view boundaries semi-transparent based on confidence heuristic scores
    overlay = img.copy()
    for view in state.detected_views:
        vx, vy, vw, vh = view.bbox
        if view.confidence >= 0.75:
            color = (117, 158, 29) # BGR
        elif view.confidence >= 0.50:
            color = (39, 159, 239) # BGR
        else:
            color = (74, 75, 226)  # BGR
                
        cv2.rectangle(overlay, (vx, vy), (vx+vw, vy+vh), color, -1)
        cv2.rectangle(img, (vx, vy), (vx+vw, vy+vh), color, 2)
        
        cv2.putText(img, view.label, (vx, max(20, vy - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        
    cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)
    
    # d. Draw dimension balloons mapping correctly onto the original image space
    sorted_balloons = sorted(state.balloons, key=lambda b: getattr(b, 'sequence_number', 0))
    for b in sorted_balloons:
        cx, cy = int(b.position_image[0]), int(b.position_image[1])
        bcolor = DIM_TYPE_COLORS.get(getattr(b, 'dim_type', ''), DIM_TYPE_COLORS["unknown"])
        
        # Dashed leader line approximation by finding relative center constraints
        parent_view = next((v for v in state.detected_views if v.view_id == b.view_id), None)
        if parent_view and getattr(b, 'dim_type', '') not in ("note", "notes", "bom"):
            vx, vy, vw, vh = parent_view.bbox
            vcx, vcy = vx + vw//2, vy + vh//2
            cv2.line(img, (cx, cy), (vcx, vcy), (150,150,150), 1, cv2.LINE_AA)
            
        cv2.circle(img, (cx, cy), 22, (255, 255, 255), -1)
        cv2.circle(img, (cx, cy), 22, bcolor, 3)
        
        text = str(getattr(b, 'sequence_number', 0))
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        (tw, th), _ = cv2.getTextSize(text, font, font_scale, 2)
        cv2.putText(img, text, (cx - tw//2, cy + th//2), font, font_scale, (0,0,0), 2)
        
        # Auxiliary subtext drawing constraint
        val_str = str(getattr(b, 'value', ''))
        if tolerance := getattr(b, 'tolerance', ''):
            val_str += f" {tolerance}"
        (vw_w, vw_h), _ = cv2.getTextSize(val_str, font, 0.35, 1)
        cv2.putText(img, val_str, (cx - vw_w//2, cy + 22 + vw_h + 5), font, 0.35, (100,100,100), 1)
        
        # e. Flagged manual UI override trigger
        if getattr(b, 'is_flagged', False):
            cv2.putText(img, "!", (cx + 12, cy - 12), font, 0.8, (0,0,255), 2)
            
    # f. Save with PIL at native 300 DPI preservation constraint
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_img)
    pil_img.save(filepath, dpi=(300, 300))

def export_pdf_report(state: Any, image_filepath: str, output_filepath: str) -> None:
    doc = SimpleDocTemplate(output_filepath, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleCentered', parent=styles['Heading1'], alignment=1, fontSize=24, spaceAfter=10)
    sub_style = ParagraphStyle('Subtitle', parent=styles['Normal'], alignment=1, fontSize=12, spaceAfter=30)
    
    # PAGE 1 - Cover Summary
    elements.append(Paragraph("CTQ ANNOTATION REPORT", title_style))
    elements.append(Paragraph(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", sub_style))
    
    high_n = sum(1 for b in state.balloons if b.confidence >= 75)
    med_n = sum(1 for b in state.balloons if 50 <= b.confidence < 75)
    low_n = sum(1 for b in state.balloons if b.confidence < 50)
    notes_n = sum(1 for b in state.balloons if getattr(b, 'dim_type', '') in ("note", "notes"))
    bom_n = sum(1 for b in state.balloons if getattr(b, 'dim_type', '') == "bom")
    dims_n = len(state.balloons) - notes_n - bom_n
    
    summary_data = [
        ["Total Dimensions", str(dims_n)],
        ["Total Notes", str(notes_n)],
        ["Total BOM Entries", str(bom_n)],
        ["Views Detected", str(len(state.detected_views))],
        ["Flow Direction", state.flow_direction or "CW"],
        ["High Confidence", Paragraph(f'<font color="green">{high_n}</font>', styles['Normal'])],
        ["Medium Confidence", Paragraph(f'<font color="#f39c12">{med_n}</font>', styles['Normal'])],
        ["Low Confidence", Paragraph(f'<font color="red">{low_n}</font>', styles['Normal'])],
    ]
    
    t_summary = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
    t_summary.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 40))
    
    # Custom vertical Bar Chart for confidence modeling representation
    d = Drawing(400, 200)
    bc = VerticalBarChart()
    bc.x = 100
    bc.y = 50
    bc.height = 125
    bc.width = 300
    bc.data = [[high_n, med_n, low_n]]
    bc.categoryAxis.categoryNames = ['High (>=75)', 'Medium (50-74)', 'Low (<50)']
    
    bc.bars[0].fillColor = colors.HexColor("#2ecc71")
    bc.bars[1].fillColor = colors.HexColor("#f39c12")
    bc.bars[2].fillColor = colors.HexColor("#e74c3c")
    bc.valueAxis.valueMin = 0
    d.add(bc)
    elements.append(d)
    
    elements.append(PageBreak())
    
    # PAGE 2 - Annotated Image Drawing Render Map
    elements.append(Paragraph("Annotated Drawing Validation", styles['Heading2']))
    if os.path.exists(image_filepath):
        img_element = RLImage(image_filepath, width=7*inch, height=8.5*inch, kind='proportional')
        elements.append(img_element)
    
    paper_sz = state.drawing_meta.get("paper_size", "A4") if hasattr(state, 'drawing_meta') else "A4"
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Drawing Frame:</b> {paper_sz}", styles['Normal']))
    
    elements.append(PageBreak())
    
    # PAGES 3+ - Dynamically allocated CTQ Table representation per view instance
    table_header = ["#", "Type", "Value", "Tolerance", "Unit", "Conf", "Flagged"]
    for view in state.detected_views:
        view_balloons = [b for b in state.balloons if b.view_id == view.view_id and getattr(b, 'dim_type', '') not in ("note", "notes", "bom")]
        if not view_balloons: continue
        
        elements.append(Paragraph(f"View: {view.label} (Confidence: {view.confidence*100:.0f}%)", styles['Heading2']))
        
        row_data = [table_header]
        bg_colors = []
        
        v_high = v_med = v_low = 0
        for i, b in enumerate(sorted(view_balloons, key=lambda x: getattr(x, 'sequence_number', 0))):
            cnf = b.confidence
            if cnf >= 75: v_high += 1
            elif cnf >= 50: v_med += 1
            else: v_low += 1
            
            # Using valid native Helvetica compliant standard encoding 
            flag_str = "FLAG" if getattr(b, 'is_flagged', False) else "OK"
            
            dt = getattr(b, 'dim_type', 'unknown')
            c = colors.whitesmoke
            if dt == "linear_h": c = colors.HexColor("#e6f2ff")
            elif dt == "linear_v": c = colors.HexColor("#e6ffe6")
            elif dt == "angular": c = colors.HexColor("#ffffe6")
            elif dt == "circular": c = colors.HexColor("#fff0e6")
            elif dt == "radial": c = colors.HexColor("#ffe6ff")
            
            bg_colors.append(('BACKGROUND', (0, i+1), (-1, i+1), c))
            row_data.append([
                str(getattr(b, 'sequence_number', 0)), 
                dt, 
                str(getattr(b, 'value', '')), 
                getattr(b, 'tolerance', ''),
                getattr(b, 'unit', ''),
                str(cnf),
                flag_str
            ])
            
        t = Table(row_data, colWidths=[0.5*inch, 1.3*inch, 1.2*inch, 1*inch, 0.6*inch, 0.6*inch, 0.8*inch])
        base_style = [
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]
        t.setStyle(TableStyle(base_style + bg_colors))
        elements.append(t)
        
        elements.append(Spacer(1, 15))
        elements.append(Paragraph(f"<b>View Summary:</b> High: {v_high} | Medium: {v_med} | Low: {v_low}", styles['Normal']))
        elements.append(PageBreak())
        
    # LAST PAGE - BOM Table Export Schema
    bom_balloons = [b for b in state.balloons if getattr(b, 'dim_type', '') == "bom"]
    if bom_balloons:
        elements.append(Paragraph("Bill of Materials (BOM) Entries", styles['Heading2']))
        bom_header = ["Item", "Description", "Qty", "Conf", "Status"]
        bom_data = [bom_header]
        for b in sorted(bom_balloons, key=lambda x: getattr(x, 'sequence_number', 0)):
            flag_str = "FLAG" if getattr(b, 'is_flagged', False) else "OK"
            desc = getattr(b, 'description', str(getattr(b, 'value', '')))
            qty = getattr(b, 'quantity', '1')
            item = getattr(b, 'itemNumber', str(getattr(b, 'sequence_number', 0)))
            
            bom_data.append([item, desc, qty, str(b.confidence), flag_str])
            
        t_bom = Table(bom_data, colWidths=[0.8*inch, 4*inch, 0.6*inch, 0.6*inch, 0.8*inch])
        t_bom.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (1,1), (1,-1), 'LEFT'), # Description left aligned
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(t_bom)
        
    doc.build(elements)

def export_all(state: Any, output_dir: str) -> Dict[str, str]:
    """Convenience wrapper to run JSON, Image, and PDF exports."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    json_path = os.path.join(output_dir, f"ctq_export_{timestamp}.json")
    img_path = os.path.join(output_dir, f"ctq_annotated_{timestamp}.png")
    pdf_path = os.path.join(output_dir, f"ctq_report_{timestamp}.pdf")
    
    # Synchronously flush each export model variant payload
    export_json(state, json_path)
    export_annotated_image(state, img_path)
    export_pdf_report(state, img_path, pdf_path)
    
    return {
        "json": json_path,
        "image": img_path,
        "pdf": pdf_path
    }
