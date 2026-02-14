# Building the Engineering Drawing Annotation Tool

## Run from source

```bash
pip install -r requirements.txt
python main.py
```

## Single executable (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "DrawingAnnotationTool" main.py
```

Output: `dist/DrawingAnnotationTool` (or `DrawingAnnotationTool.exe` on Windows).

For console output on Windows (e.g. debug): omit `--windowed`.

## Cross-platform

- **Windows**: `dist/DrawingAnnotationTool.exe`
- **macOS**: `dist/DrawingAnnotationTool.app`
- **Linux**: `dist/DrawingAnnotationTool`

No runtime dependencies; no internet required.
