
import React, { useRef, useEffect } from 'react';
import { Stage, Layer, Image as KonvaImage, Rect, Text } from 'react-konva';
import useImage from 'use-image';
import { useDrawingStore } from '../store/drawingStore';
import { useBalloonStore } from '../store/balloonStore';
import BalloonOverlay from './BalloonOverlay';
import { Balloon } from '../types';

const DrawingCanvas: React.FC = () => {
    const { metadata, views } = useDrawingStore();
    const { balloons, selectedBalloonId, setSelectedBalloon, updateBalloon } = useBalloonStore();

    // Load image
    const [image] = useImage(metadata?.image_url || "", "anonymous"); // "anonymous" for CORS if needed

    // Stage ref for zooming
    const stageRef = useRef<any>(null);
    const [scale, setScale] = React.useState(1);
    const [position, setPosition] = React.useState({ x: 0, y: 0 });

    const handleWheel = (e: any) => {
        e.evt.preventDefault();
        const stage = stageRef.current;
        const oldScale = stage.scaleX();
        const pointer = stage.getPointerPosition();

        const mousePointTo = {
            x: (pointer.x - stage.x()) / oldScale,
            y: (pointer.y - stage.y()) / oldScale,
        };

        const newScale = e.evt.deltaY > 0 ? oldScale * 0.9 : oldScale * 1.1;
        setScale(newScale);

        const newPos = {
            x: pointer.x - mousePointTo.x * newScale,
            y: pointer.y - mousePointTo.y * newScale,
        };
        setPosition(newPos);
    };

    const handleBalloonDrag = (id: string, x: number, y: number) => {
        updateBalloon(id, { position: [x, y] });
    };

    if (!metadata) return <div>No Drawing Loaded</div>;

    return (
        <div className="w-full h-full bg-gray-100 overflow-hidden relative">
            <Stage
                width={window.innerWidth}
                height={window.innerHeight}
                onWheel={handleWheel}
                scaleX={scale}
                scaleY={scale}
                x={position.x}
                y={position.y}
                draggable
                ref={stageRef}
            >
                <Layer>
                    {image && <KonvaImage image={image} />}
                </Layer>

                <Layer>
                    {views.map((view) => (
                        <React.Fragment key={view.view_id}>
                            <Rect
                                x={view.bbox[0]}
                                y={view.bbox[1]}
                                width={view.bbox[2]}
                                height={view.bbox[3]}
                                stroke="rgba(0, 0, 255, 0.3)"
                                strokeWidth={2}
                                dash={[10, 5]}
                            />
                            <Text
                                x={view.bbox[0]}
                                y={view.bbox[1] - 20}
                                text={view.label}
                                fontSize={16}
                                fill="blue"
                            />
                        </React.Fragment>
                    ))}
                </Layer>

                <Layer>
                    {balloons.map((balloon) => (
                        <BalloonOverlay
                            key={balloon.balloon_id}
                            balloon={balloon}
                            isSelected={selectedBalloonId === balloon.balloon_id}
                            onSelect={setSelectedBalloon}
                            onDragEnd={handleBalloonDrag}
                        />
                    ))}
                </Layer>
            </Stage>

            <div className="absolute bottom-4 right-4 bg-white p-2 rounded shadow text-xs">
                Zoom: {Math.round(scale * 100)}%
            </div>
        </div>
    );
};

export default DrawingCanvas;
