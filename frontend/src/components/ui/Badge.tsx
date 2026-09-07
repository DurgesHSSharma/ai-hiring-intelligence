import type { ApplicationStatus, RiskLevel, ScoreBand } from "@/types";
import type { ReactNode } from "react";

type Tone = "success" | "warning" | "danger" | "info" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  success: "bg-success-bg text-success",
  warning: "bg-warning-bg text-warning",
  danger: "bg-danger-bg text-danger",
  info: "bg-info-bg text-info",
  neutral: "bg-canvas text-ink-500",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${TONE_CLASSES[tone]}`}>
      {children}
    </span>
  );
}

const SCORE_BAND_LABEL: Record<ScoreBand, { label: string; tone: Tone }> = {
  strong_match: { label: "Strong Hire", tone: "success" },
  good_match: { label: "Good Match", tone: "success" },
  moderate_match: { label: "Consider", tone: "warning" },
  weak_match: { label: "Weak Match", tone: "danger" },
};

export function ScoreBandBadge({ band }: { band: ScoreBand }) {
  const { label, tone } = SCORE_BAND_LABEL[band];
  return <Badge tone={tone}>{label}</Badge>;
}

const RISK_LEVEL_LABEL: Record<RiskLevel, { label: string; tone: Tone }> = {
  low: { label: "Low Risk", tone: "success" },
  medium: { label: "Medium Risk", tone: "warning" },
  high: { label: "High Risk", tone: "danger" },
};

export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  const { label, tone } = RISK_LEVEL_LABEL[level];
  return <Badge tone={tone}>{label}</Badge>;
}

const APPLICATION_STATUS_LABEL: Record<ApplicationStatus, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "info" },
  shortlisted: { label: "Shortlisted", tone: "info" },
  interviewed: { label: "Interviewed", tone: "warning" },
  selected: { label: "Selected", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
};

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  const { label, tone } = APPLICATION_STATUS_LABEL[status];
  return <Badge tone={tone}>{label}</Badge>;
}
