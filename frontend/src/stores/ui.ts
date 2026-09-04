import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { RetrievalMode } from "@/api/types";

interface UiState {
  activeKbId: string | null;
  activeConversationId: string | null;
  retrievalMode: RetrievalMode;
  setActiveKb: (id: string | null) => void;
  setActiveConversation: (id: string | null) => void;
  setRetrievalMode: (m: RetrievalMode) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      activeKbId: null,
      activeConversationId: null,
      retrievalMode: "hybrid",
      setActiveKb: (id) => set({ activeKbId: id, activeConversationId: null }),
      setActiveConversation: (id) => set({ activeConversationId: id }),
      setRetrievalMode: (m) => set({ retrievalMode: m }),
    }),
    { name: "erp.ui", partialize: (s) => ({ activeKbId: s.activeKbId, retrievalMode: s.retrievalMode }) },
  ),
);
