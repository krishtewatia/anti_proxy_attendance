import React from "react";
import "./auth.css";
import { APP_NAME, APP_TAGLINE } from "../../config/app.ts";

interface AuthLayoutProps {
  children: React.ReactNode;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  return (
    <div className="erp-auth-wrapper">
      <main className="erp-auth-container">
        <header className="erp-auth-header">
          {/* The logo and name lead to the public home page. */}
          <a className="erp-auth-home-link" href="/" aria-label={`${APP_NAME} home`}>
            <div className="erp-auth-crest" aria-hidden="true">
              <svg fill="currentColor" viewBox="0 0 24 24" width="32" height="32">
                <path d="M12 2L1 7l11 5 9-4.09V17h2V7L12 2zm0 13.54L4.82 12 12 8.73 19.18 12 12 15.54zM5 13.18v4L12 21l7-3.82v-4L12 17.5 5 13.18z"/>
              </svg>
            </div>
            <h1 className="erp-auth-title">{APP_NAME}</h1>
          </a>
          <p className="erp-auth-subtitle">{APP_TAGLINE}</p>
        </header>

        <section className="erp-auth-card" aria-label="Portal Authentication">
          {children}
        </section>

        <footer className="erp-auth-footer-tag">
          <span>{APP_NAME}</span>
        </footer>
      </main>
    </div>
  );
};
