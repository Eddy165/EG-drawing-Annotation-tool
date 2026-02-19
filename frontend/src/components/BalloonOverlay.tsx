
import React from 'react';
import { Circle, Line, Text, Group } from 'react-konva';
import { Balloon } from '../types';

interface BalloonOverlayProps {
    balloon: Balloon;
    isSelected: boolean;
    onSelect: (id: string) => void;
    onDragEnd: (id: string, x: number, y: number) => void;
}

const BalloonOverlay: React.FC<BalloonOverlayProps> = ({ balloon, isSelected, onSelect, onDragEnd }) => {
    const { position, balloon_no, type, leader_point } = balloon;
    const [x, y] = position;

    // Color coding
    let color = "#3B82F6"; // Linear - Blue
    if (type === "angular") color = "#F97316";
    if (type === "radius") color = "#22C55E";
    if (type === "notes") color = "#EF4444";
    if (type === "bom") color = "#6B7280";

    if (isSelected) color = "#EAB308"; // Highlight color

    return (
        <Group
            x={x}
            y={y}
            draggable
            onClick={() => onSelect(balloon.balloon_id)}
            onDragEnd={(e) => {
                onDragEnd(balloon.balloon_id, e.target.x(), e.target.y());
            }}
        >
            {/* Leader Line - drawn from (0,0) local to leader point relative to this group? 
           No, leader_point is absolute. We need to draw from 0,0 (group center) to leader_point - group_pos.
       */}
            {leader_point && (
                <Line
                    points={[0, 0, leader_point[0] - x, leader_point[1] - y]}
                    stroke={color}
                    strokeWidth={2}
                />
            )}

            <Circle
                radius={14}
                fill={color}
                shadowBlur={5}
                shadowOpacity={0.3}
            />

            <Text
                text={balloon_no.toString()}
                fontSize={14}
                fontStyle="bold"
                fill="white"
                offsetX={balloon_no > 9 ? 7 : 4}
                offsetY={6}
            />
        </Group>
    );
};

export default BalloonOverlay;
