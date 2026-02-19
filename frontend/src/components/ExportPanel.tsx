
import React, { useState } from 'react';
import axios from 'axios';
import { useDrawingStore } from '../store/drawingStore';
import { useBalloonStore } from '../store/balloonStore';

const ExportPanel: React.FC = () => {
    const { metadata } = useDrawingStore();
    const { balloons } = useBalloonStore();
    const [isOpen, setIsOpen] = useState(false);

    // Form State
    const [inspectorName, setInspectorName] = useState("Inspector");
    const [formats, setFormats] = useState({ pdf: true, xlsx: true, json: false });
    const [isGenerating, setIsGenerating] = useState(false);

    const handleExport = async () => {
        if (!metadata) return;
        setIsGenerating(true);

        try {
            const selectedFormats = Object.entries(formats)
                .filter(([_, enabled]) => enabled)
                .map(([fmt]) => fmt);

            // Trigger downloads sequentially
            for (const format of selectedFormats) {
                const response = await axios.post('/api/export', {
                    session_id: metadata.session_id,
                    format: format,
                    inspector_name: inspectorName,
                    drawing_name: "Inspection_Report" // could ideally be original filename
                }, { responseType: 'blob' });

                // Create blob link to download
                const url = window.URL.createObjectURL(new Blob([response.data]));
                const link = document.createElement('a');
                link.href = url;
                link.setAttribute('download', `report_${metadata.session_id}.${format}`);
                document.body.appendChild(link);
                link.click();
                link.remove();
            }

            setIsOpen(false);
        } catch (error) {
            console.error("Export failed", error);
            alert("Export failed. See console.");
        } finally {
            setIsGenerating(false);
        }
    };

    if (balloons.length === 0) return null;

    return (
        <>
            <button
                onClick={() => setIsOpen(true)}
                className="absolute top-4 left-1/2 transform -translate-x-1/2 bg-green-600 hover:bg-green-700 text-white px-6 py-2 rounded-full shadow-lg font-bold flex items-center gap-2 z-20"
            >
                <span>📥</span> Export Report
            </button>

            {isOpen && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
                    <div className="bg-white rounded-xl shadow-2xl p-8 w-96 max-w-full">
                        <h2 className="text-2xl font-bold mb-6 text-gray-800">Export Inspection</h2>

                        <div className="space-y-4 mb-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Inspector Name</label>
                                <input
                                    type="text"
                                    value={inspectorName}
                                    onChange={(e) => setInspectorName(e.target.value)}
                                    className="w-full border rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">Formats</label>
                                <div className="flex gap-4">
                                    {(['pdf', 'xlsx', 'json'] as const).map(fmt => (
                                        <label key={fmt} className="flex items-center gap-2 cursor-pointer">
                                            <input
                                                type="checkbox"
                                                checked={formats[fmt]}
                                                onChange={(e) => setFormats({ ...formats, [fmt]: e.target.checked })}
                                                className="w-4 h-4 text-blue-600 rounded"
                                            />
                                            <span className="uppercase text-sm font-semibold text-gray-600">{fmt}</span>
                                        </label>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className="flex gap-3">
                            <button
                                onClick={() => setIsOpen(false)}
                                className="flex-1 py-3 rounded-lg border border-gray-300 text-gray-700 font-medium hover:bg-gray-50 transition"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleExport}
                                disabled={isGenerating}
                                className="flex-1 py-3 rounded-lg bg-green-600 text-white font-bold hover:bg-green-700 transition shadow disabled:opacity-50"
                            >
                                {isGenerating ? "Generating..." : "Download"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default ExportPanel;
