import React, { useEffect, useState } from "react";
import { SiteFooter } from "../components/common/SiteFooter";
import { APP_NAME, ORGANISATIONS } from "../config/app.ts";
import { api } from "../services";
import "./landing.css";

interface LandingPageProps {
  onNavigate: (path: string) => void;
}

const FEATURES = [
  {
    title: "Face recognition from the teacher's camera",
    body: "The teacher opens the class on a laptop or phone. Each face the camera sees is matched against that class's enrolled students only.",
    icon: "M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316zM16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z",
  },
  {
    title: "No proxies, no replays",
    body: "Every result is signed by the recognition service and can be used once. A liveness check scores each face against printed photos and screen replays.",
    icon: "M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z",
  },
  {
    title: "ENTRY and EXIT rounds",
    body: "Attendance is taken when class starts and again before it ends, so a student who leaves early is not marked present.",
    icon: "M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5",
  },
  {
    title: "Runs on your timetable",
    body: "Load the timetable once. Teachers start the classes they are assigned to, for their own sections and lab groups.",
    icon: "M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5",
  },
  {
    title: "Admin approval and audit trail",
    body: "Nobody gets in without an administrator's approval. Every hand correction is recorded with who made it and why.",
    icon: "M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z",
  },
  {
    title: "Reports and CSV exports",
    body: "Students see their own percentage per subject. Teachers and administrators download class and shortage reports as CSV.",
    icon: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z",
  },
];

const STEPS = [
  { title: "Set up the organisation", body: "The administrator loads the branches, subjects and timetable, and approves teachers." },
  { title: "Students enrol", body: "Each student signs up, picks their section and electives and takes a few photos. An administrator approves." },
  { title: "Teacher takes attendance", body: "In class, the teacher starts the ENTRY round and points the camera at the room. Recognised students are marked." },
  { title: "Finalize and report", body: "After the EXIT round the teacher finalizes. Students, teachers and administrators see the result at once." },
];

