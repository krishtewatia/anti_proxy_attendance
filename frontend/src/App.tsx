import { useEffect, useState } from "react";
import { AuthPage } from "./pages/AuthPage";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppLayout } from "./components/layout/AppLayout";
import { TeacherAttendanceFlow } from "./pages/TeacherAttendanceFlow";
import { SessionDetails } from "./pages/SessionDetails";
import { StudentDashboard } from "./pages/StudentDashboard";
import { AdminDashboard } from "./pages/AdminDashboard";
import { auth } from "./services";
import type { TokenResponse, UserResponse } from "./types";
import { getDashboardPath } from "./utils/auth";

export function App() {
  const [currentUser, setCurrentUser] = useState<UserResponse | null>(() =>
    auth.getStoredUser()
  );
  const [activeNavId, setActiveNavId] = useState<string>("dashboard");
  // Registrations and photo changes waiting for an administrator (admin badge).
  const [pendingApprovals, setPendingApprovals] = useState<number>(0);
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
    setActiveNavId("dashboard");
    const targetDashboard = getDashboardPath(response.user.role);
    navigate(targetDashboard);
  };

  const handleLogout = () => {
    auth.logout();
    setCurrentUser(null);
    setActiveNavId("dashboard");
    navigate("/");
  };

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
            activeNavId={activeNavId}
            onSelectNav={handleNavSelect}
          >
            <TeacherAttendanceFlow
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onSelectNav={handleNavSelect}
            />
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
            activeNavId={activeNavId}
            onSelectNav={handleNavSelect}
          >
            <SessionDetails
              sessionId={sessionId}
              user={currentUser}
              onNavigate={navigate}
            />
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
            activeNavId={activeNavId}
            onSelectNav={handleNavSelect}
          >
            <StudentDashboard
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onSelectNav={handleNavSelect}
            />
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
            activeNavId={activeNavId}
            onSelectNav={handleNavSelect}
            navBadges={{ approvals: pendingApprovals }}
          >
            <AdminDashboard
              user={currentUser}
              onLogout={handleLogout}
              onNavigate={navigate}
              activeNavId={activeNavId}
              onPendingCountChange={setPendingApprovals}
            />
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
