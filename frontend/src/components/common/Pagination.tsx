import React from "react";
import type { Page } from "../../utils/sessions.ts";

interface PaginationProps {
  page: Page<unknown>;
  onChange: (page: number) => void;
  label: string;
}

const smallButton: React.CSSProperties = { padding: "0.25rem 0.6rem", fontSize: "0.75rem" };

// The "Showing 1–15 of 45 / Previous / Next" bar under a long list.
export const Pagination: React.FC<PaginationProps> = ({ page, onChange, label }) => {
  if (page.total === 0) {
    return null;
  }
  return (
    <div className="erp-pagination" role="navigation" aria-label={label}>
      <span className="erp-pagination-summary">
        Showing {page.from}–{page.to} of {page.total}
      </span>
      <div className="erp-pagination-buttons">
        <button
          type="button"
          className="erp-btn erp-btn-secondary"
          style={smallButton}
          disabled={page.page <= 1}
          onClick={() => onChange(page.page - 1)}
        >
          ← Previous
        </button>
        <span className="erp-pagination-page">
          Page {page.page} of {page.pageCount}
        </span>
        <button
          type="button"
          className="erp-btn erp-btn-secondary"
          style={smallButton}
          disabled={page.page >= page.pageCount}
          onClick={() => onChange(page.page + 1)}
        >
          Next →
        </button>
      </div>
    </div>
  );
};
