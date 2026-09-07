import { AppLayout } from "@/components/layout/AppLayout";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { Spinner } from "@/components/ui/AsyncState";
import LandingPage from "@/pages/LandingPage";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const JobsPage = lazy(() => import("@/pages/JobsPage"));
const UploadResumesPage = lazy(() => import("@/pages/UploadResumesPage"));
const CandidatesPage = lazy(() => import("@/pages/CandidatesPage"));
const CandidateDetailPage = lazy(() => import("@/pages/CandidateDetailPage"));
const ComparePage = lazy(() => import("@/pages/ComparePage"));
const InterviewQuestionsPage = lazy(() => import("@/pages/InterviewQuestionsPage"));
const AttritionPage = lazy(() => import("@/pages/AttritionPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

function LazyPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route element={<ProtectedRoute />}>
        <Route path="/app" element={<AppLayout />}>
          <Route index element={<LazyPage><DashboardPage /></LazyPage>} />
          <Route path="jobs" element={<LazyPage><JobsPage /></LazyPage>} />
          <Route path="upload" element={<LazyPage><UploadResumesPage /></LazyPage>} />
          <Route path="candidates" element={<LazyPage><CandidatesPage /></LazyPage>} />
          <Route path="candidates/:candidateId" element={<LazyPage><CandidateDetailPage /></LazyPage>} />
          <Route path="jobs/:jobId/compare" element={<LazyPage><ComparePage /></LazyPage>} />
          <Route path="interview-questions" element={<LazyPage><InterviewQuestionsPage /></LazyPage>} />
          <Route path="attrition" element={<LazyPage><AttritionPage /></LazyPage>} />
          <Route path="analytics" element={<LazyPage><AnalyticsPage /></LazyPage>} />
          <Route path="settings" element={<LazyPage><SettingsPage /></LazyPage>} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
