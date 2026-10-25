import React, { useCallback, useEffect, useState } from "react";
import { api } from "../services";
import type { UserResponse } from "../types";
import "./admin-dashboard.css";
import { AdminsTab } from "../components/admin/AdminsTab";
import { ApprovalsTab } from "../components/admin/ApprovalsTab";
import { ClassesTab } from "../components/admin/ClassesTab";
import { OverviewTab } from "../components/admin/OverviewTab";
import { ProfileTab } from "../components/admin/ProfileTab";
import { ReportsTab } from "../components/admin/ReportsTab";
import { SessionsTab } from "../components/admin/SessionsTab";
import { StudentsTab } from "../components/admin/StudentsTab";
import { SubjectsTab } from "../components/admin/SubjectsTab";
import { AcademicSetupTab } from "../components/admin/AcademicSetupTab";
import { TeachersTab } from "../components/admin/TeachersTab";
import { StudentRegistryTab } from "../components/admin/StudentRegistryTab";
import { SectionOverview } from "../components/admin/SectionOverview";
import { TeacherRegistryTab } from "../components/admin/TeacherRegistryTab";
import { useOrgNavigator } from "../hooks/useOrgNavigator.ts";
import { errorText, type AdminData, type Banner } from "../components/admin/adminShared.ts";

interface Props {
  user: UserResponse;
  onLogout: () => void;
  onNavigate?: (path: string) => void;
  activeNavId?: string;
  onPendingCountChange?: (total: number) => void;
  onSelectNav?: (navId: string) => void;
}

const EMPTY_DATA: AdminData = { students: [], teachers: [], academic: null, sessions: [] };

// Owns the data every tab shares and the banner; each tab is its own component.
export const AdminDashboard: React.FC<Props> = ({
  user,
  onNavigate,
  activeNavId: _activeNavId = "dashboard",
  onPendingCountChange,
  onSelectNav,
}) => {
  const [activeTab, setActiveTab] = useState<string>(_activeNavId || "dashboard");

  useEffect(() => {
    if (_activeNavId) {
      setActiveTab(_activeNavId);
    }
  }, [_activeNavId]);

  // Keep the "Pending Approvals" badge current while the admin panel is open.
  useEffect(() => {
    if (!onPendingCountChange) return;
    let cancelled = false;
    const refresh = () => {
      api
        .getPendingApprovalCounts()
        .then((counts) => {
          if (!cancelled) onPendingCountChange(counts.total);
        })
        .catch(() => {
          /* the badge simply keeps its last value */
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onPendingCountChange]);

  const [data, setData] = useState<AdminData>(EMPTY_DATA);
  const [loading, setLoading] = useState<boolean>(true);
  const [banner, setBanner] = useState<Banner | null>(null);

  const loadAllData = useCallback(async () => {
    setLoading(true);
    try {
      const [students, teachers, academic, sessions] = await Promise.all([
        api.getAdminStudents(),
        api.getAdminTeachers(),
        api.getAcademicStructure(),
        api.getAdminSessions(),
      ]);
      setData({ students, teachers, academic, sessions });
    } catch (err: unknown) {
      setBanner({ type: "error", text: `Failed to load admin data: ${errorText(err)}` });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAllData();
  }, [loadAllData]);

  const tabProps = { ...data, notify: setBanner, reload: loadAllData };
  // Year > Branch > Section. Without the pilot structure (a development
  // database) the older flat screens are shown instead.
  const org = useOrgNavigator();
  const [legacyAcademic, setLegacyAcademic] = useState<"classes" | "subjects" | "pilot">("classes");
  const navigatorProps = { years: org.years, selection: org.selection, onSelect: org.setSelection, notify: setBanner };

  return (
    <div className="erp-admin-container">
      {loading && (
        <div style={{ marginBottom: "1rem", fontSize: "0.8125rem", color: "var(--erp-primary)", fontWeight: 600 }}>
          Syncing institutional records...
        </div>
      )}
      {banner && (
        <div className={`alert-banner ${banner.type}`} style={{ marginBottom: "1.5rem" }}>
          <span>{banner.text}</span>
          <button
            onClick={() => setBanner(null)}
            style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontWeight: 700 }}
          >
            ✕
          </button>
        </div>
      )}

      {activeTab === "approvals" && (
        <ApprovalsTab
          classCodes={(data.academic?.classes || []).map((c) => c.class_code)}
          branches={data.academic?.branches || []}
          onCountChange={onPendingCountChange}
          years={org.years}
          selection={org.selection}
          onSelect={org.setSelection}
        />
      )}
      {activeTab === "dashboard" && (
        <>
          {org.pilot && <SectionOverview years={org.years} />}
          <OverviewTab {...data} />
        </>
      )}
      {activeTab === "students" &&
        (org.pilot ? (
          <StudentRegistryTab {...navigatorProps} onOpenApprovals={() => (onSelectNav ? onSelectNav("approvals") : setActiveTab("approvals"))} />
        ) : (
          <StudentsTab {...tabProps} />
        ))}
      {activeTab === "teachers" && (org.pilot ? <TeacherRegistryTab {...navigatorProps} /> : <TeachersTab {...tabProps} />)}
      {activeTab === "academic" &&
        (org.pilot || !org.loaded ? (
          <AcademicSetupTab notify={setBanner} />
        ) : (
          <div>
            <div role="tablist" aria-label="Academic" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
              {(
                [
                  ["classes", "Classes"],
                  ["subjects", "Subjects"],
                  ["pilot", "Pilot structure"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={legacyAcademic === id}
                  className={`erp-btn ${legacyAcademic === id ? "erp-btn-primary" : "erp-btn-secondary"}`}
                  onClick={() => setLegacyAcademic(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {legacyAcademic === "classes" && <ClassesTab {...tabProps} />}
            {legacyAcademic === "subjects" && <SubjectsTab {...tabProps} />}
            {legacyAcademic === "pilot" && <AcademicSetupTab notify={setBanner} />}
          </div>
        ))}
      {activeTab === "sessions" && <SessionsTab {...tabProps} />}
      {activeTab === "reports" && <ReportsTab />}
      {activeTab === "admins" && <AdminsTab user={user} notify={setBanner} />}
      {activeTab === "profile" && (
        <ProfileTab
          user={user}
          onChangePassword={onNavigate ? () => onNavigate("/account/password") : undefined}
        />
      )}
    </div>
  );
};
