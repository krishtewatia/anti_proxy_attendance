import React, { useState } from "react";
import { AuthLayout } from "../components/auth/AuthLayout";
import { LoginForm } from "../components/auth/LoginForm";
import { RegisterForm } from "../components/auth/RegisterForm";
import type { TokenResponse } from "../types";

interface AuthPageProps {
  onLoginSuccess: (response: TokenResponse) => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({ onLoginSuccess }) => {
  const [activeTab, setActiveTab] = useState<"login" | "register">("login");
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  const handleRegisterSuccess = (registeredEmail: string) => {
    setActiveTab("login");
    setSuccessBanner(
      `Account created for ${registeredEmail}! You can now sign in with your password.`
    );
  };

  return (
    <AuthLayout>
      <div className="auth-tabs" role="tablist" aria-label="Authentication modes">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "login"}
          className={`auth-tab-btn ${activeTab === "login" ? "active" : ""}`}
          onClick={() => {
            setActiveTab("login");
            setSuccessBanner(null);
          }}
        >
          Sign In
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "register"}
          className={`auth-tab-btn ${activeTab === "register" ? "active" : ""}`}
          onClick={() => {
            setActiveTab("register");
            setSuccessBanner(null);
          }}
        >
          Register
        </button>
      </div>

      {successBanner && activeTab === "login" && (
        <div className="alert-banner success" style={{ marginBottom: "1.25rem" }} role="status">
          <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{successBanner}</span>
        </div>
      )}

      {activeTab === "login" ? (
        <LoginForm
          onSuccess={onLoginSuccess}
          onSwitchToRegister={() => {
            setActiveTab("register");
            setSuccessBanner(null);
          }}
        />
      ) : (
        <RegisterForm
          onSuccess={handleRegisterSuccess}
          onSwitchToLogin={() => {
            setActiveTab("login");
            setSuccessBanner(null);
          }}
        />
      )}
    </AuthLayout>
  );
};
