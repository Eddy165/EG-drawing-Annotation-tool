
import pytest
import os
import sys
import json
import openpyxl

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.report_generator import ReportGenerator

def test_generate_reports():
    generator = ReportGenerator(output_dir="backend/tests/reports")
    
    data = {
        "metadata": {
            "drawing_name": "Test Drawing",
            "inspector": "John Doe",
            "date": "2023-10-27",
            "total_balloons": 5
        },
        "balloons": [
            {"balloon_no": 1, "type": "linear", "value": "10.5", "unit": "mm", "section": "drawing", "view_id": "v1", "position": [100, 100]},
            {"balloon_no": 2, "type": "radius", "value": "R5", "unit": "", "section": "drawing", "view_id": "v1", "position": [200, 200]}
        ],
        "notes": [
            {"balloon_no": 3, "text": "Note 1"}
        ],
        "bom": [
            {"balloon_no": 4, "item_no": "1", "description": "Screw", "qty": "2", "material": "Steel"}
        ]
    }
    
    # JSON
    json_path = generator.generate_json(data, "test_report")
    assert os.path.exists(json_path)
    with open(json_path, 'r') as f:
        loaded = json.load(f)
        assert loaded["metadata"]["drawing_name"] == "Test Drawing"
        
    # XLSX
    xlsx_path = generator.generate_xlsx(data, "test_report")
    assert os.path.exists(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path)
    assert "Dimensions" in wb.sheetnames
    assert "Notes" in wb.sheetnames
    
    # PDF
    pdf_path = generator.generate_pdf(data, "test_report")
    assert os.path.exists(pdf_path)
    # Checking PDF content is hard without extra libs, just existence is enough for MVP
