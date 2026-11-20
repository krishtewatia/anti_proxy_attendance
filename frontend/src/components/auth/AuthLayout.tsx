import React from "react";
import "./auth.css";
import { APP_NAME, APP_TAGLINE, type Organisation } from "../../config/app.ts";
import { SiteFooter } from "../common/SiteFooter";

interface AuthLayoutProps {
  children: React.ReactNode;
  // The organisation whose sign-in page this is (shown above the form).
  organisation?: Organisation;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children, organisation }) => {
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

        {organisation && (
          <div className="erp-auth-org" aria-label="Organisation">
            <span className="erp-auth-org-badge">{organisation.shortName}</span>
            <div className="erp-auth-org-text">
              <span className="erp-auth-org-name">{organisation.name}</span>
              <span className="erp-auth-org-meta">
                {organisation.place} · {organisation.status}
              </span>
            </div>
            <a className="erp-auth-org-switch" href="/#organisations">
              Change
            </a>
          </div>
        )}

        <section className="erp-auth-card" aria-label="Portal Authentication">
          {children}
        </section>

        <SiteFooter variant="compact" />
      </main>
    </div>
  );
};
