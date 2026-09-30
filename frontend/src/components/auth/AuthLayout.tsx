import React from "react";
import "./auth.css";

interface AuthLayoutProps {
  children: React.ReactNode;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  return (
    <div className="auth-wrapper">
      <div className="auth-ambient-glow" aria-hidden="true" />

      <main className="auth-content">
        <header className="auth-brand">
          <div className="auth-logo-badge" aria-hidden="true">
            <svg
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
              />
            </svg>
          </div>
          <h1 className="auth-title">Anti-Proxy Attendance</h1>
          <p className="auth-subtitle">
            Intelligent Presence Verification & Attendance Integrity
          </p>
        </header>

        <section className="auth-card" aria-label="Authentication">
          {children}
        </section>

        <footer className="auth-system-badge">
          <svg
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span>JWT + RBAC Protected Endpoint Protocol</span>
        </footer>
      </main>
    </div>
  );
};
