import React, { useEffect, useState } from "react";
import { SiteFooter } from "../components/common/SiteFooter";
import { APP_NAME } from "../config/app.ts";
import { api, auth } from "../services";
import type { TokenResponse, UserRole } from "../types";
import "./landing.css";

interface DemoPageProps {
  onLoginSuccess: (response: TokenResponse) => void;
  onNavigate: (path: string) => void;
}

const ROLES: { role: UserRole; title: string; points: string[] }[] = [
  {
    role: "ADMIN",
    title: "Administrator",
    points: [
      "See the organisation: branches, sections, subjects",
      "The timetable and who teaches what",
      "Approve students and teachers",
      "Reports and shortage lists, CSV downloads",
    ],
  },
  {
    role: "TEACHER",
    title: "Teacher",
    points: [
      "Today's classes from the timetable",
      "Start a class and open the camera",
      "ENTRY and EXIT rounds with live present and absent lists",
      "Finalize, correct by hand, download CSV",
    ],
  },
  {
    role: "STUDENT",
    title: "Student",
    points: [
      "Your classes and attendance per subject",
      "Your own record for every class",
      "Your setup: section, electives, photos",
    ],
  },
];

export const DemoPage: React.FC<DemoPageProps> = ({ onLoginSuccess, onNavigate }) => {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [busyRole, setBusyRole] = useState<UserRole | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .demoAvailable()
      .then((answer) => !cancelled && setAvailable(Boolean(answer.enabled)))
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const start = async (role: UserRole) => {
    setError(null);
    setBusyRole(role);
    try {
      onLoginSuccess(await auth.demoLogin(role));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The demo could not be opened. Please try again.");
    } finally {
      setBusyRole(null);
    }
  };

  const home = (e: React.MouseEvent) => {
    e.preventDefault();
    onNavigate("/");
  };

  return (
    <div className="landing">
      <header className="landing-nav">
        <a className="landing-brand" href="/" onClick={home}>
          <span className="landing-crest" aria-hidden="true">
            <svg fill="currentColor" viewBox="0 0 24 24" width="22" height="22">
              <path d="M12 2L1 7l11 5 9-4.09V17h2V7L12 2zm0 13.54L4.82 12 12 8.73 19.18 12 12 15.54zM5 13.18v4L12 21l7-3.82v-4L12 17.5 5 13.18z" />
            </svg>
          </span>
          <span className="landing-brand-name">{APP_NAME}</span>
        </a>
        <div className="landing-nav-actions">
          <a className="landing-btn landing-btn-ghost" href="/" onClick={home}>
            ← Back to home
          </a>
        </div>
      </header>

      <main className="demo-page">
        <div className="demo-page-head">
          <span className="landing-eyebrow">Live demo</span>
          <h1>Try {APP_NAME}</h1>
          <p>
            Choose a role and you are signed in straight away, no account needed. You can switch roles at any time
            from the bar at the top of the app.
          </p>
        </div>

        {available === false ? (
          <div className="demo-error" role="status">
            The demo is not switched on for this site right now.
          </div>
        ) : (
          <div className="demo-roles">
            {ROLES.map(({ role, title, points }) => (
              <section key={role} className="demo-role" aria-label={`${title} demo`}>
                <h2>{title}</h2>
                <ul>
                  {points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="landing-btn landing-btn-primary"
                  onClick={() => start(role)}
                  disabled={busyRole !== null || available === null}
                >
                  {busyRole === role ? "Opening..." : `Enter as ${title.toLowerCase()}`}
                </button>
              </section>
            ))}
          </div>
        )}

        {error && (
          <div className="demo-error" role="alert">
            {error}
          </div>
        )}

        <div className="demo-notes">
          <strong>About the demo</strong>
          <ul>
            <li>All people and data in the demo are made up. Demo accounts never see any organisation's real data.</li>
            <li>The demo is shared by every visitor and is reset to its starting state every day.</li>
            <li>
              The made-up students have no photos, so the camera will find faces but mark nobody. Real organisations
              enrol their students' faces first.
            </li>
          </ul>
        </div>
      </main>

      <SiteFooter variant="full" />
    </div>
  );
};
