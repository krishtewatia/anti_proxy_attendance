import { useEffect, useState } from "react";
import { AuthPage } from "./pages/AuthPage";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppLayout } from "./components/layout/AppLayout";
import { TeacherDashboard } from "./pages/TeacherDashboard";
import { StudentDashboardPlaceholder } from "./pages/StudentDashboardPlaceholder";
import { AdminDashboardPlaceholder } from "./pages/AdminDashboardPlaceholder";
import { auth } from "./services";
import type { TokenResponse, UserResponse } from "./types";
import { getDashboardPath } from "./utils/auth";

export function App() {
  const [currentUser, setCurrentUser] = useState<UserResponse | null>(() =>
    auth.getStoredUser()
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
    const targetDashboard = getDashboardPath(response.user.role);
    navigate(targetDashboard);
  };

  const handleLogout = () => {
    auth.logout();
    setCurrentUser(null);
    navigate("/");
  };

  // Route 1: Teacher Dashboard
  if (currentPath === "/dashboard/teacher") {
    return (
      <ProtectedRoute
        allowedRoles={["TEACHER"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout user={currentUser} onLogout={handleLogout}>
            <TeacherDashboard
              user={currentUser}
              onLogout={handleLogout}
            />
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 2: Student Dashboard
  if (currentPath === "/dashboard/student") {
    return (
      <ProtectedRoute
        allowedRoles={["STUDENT"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout user={currentUser} onLogout={handleLogout}>
            <StudentDashboardPlaceholder
              user={currentUser}
              onLogout={handleLogout}
            />
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Route 3: Admin Dashboard
  if (currentPath === "/dashboard/admin") {
    return (
      <ProtectedRoute
        allowedRoles={["ADMIN"]}
        currentUser={currentUser}
        onNavigate={navigate}
      >
        {currentUser && (
          <AppLayout user={currentUser} onLogout={handleLogout}>
            <AdminDashboardPlaceholder
              user={currentUser}
              onLogout={handleLogout}
            />
          </AppLayout>
        )}
      </ProtectedRoute>
    );
  }

  // Fallback for any unknown route: if authenticated, redirect to role dashboard, else render AuthPage
  if (currentPath !== "/") {
    if (currentUser && auth.isAuthenticated()) {
      navigate(getDashboardPath(currentUser.role));
      return null;
    }
  }

  // Default route: / (AuthPage)
  return <AuthPage onLoginSuccess={handleLoginSuccess} />;
}

export default App;