const ROSTER = [
  { name: "Ananya G.", state: "present" },
  { name: "Rohan V.", state: "present" },
  { name: "Ishita S.", state: "absent" },
  { name: "Kabir K.", state: "present" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

export const LandingPage: React.FC<LandingPageProps> = ({ onNavigate }) => {
  const go = (path: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    onNavigate(path);
  };
  // Set on the server (CONTACT_EMAIL); without it the card offers the demo instead.
  const [contactEmail, setContactEmail] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .siteInfo()
      .then((site) => !cancelled && setContactEmail(site.contact_email))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  const contactHref = contactEmail
    ? `mailto:${contactEmail}?subject=${encodeURIComponent(`${APP_NAME} for our institution`)}`
    : undefined;

  return (
    <div className="landing">
      <header className="landing-nav">
        <a className="landing-brand" href="/" onClick={go("/")}>
          <span className="landing-crest" aria-hidden="true">
            <svg fill="currentColor" viewBox="0 0 24 24" width="22" height="22">
              <path d="M12 2L1 7l11 5 9-4.09V17h2V7L12 2zm0 13.54L4.82 12 12 8.73 19.18 12 12 15.54zM5 13.18v4L12 21l7-3.82v-4L12 17.5 5 13.18z" />
            </svg>
          </span>
          <span className="landing-brand-name">{APP_NAME}</span>
        </a>
        <nav className="landing-nav-links" aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#organisations">Organisations</a>
        </nav>
        <div className="landing-nav-actions">
          <a className="landing-btn landing-btn-ghost" href="#organisations">
            Sign in
          </a>
          <a className="landing-btn landing-btn-primary" href="/demo" onClick={go("/demo")}>
            Try the demo
          </a>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-text">
            <span className="landing-eyebrow">Face-recognition attendance for colleges</span>
            <h1>
              Attendance that <span className="landing-accent">can't be proxied</span>.
            </h1>
            <p className="landing-lead">
              The teacher points a camera at the class. Every enrolled student it recognises is marked present,
              once, with a signed record. No roll call, no paper sheets, no friends answering for the absent.
            </p>
            <div className="landing-hero-actions">
              <a className="landing-btn landing-btn-primary landing-btn-lg" href="/demo" onClick={go("/demo")}>
                Try the live demo
              </a>
              <a className="landing-btn landing-btn-outline landing-btn-lg" href="#organisations">
                Sign in to your organisation
              </a>
            </div>
            <p className="landing-hero-note">No sign-up for the demo: pick a role and look around.</p>
          </div>

          <div className="landing-hero-visual" aria-hidden="true">
            <div className="landing-mock">
              <div className="landing-mock-bar">
                <span className="landing-dot" />
                <span className="landing-dot" />
                <span className="landing-dot" />
                <span className="landing-mock-title">Computer Networks · Section A · ENTRY</span>
              </div>
              <div className="landing-mock-body">
                <div className="landing-mock-camera">
                  <div className="landing-face landing-face-1">
                    <span>Ananya G.</span>
                  </div>
                  <div className="landing-face landing-face-2">
                    <span>Rohan V.</span>
                  </div>
                  <div className="landing-face landing-face-3">
                    <span>Kabir K.</span>
                  </div>
                  <span className="landing-live">● LIVE</span>
                </div>
                <ul className="landing-mock-roster">
                  {ROSTER.map((row) => (
                    <li key={row.name}>
                      <span>{row.name}</span>
                      <span className={`landing-pill landing-pill-${row.state}`}>
                        {row.state === "present" ? "Present" : "Absent"}
                      </span>
                    </li>
                  ))}
                  <li className="landing-mock-summary">3 of 4 present</li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-strip" aria-label="At a glance">
          <div>
            <strong>3 portals</strong>
            <span>Administrator, teacher, student</span>
          </div>
          <div>
            <strong>2 rounds</strong>
            <span>ENTRY and EXIT in every class</span>
          </div>
          <div>
            <strong>Signed</strong>
            <span>Every recognition, single use</span>
          </div>
          <div>
            <strong>Audited</strong>
            <span>Every change by hand</span>
          </div>
        </section>

        <section id="features" className="landing-section">
          <div className="landing-section-head">
            <h2>Everything a college needs to take attendance it can trust</h2>
            <p>Built for real colleges: shared Wi-Fi, a teacher's own phone, sections and lab groups.</p>
          </div>
          <div className="landing-features">
            {FEATURES.map((feature) => (
              <article key={feature.title} className="landing-feature">
                <span className="landing-feature-icon">
                  <Icon d={feature.icon} />
                </span>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="how" className="landing-section landing-section-alt">
          <div className="landing-section-head">
            <h2>How it works</h2>
            <p>From timetable to report in four steps.</p>
          </div>
          <ol className="landing-steps">
            {STEPS.map((step, index) => (
              <li key={step.title} className="landing-step">
                <span className="landing-step-number">{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="organisations" className="landing-section">
          <div className="landing-section-head">
            <h2>Organisations</h2>
            <p>Each organisation has its own page to sign in and register. Choose yours.</p>
          </div>
          <div className="landing-orgs">
            {ORGANISATIONS.map((org) => (
              <a key={org.slug} className="landing-org" href={`/${org.slug}`} onClick={go(`/${org.slug}`)}>
                <div className="landing-org-top">
                  <span className="landing-org-badge">{org.shortName}</span>
                  <span className="landing-org-status">{org.status}</span>
                </div>
                <h3>{org.name}</h3>
                <p className="landing-org-place">{org.place}</p>
                <p>{org.description}</p>
                <span className="landing-org-link">Sign in or register →</span>
              </a>
            ))}
            <div className="landing-org landing-org-new">
              <div className="landing-org-top">
                <span className="landing-org-badge landing-org-badge-new">+</span>
              </div>
              <h3>Your institution</h3>
              <p>
                Want this for your college or school? Your organisation gets its own page, its timetable and its own
                administrators.
              </p>
              {contactHref ? (
                <a className="landing-btn landing-btn-primary" href={contactHref}>
                  Contact us
                </a>
              ) : (
                <a className="landing-btn landing-btn-outline" href="/demo" onClick={go("/demo")}>
                  See the demo first
                </a>
              )}
            </div>
          </div>
        </section>

        <section className="landing-cta">
          <h2>See it for yourself</h2>
          <p>Sign in as an administrator, a teacher or a student in one click. The demo uses made-up data only.</p>
          <a className="landing-btn landing-btn-light landing-btn-lg" href="/demo" onClick={go("/demo")}>
            Open the demo
          </a>
        </section>
      </main>

      <SiteFooter variant="full" />
    </div>
  );
};
