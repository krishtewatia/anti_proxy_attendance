import React from "react";
import type { UserResponse, UserRole } from "../../types";
import "./layout.css";

interface AppLayoutProps {
  user: UserResponse;
  onLogout: () => void;
  children: React.ReactNode;
}

interface NavItem {
  id: string;
  label: string;
  isPlaceholder?: boolean;
}

function getNavigationItems(role: UserRole): NavItem[] {
  switch (role) {
    case "TEACHER":
      return [
        { id: "dashboard", label: "Dashboard" },
        { id: "sessions", label: "Sessions", isPlaceholder: true },
        { id: "attendance", label: "Attendance", isPlaceholder: true },
      ];
    case "STUDENT":
      return [
        { id: "dashboard", label: "Dashboard" },
        { id: "attendance", label: "My Attendance", isPlaceholder: true },
      ];
    case "ADMIN":
      return [
        { id: "dashboard", label: "Dashboard" },
        { id: "users", label: "Users", isPlaceholder: true },
        { id: "audit", label: "Audit Logs", isPlaceholder: true },
      ];
    default:
      return [{ id: "dashboard", label: "Dashboard" }];
  }
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  user,
  onLogout,
  children,
}) => {
  const navItems = getNavigationItems(user.role);

  return (
    <div className="app-shell">
      {/* Top Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-icon" aria-hidden="true">
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
          <span className="brand-name">Anti-Proxy Attendance</span>
        </div>

        <div className="header-user">
          <div className="user-meta">
            <span className="user-email">{user.email}</span>
            <span
              className={`user-badge role-${user.role.toLowerCase()}`}
            >
              {user.role}
            </span>
          </div>
          <button
            type="button"
            className="btn-header-logout"
            onClick={onLogout}
            title="Sign out of system"
          >
            <svg
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75"
              />
            </svg>
            <span>Sign Out</span>
          </button>
        </div>
      </header>

      {/* Body with Sidebar and Content */}
      <div className="app-body">
        <aside className="app-sidebar" aria-label="Role Navigation">
          <nav>
            <ul className="sidebar-nav-list">
              {navItems.map((item) => (
                <li
                  key={item.id}
                  className={`sidebar-nav-item ${
                    item.id === "dashboard" ? "active" : "disabled"
                  }`}
                  title={item.isPlaceholder ? "Coming in next step" : item.label}
                >
                  <svg
                    className="nav-item-icon"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    viewBox="0 0 24 24"
                  >
                    {item.id === "dashboard" && (
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z"
                      />
                    )}
                    {item.id === "sessions" && (
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"
                      />
                    )}
                    {item.id === "attendance" && (
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    )}
                    {item.id === "users" && (
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
                      />
                    )}
                    {item.id === "audit" && (
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                      />
                    )}
                  </svg>
                  <span>{item.label}</span>
                  {item.isPlaceholder && (
                    <span className="nav-item-badge">Soon</span>
                  )}
                </li>
              ))}
            </ul>
          </nav>

          <div className="sidebar-footer">
            <button
              type="button"
              className="sidebar-footer-btn"
              onClick={onLogout}
            >
              <svg
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75"
                />
              </svg>
              <span>Logout</span>
            </button>
          </div>
        </aside>

        <main className="app-content">{children}</main>
      </div>
    </div>
  );
};
