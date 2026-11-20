import React from "react";
import { APP_NAME, AUTHOR_NAME, AUTHOR_URL } from "../../config/app.ts";
import "./site-footer.css";

// Read once when the page loads.
const COPYRIGHT_YEAR = new Date().getFullYear();

interface SiteFooterProps {
  // "full" on the public pages, "compact" inside the app and on sign-in pages.
  variant?: "full" | "compact";
}

export const SiteFooter: React.FC<SiteFooterProps> = ({ variant = "compact" }) => {
  const year = COPYRIGHT_YEAR;
  return (
    <footer className={`site-footer site-footer-${variant}`}>
      <span className="site-footer-made">
        Made by{" "}
        <a href={AUTHOR_URL} target="_blank" rel="noopener noreferrer" className="site-footer-author">
          {AUTHOR_NAME}
        </a>
      </span>
      <span className="site-footer-sep" aria-hidden="true">·</span>
      <span>
        © {year} {APP_NAME}
      </span>
    </footer>
  );
};
