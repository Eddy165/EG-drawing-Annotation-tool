
import React from 'react';
import { useDrawingStore } from './store/drawingStore';

// Components
import UploadZone from './components/UploadZone';
import DrawingCanvas from './components/DrawingCanvas';
import ViewConfirmPanel from './components/ViewConfirmPanel';
import TraversalControls from './components/TraversalControls';
import ManualOverrideToolbar from './components/ManualOverrideToolbar';
import BalloonListPanel from './components/BalloonListPanel';
import ExportPanel from './components/ExportPanel';

function App() {
  const { metadata, isUploading } = useDrawingStore();

  return (
    <div className="w-screen h-screen bg-gray-50 font-sans text-gray-900 overflow-hidden relative selection:bg-blue-100">

      {/* HEADER / NAV (Optional, kept minimal per requirements) */}

      {/* MAIN CONTENT AREA */}
      {!metadata ? (
        // UPLOAD STATE
        <div className="flex items-center justify-center h-full w-full p-8">
          <div className="max-w-2xl w-full">
            <h1 className="text-4xl font-extrabold text-center mb-2 text-gray-800 tracking-tight">
              EG Drawing Inspector
            </h1>
            <p className="text-center text-gray-500 mb-10 text-lg">
              Automated Ballooning & Inspection for Engineering Drawings
            </p>
            <UploadZone />
            {isUploading && (
              <div className="mt-8 text-center animate-pulse text-blue-600 font-medium">
                Uploading & Pre-processing...
              </div>
            )}
          </div>
        </div>
      ) : (
        // EDITING STATE
        <>
          <DrawingCanvas />

          {/* OVERLAYS */}
          <ViewConfirmPanel />
          <TraversalControls />
          <ManualOverrideToolbar />
          <BalloonListPanel />
          <ExportPanel />
        </>
      )}
    </div>
  );
}

export default App;
