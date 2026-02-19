
import React from 'react';
import { useBalloonStore } from '../store/balloonStore';

const ManualOverrideToolbar: React.FC = () => {
    // Correct destructuring based on store definition
    const balloons = useBalloonStore(state => state.balloons);
    const selectedBalloonId = useBalloonStore(state => state.selectedBalloonId);
    const undo = useBalloonStore(state => state.undo);
    const redo = useBalloonStore(state => state.redo);
    const canUndo = useBalloonStore(state => state.canUndo);
    const canRedo = useBalloonStore(state => state.canRedo);
    const deleteBalloon = useBalloonStore(state => state.deleteBalloon);
    const addBalloon = useBalloonStore(state => state.addBalloon);

    const handleAdd = () => {
        // Basic implementation: Add linear balloon at center of screen (or via click later)
        addBalloon({
            type: "linear",
            value: "0.0",
            unit: "mm",
            section: "drawing",
            position: [window.innerWidth / 2, window.innerHeight / 2],
            leader_point: [window.innerWidth / 2 + 50, window.innerHeight / 2 + 50],
            is_manual: true
        });
    };

    const handleDelete = () => {
        if (selectedBalloonId) {
            deleteBalloon(selectedBalloonId);
        }
    };

    return (
        <div className="absolute bottom-6 left-1/2 transform -translate-x-1/2 bg-white/90 backdrop-blur px-6 py-3 rounded-full shadow-lg border border-gray-200 z-20 flex items-center gap-4">
            <div className="flex gap-2 border-r pr-4 border-gray-300">
                <button
                    onClick={undo}
                    disabled={!canUndo()}
                    className="p-2 hover:bg-gray-100 rounded disabled:opacity-30 tooltip text-xl"
                    title="Undo (Ctrl+Z)"
                >
                    ↩️
                </button>
                <button
                    onClick={redo}
                    disabled={!canRedo()}
                    className="p-2 hover:bg-gray-100 rounded disabled:opacity-30 tooltip text-xl"
                    title="Redo (Ctrl+Y)"
                >
                    ↪️
                </button>
            </div>

            <div className="flex gap-2">
                <button
                    onClick={handleAdd}
                    className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-full font-medium transition shadow-md flex items-center gap-2"
                >
                    <span className="text-xl">+</span> Add Balloon
                </button>

                <button
                    onClick={handleDelete}
                    disabled={!selectedBalloonId}
                    className="bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 px-5 py-2 rounded-full font-medium transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shadow-sm"
                >
                    <span className="text-xl">🗑️</span> Delete
                </button>
            </div>

            <div className="text-sm text-gray-500 border-l pl-4 border-gray-300">
                {balloons.length} Balloons
            </div>
        </div>
    );
};

export default ManualOverrideToolbar;
