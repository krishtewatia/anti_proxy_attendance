import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { AuthPage } from "./pages/AuthPage";
import { AuthLayout } from "./components/auth/AuthLayout";
import { ChangePasswordForm } from "./components/auth/ChangePasswordForm";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppLayout } from "./components/layout/AppLayout";
import { auth } from "./services";
import type { TokenResponse, UserResponse } from "./types";
import { getDashboardPath } from "./utils/auth";

// Each role's pages load only when that role opens them, so a student never
// downloads the admin panel (and the first page loads faster on a phone).
const TeacherAttendanceFlow = lazy(() => import("./pages/TeacherAttendanceFlow").then((m) => ({ default: m.TeacherAttendanceFlow })));
const SessionDetails = lazy(() => import("./pages/SessionDetails").then((m) => ({ default: m.SessionDetails })));
const StudentDashboard = lazy(() => import("./pages/StudentDashboard").then((m) => ({ default: m.StudentDashboard })));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard").then((m) => ({ default: m.AdminDashboard })));

function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="erp-loading-state">Loading...</div>}>{children}</Suspense>;
}

export function App() {
  const [currentUser, setCurrentUser] = useState<UserResponse | null>(() =>
    auth.getStoredUser()
  );
  const [activeNavId, setActiveNavId] = useState<string>("dashboard");
  // Registrations and photo changes waiting for an administrator (admin badge).
  const [pendingApprovals, setPendingApprovals] = useState<number>(0);
  // An account created or reset by an administrator must choose a password first.
  const [mustChangePassword, setMustChangePassword] = useState<boolean>(() =>
    auth.mustChangePassword()
  );
  const [currentPath, setCurrentPath] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return window.location.pathname || "/";
    }
    return "/";
  });

  const navigate = (path: string) => {
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", path);
    }
    setCurrentPath(path);
  };

  const handleNavSelect = (navId: string) => {
    setActiveNavId(navId);
    if (currentUser) {
      const baseDashboard = getDashboardPath(currentUser.role);
      if (currentPath !== baseDashboard) {
        navigate(baseDashboard);
      }
    }
  };

  useEffect(() => {
    const handlePopState = () => {
      setCurrentUser(auth.getStoredUser());
      setMustChangePassword(auth.mustChangePassword());
      setCurrentPath(window.location.pathname || "/");
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Step 2C.2.6 & Step 2C.3: If authenticated user opens "/", redirect to their role dashboard
  useEffect(() => {
    if (currentPath === "/" && currentUser && auth.isAuthenticated()) {
      navigate(getDashboardPath(currentUser.role));
    }
  }, [currentPath, currentUser]);

  const handleLoginSuccess = (response: TokenResponse) => {
    setCurrentUser(response.user);
    setMustChangePassword(Boolean(response.must_change_password));
    setActiveNavId("dashboard");
    const targetDashboard = getDashboardPath(response.user.role);
    navigate(targetDashboard);
  };

  const handleLogout = () => {
    auth.logout();
    setCurrentUser(null);
    setMustChangePassword(false);
    setActiveNavId("dashboard");
    navigate("/");
  };

  const openChangePassword = () => navigate("/account/password");

  // The logo and name in the header: the home page of the signed-in role.
  const goHome = () => {
    setActiveNavId("dashboard");
    navigate(currentUser ? getDashboardPath(currentUser.role) : "/");
  };

  // Before anything else: an account that must change its password sees only that.
  if (currentUser && auth.isAuthenticated() && mustChangePassword) {
    return (
      <AuthLayout>
        <ChangePasswordForm
          forced
          onDone={() => {
            setMustChangePassword(false);
            setCurrentUser(auth.getStoredUser());
            navigate(getDashboardPath(currentUser.role));
          }}
          onCancel={handleLogout}
        />
      </AuthLayout>
    );
  }

  // Any signed-in user can change their own password.
  if (currentPath === "/account/password") {
    return (
      <ProtectedRoute currentUser={currentUser} onNavigate={navigate}>
        {currentUser && (
          <AppLayout
            user={currentUser}
            onLogout={handleLogout}
            onGoHome={goHome}
            activeNavId=""
            onSelectNav={handleNavSelect}
          >
            <div style={{ maxWidth: "440px", margin: "0 auto" }}>
              <div className="erp-page-header">
                <h1 className="erp-page-title">Change Password</h1>
                <p className="erp-page-subtitle">{currentUser.email}</p>
              </div>
              <div className="erp-card" style={{ padding: "1.5rem" }}>
                <ChangePasswordForm
                  forced={false}
                  onDone={() => {
                    setCurrentUser(auth.getStoredUser());
                    navigate(getDashboardPath(currentUser.role));
                  }}
                  onCancel={() => navigate(getDashboardPath(currentUser.role))}
                />
              </div>
            </div>
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 1: Teacher Attendance Flow (ERP Multi-view Workflow)
  if (currentPath === "/teacher/dashboard" || currentPath === "/dashboard/teacher") {
    return (
      <ProtectedRoute
        allowedRoles={["TEACHER", "ADMIN"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout
            user={currentUser}
            onLogout={handleLogout}
            onGoHome={goHome}
            activeNavId={activeNavId}
            onChangePassword={openChangePassword}
            onSelectNav={handleNavSelect}
          >
            <Page>
<TeacherAttendanceFlow
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onSelectNav={handleNavSelect}
            />
</Page>
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 1B: Teacher Session Details: /dashboard/teacher/sessions/:sessionId or /teacher/sessions/:sessionId
  const sessionDetailsMatch = currentPath.match(
    /^\/(?:dashboard\/teacher|teacher)\/sessions\/([^/]+)$/
  );
  if (sessionDetailsMatch) {
    const sessionId = decodeURIComponent(sessionDetailsMatch[1]);
    return (
      <ProtectedRoute
        allowedRoles={["TEACHER", "ADMIN"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout
            user={currentUser}
            onLogout={handleLogout}
            onGoHome={goHome}
            activeNavId="sessions"
            onChangePassword={openChangePassword}
            onSelectNav={handleNavSelect}
          >
            <Page>
<SessionDetails
              sessionId={sessionId}
              user={currentUser}
              onNavigate={navigate}
            />
</Page>
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 2: Student Dashboard
  if (currentPath === "/student/dashboard" || currentPath === "/dashboard/student") {
    return (
      <ProtectedRoute
        allowedRoles={["STUDENT"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout
            user={currentUser}
            onLogout={handleLogout}
            onGoHome={goHome}
            activeNavId={activeNavId}
            onChangePassword={openChangePassword}
            onSelectNav={handleNavSelect}
          >
            <Page>
<StudentDashboard
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onSelectNav={handleNavSelect}
            />
</Page>
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 3: Admin Dashboard
  if (currentPath === "/admin/dashboard" || currentPath === "/dashboard/admin") {
    return (
      <ProtectedRoute
        allowedRoles={["ADMIN"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout
            user={currentUser}
            onLogout={handleLogout}
            onGoHome={goHome}
            activeNavId={activeNavId}
            onChangePassword={openChangePassword}
            onSelectNav={handleNavSelect}
            navBadges={{ approvals: pendingApprovals }}
          >
            <Page>
<AdminDashboard
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onSelectNav={handleNavSelect}
              onPendingCountChange={setPendingApprovals}
            />
</Page>
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Fallback for any unknown route: if authenticated, redirect to role dashboard, else render AuthPage
  if (currentPath !== "/" && currentPath !== "/login") {
    if (currentUser && auth.isAuthenticated()) {
      navigate(getDashboardPath(currentUser.role));
      return null;
    }
  }

  // Default route: / or /login (AuthPage)
  return <AuthPage onLoginSuccess={handleLoginSuccess} />;
}

export default App;
