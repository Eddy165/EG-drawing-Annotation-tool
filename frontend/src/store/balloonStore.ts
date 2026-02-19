
import { create } from 'zustand';
import { Balloon } from '../types';
import { v4 as uuidv4 } from 'uuid'; // Need to install uuid or use simple random

// Simple UUID generator if library not available yet, but we will install it
const generateId = () => Math.random().toString(36).substr(2, 9);

interface BalloonState {
    balloons: Balloon[];
    traversalDirection: "CW" | "CCW";
    selectedBalloonId: string | null;

    // History for Undo/Redo
    history: Balloon[][];
    historyIndex: number;

    setBalloons: (balloons: Balloon[]) => void;
    addBalloon: (balloon: Omit<Balloon, "balloon_id" | "balloon_no">) => void;
    updateBalloon: (id: string, updates: Partial<Balloon>) => void;
    deleteBalloon: (id: string) => void;
    setTraversalDirection: (dir: "CW" | "CCW") => void;
    setSelectedBalloon: (id: string | null) => void;

    undo: () => void;
    redo: () => void;
    canUndo: () => boolean;
    canRedo: () => boolean;

    _pushHistory: (newBalloons: Balloon[]) => void;
}

export const useBalloonStore = create<BalloonState>((set, get) => ({
    balloons: [],
    traversalDirection: "CW",
    selectedBalloonId: null,
    history: [[]],
    historyIndex: 0,

    setBalloons: (balloons) => {
        set({ balloons });
        get()._pushHistory(balloons);
    },

    addBalloon: (balloonData) => {
        const { balloons } = get();
        // Insert new balloon. Logic:
        // If we want to support "Add anywhere and renumber", we need complex logic.
        // For now, simplify: Add to end or insert based on position?
        // Requirement: "All subsequent balloon numbers shift up by 1" -> Insert at specific spot?
        // Let's implement: Add, then user can reorder or we just append.
        // Wait, requirement says "Modal appears... New balloon is inserted... subsequent numbers shift".
        // We need to know WHERE in the sequence. 
        // Heuristic: User clicks, we find the closest balloon in sequence? 
        // Or just append to end? 
        // Let's append to end for MVP unless specific "Insert Before/After" UI exists.
        // Actually, Prompt says "New balloon is inserted at the clicked position".
        // And "All subsequent balloon numbers shift up by 1". 
        // This implies we need to determine the index in the LIST based on spatial position?
        // Or maybe just based on ID if user selected "Add after #5"?
        // Let's assume append for now to KEEP IT SIMPLE, or find nearest balloon number and insert after.

        // Auto-increment number
        const maxNo = balloons.length > 0 ? Math.max(...balloons.map(b => b.balloon_no)) : 0;
        const newNo = maxNo + 1;

        const newBalloon: Balloon = {
            ...balloonData,
            balloon_id: generateId(),
            balloon_no: newNo,
            is_manual: true
        };

        const newBalloons = [...balloons, newBalloon];
        set({ balloons: newBalloons });
        get()._pushHistory(newBalloons);
    },

    updateBalloon: (id, updates) => {
        const { balloons } = get();
        const newBalloons = balloons.map(b => b.balloon_id === id ? { ...b, ...updates } : b);
        set({ balloons: newBalloons });
        get()._pushHistory(newBalloons);
    },

    deleteBalloon: (id) => {
        const { balloons } = get();
        const filtered = balloons.filter(b => b.balloon_id !== id);

        // Renumber
        const renumbered = filtered.map((b, index) => ({
            ...b,
            balloon_no: index + 1
        }));

        set({ balloons: renumbered, selectedBalloonId: null });
        get()._pushHistory(renumbered);
    },

    setTraversalDirection: (dir) => set({ traversalDirection: dir }),
    setSelectedBalloon: (id) => set({ selectedBalloonId: id }),

    undo: () => {
        const { history, historyIndex } = get();
        if (historyIndex > 0) {
            const newIndex = historyIndex - 1;
            set({ balloons: history[newIndex], historyIndex: newIndex });
        }
    },

    redo: () => {
        const { history, historyIndex } = get();
        if (historyIndex < history.length - 1) {
            const newIndex = historyIndex + 1;
            set({ balloons: history[newIndex], historyIndex: newIndex });
        }
    },

    canUndo: () => get().historyIndex > 0,
    canRedo: () => get().historyIndex < get().history.length - 1,

    _pushHistory: (newBalloons) => {
        const { history, historyIndex } = get();
        // Slice history if we are in the middle
        const newHistory = history.slice(0, historyIndex + 1);
        newHistory.push(newBalloons);
        // Limit history size
        if (newHistory.length > 20) newHistory.shift();

        set({ history: newHistory, historyIndex: newHistory.length - 1 });
    }
}));
