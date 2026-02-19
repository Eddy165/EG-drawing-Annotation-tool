
import React from 'react';
import { useDrawingStore } from '../store/drawingStore';

const ViewConfirmPanel: React.FC = () => {
    const { views, setViews, setDetectionStatus } = useDrawingStore();

    if (views.length === 0) return null;

    const handleDelete = (viewId: string) => {
        setViews(views.filter(v => v.view_id !== viewId));
    };

    const handleConfirm = () => {
        // Proceed to Dimension Detection setup
        // Ideally we might change a step state here
        // For now, next step is manually triggered or flows naturally
        setDetectionStatus("idle"); // reset status to allow next action
    };

    return (
        <div className="absolute top-4 left-4 bg-white p-4 rounded shadow-lg z-10 w-64">
            <h3 className="font-bold text-lg mb-2">Detected Views</h3>
            <ul className="max-h-60 overflow-y-auto mb-4">
                {views.map(view => (
                    <li key={view.view_id} className="flex justify-between items-center py-1 border-b text-sm">
                        <span>{view.label}</span>
                        <button
                            onClick={() => handleDelete(view.view_id)}
                            className="text-red-500 hover:text-red-700 px-2"
                        >
                            ×
                        </button>
                    </li>
                ))}
            </ul>
            <button
                onClick={handleConfirm}
                className="w-full bg-green-500 text-white py-2 rounded hover:bg-green-600 transition"
            >
                Confirm Views
            </button>
        </div>
    );
};

export default ViewConfirmPanel;
