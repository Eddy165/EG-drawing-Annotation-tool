
import React from 'react';
import axios from 'axios';
import { useDrawingStore } from '../store/drawingStore';
import { useBalloonStore } from '../store/balloonStore';

const TraversalControls: React.FC = () => {
    const { metadata, views, detectionStatus, setDetectionStatus } = useDrawingStore();
    const { traversalDirection, setTraversalDirection, setBalloons } = useBalloonStore();

    const handleAutoDetect = async () => {
        if (!metadata) return;
        setDetectionStatus("detecting");

        try {
            const response = await axios.post('/api/detect/dimensions', {
                session_id: metadata.session_id,
                views: views,
                direction: traversalDirection
            });

            // Assuming response contains balloons array directly or nested
            if (response.data.balloons) {
                setBalloons(response.data.balloons);
                setDetectionStatus("complete");
            } else {
                console.error("No balloons in response", response.data);
                setDetectionStatus("error");
            }
        } catch (error) {
            console.error("Auto detection failed", error);
            setDetectionStatus("error");
        }
    };

    if (!metadata || views.length === 0) return null;

    return (
        <div className="absolute top-4 right-4 bg-white p-4 rounded shadow-lg z-10 w-72">
            <h3 className="font-bold text-lg mb-3">Traversal & Detection</h3>

            <div className="flex gap-2 mb-4">
                <button
                    onClick={() => setTraversalDirection("CW")}
                    className={`flex-1 py-1 px-2 rounded border transition-colors ${traversalDirection === "CW"
                            ? "bg-blue-100 border-blue-500 text-blue-700 font-medium"
                            : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                        }`}
                >
                    ↻ Clockwise
                </button>
                <button
                    onClick={() => setTraversalDirection("CCW")}
                    className={`flex-1 py-1 px-2 rounded border transition-colors ${traversalDirection === "CCW"
                            ? "bg-blue-100 border-blue-500 text-blue-700 font-medium"
                            : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                        }`}
                >
                    ↺ Counter-CW
                </button>
            </div>

            <button
                onClick={handleAutoDetect}
                disabled={detectionStatus === "detecting"}
                className={`w-full py-2 rounded text-white font-medium transition-colors ${detectionStatus === "detecting"
                        ? "bg-blue-400 cursor-not-allowed"
                        : "bg-blue-600 hover:bg-blue-700 shadow-sm"
                    }`}
            >
                {detectionStatus === "detecting" ? "Detecting Balloons..." : "Start Auto-Detection"}
            </button>
        </div>
    );
};

export default TraversalControls;
