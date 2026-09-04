import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";

const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);

export function Layout({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="app">
      <nav className="nav">
        <div className="brand">Enterprise RAG</div>
        <NavLink to="/knowledge-bases" className={link}>
          Knowledge bases
        </NavLink>
        <NavLink to="/chat" className={link}>
          Chat
        </NavLink>
        <NavLink to="/evaluation" className={link}>
          Evaluation
        </NavLink>
        <NavLink to="/settings" className={link}>
          Settings
        </NavLink>
        <div className="spacer" />
        <div className="who">
          {user?.display_name || user?.email}
          {user?.is_admin ? " · admin" : ""}
        </div>
        <button onClick={() => void logout()}>Sign out</button>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
