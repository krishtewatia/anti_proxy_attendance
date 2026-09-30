import React, { useEffect } from "react";
import { auth } from "../../services";
import type { UserResponse, UserRole } from "../../types";
import { getDashboardPath } from "../../utils/auth";

interface ProtectedRouteProps {
  allowedRoles?: UserRole[];
  currentUser?: UserResponse | null;
  onNavigate: (path: string) => void;
  children: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  allowedRoles,
  currentUser,
  onNavigate,
  children,
}) => {
  const activeUser = currentUser ?? auth.getStoredUser();
  const authenticated = auth.isAuthenticated() && Boolean(activeUser);

  useEffect(() => {
    // 1. Not authenticated -> Redirect to root / AuthPage
    if (!authenticated || !activeUser) {
      onNavigate("/");
      return;
    }

    // 2. Authenticated, but role is not allowed -> Redirect to user's own dashboard
    if (
      allowedRoles &&
      allowedRoles.length > 0 &&
      !allowedRoles.includes(activeUser.role)
    ) {
      const ownDashboard = getDashboardPath(activeUser.role);
      onNavigate(ownDashboard);
    }
  }, [authenticated, activeUser, allowedRoles, onNavigate]);

  // Prevent flash of unauthorized content
  if (!authenticated || !activeUser) {
    return null;
  }

  if (
    allowedRoles &&
    allowedRoles.length > 0 &&
    !allowedRoles.includes(activeUser.role)
  ) {
    return null;
  }

  return <>{children}</>;
};
