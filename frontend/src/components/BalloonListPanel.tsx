
import React from 'react';
import { useBalloonStore } from '../store/balloonStore';

const BalloonListPanel: React.FC = () => {
    const balloons = useBalloonStore(state => state.balloons);
    const selectedBalloonId = useBalloonStore(state => state.selectedBalloonId);
    const setSelectedBalloon = useBalloonStore(state => state.setSelectedBalloon);

    // Grouping for better UX? Or just flat list as requested?
    // "Right panel: scrollable balloon list"

    if (balloons.length === 0) return null;

    return (
        <div className="absolute top-0 right-0 h-full w-80 bg-white border-l shadow-xl flex flex-col z-0 pt-16">
            <h3 className="p-4 font-bold text-lg border-b bg-gray-50">Balloon List</h3>
            <div className="flex-1 overflow-y-auto">
                <table className="w-full text-sm text-left">
                    <thead className="text-xs text-gray-700 uppercase bg-gray-100 sticky top-0">
                        <tr>
                            <th className="px-4 py-2">No.</th>
                            <th className="px-2 py-2">Type</th>
                            <th className="px-2 py-2">Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {balloons.map((balloon) => (
                            <tr
                                key={balloon.balloon_id}
                                onClick={() => setSelectedBalloon(balloon.balloon_id)}
                                className={`cursor-pointer border-b hover:bg-blue-50 transition ${selectedBalloonId === balloon.balloon_id ? "bg-blue-100" : ""
                                    }`}
                            >
                                <td className="px-4 py-3 font-medium text-gray-900 border-r text-center bg-gray-50 w-12">
                                    {balloon.balloon_no}
                                </td>
                                <td className="px-2 py-3 capitalize text-gray-600">
                                    {balloon.type}
                                </td>
                                <td className="px-2 py-3 font-mono text-blue-600">
                                    {balloon.section === "notes" ? (
                                        <span className="truncate block w-24" title={balloon.text}>
                                            {balloon.text}
                                        </span>
                                    ) : (
                                        `${balloon.value}${balloon.unit}`
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default BalloonListPanel;
