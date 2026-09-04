import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import { Layout } from "@/components/Layout";
import { LoginPage } from "@/pages/LoginPage";
import { KnowledgeBasesPage } from "@/pages/KnowledgeBasesPage";
import { KnowledgeBaseDetailPage } from "@/pages/KnowledgeBaseDetailPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { ChatPage } from "@/pages/ChatPage";
import { EvaluationPage } from "@/pages/EvaluationPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  const status = useAuthStore((s) => s.status);
  const bootstrap = useAuthStore((s) => s.bootstrap);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  if (status === "idle" || status === "loading") {
    return <div className="auth-wrap">Loading…</div>;
  }

  if (status !== "authenticated") {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/knowledge-bases" replace />} />
        <Route path="/login" element={<Navigate to="/knowledge-bases" replace />} />
        <Route path="/knowledge-bases" element={<KnowledgeBasesPage />} />
        <Route path="/knowledge-bases/:kbId" element={<KnowledgeBaseDetailPage />} />
        <Route path="/knowledge-bases/:kbId/documents" element={<DocumentsPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/evaluation" element={<EvaluationPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/knowledge-bases" replace />} />
      </Routes>
    </Layout>
  );
}
