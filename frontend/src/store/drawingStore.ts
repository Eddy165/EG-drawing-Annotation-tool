
import { create } from 'zustand';
import { DrawingMetadata, View } from '../types';

interface DrawingState {
    metadata: DrawingMetadata | null;
    views: View[];
    isUploading: boolean;
    detectionStatus: "idle" | "detecting" | "complete" | "error";

    setMetadata: (metadata: DrawingMetadata) => void;
    setViews: (views: View[]) => void;
    setUploading: (isUploading: boolean) => void;
    setDetectionStatus: (status: "idle" | "detecting" | "complete" | "error") => void;
    reset: () => void;
}

export const useDrawingStore = create<DrawingState>((set) => ({
    metadata: null,
    views: [],
    isUploading: false,
    detectionStatus: "idle",

    setMetadata: (metadata) => set({ metadata }),
    setViews: (views) => set({ views }),
    setUploading: (isUploading) => set({ isUploading }),
    setDetectionStatus: (status) => set({ detectionStatus: status }),
    reset: () => set({ metadata: null, views: [], isUploading: false, detectionStatus: "idle" })
}));
