import {
  BarChart3,
  Briefcase,
  LayoutDashboard,
  MessageSquareText,
  Settings,
  TrendingDown,
  Upload,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", to: "/app", icon: LayoutDashboard },
  { label: "Jobs", to: "/app/jobs", icon: Briefcase },
  { label: "Upload Resumes", to: "/app/upload", icon: Upload },
  { label: "Candidates", to: "/app/candidates", icon: Users },
  { label: "Interview Questions", to: "/app/interview-questions", icon: MessageSquareText },
  { label: "Attrition Prediction", to: "/app/attrition", icon: TrendingDown },
  { label: "Analytics", to: "/app/analytics", icon: BarChart3 },
  { label: "Settings", to: "/app/settings", icon: Settings },
];
