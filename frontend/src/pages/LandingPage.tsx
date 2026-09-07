import { Logo } from "@/components/ui/Logo";
import { useAuth } from "@/hooks/useAuth";
import {
  BarChart3,
  FileSearch,
  MessageSquareText,
  PlayCircle,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";
import { Link, Navigate } from "react-router-dom";

const NAV_LINKS = ["Product", "Features", "How it Works", "Pricing"];

const FEATURES: { icon: LucideIcon; label: string }[] = [
  { icon: FileSearch, label: "Resume Screening in seconds" },
  { icon: MessageSquareText, label: "AI Interview Questions" },
  { icon: BarChart3, label: "Skill Gap Analysis" },
  { icon: TrendingDown, label: "Attrition Prediction" },
];

const SAMPLE_MATCHES = [
  { name: "Rahul Verma", score: 92 },
  { name: "Priya Singh", score: 87 },
  { name: "Aman Kumar", score: 76 },
  { name: "Sneha Mehta", score: 68 },
];

export default function LandingPage() {
  const { user, isLoading } = useAuth();
  if (!isLoading && user) return <Navigate to="/app" replace />;

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <Logo />
          <nav className="hidden items-center gap-8 md:flex">
            {NAV_LINKS.map((link) => (
              <span key={link} className="text-sm font-medium text-ink-500 hover:text-ink-900">
                {link}
              </span>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <Link to="/login" className="rounded-[var(--radius-control)] px-4 py-2 text-sm font-semibold text-ink-700 hover:bg-canvas">
              Login
            </Link>
            <Link
              to="/register"
              className="rounded-[var(--radius-control)] bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors duration-150 hover:bg-brand-700"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden bg-ink-950">
        <div className="pointer-events-none absolute -left-32 top-0 h-96 w-96 rounded-full bg-brand-700/40 blur-3xl" />
        <div className="pointer-events-none absolute -right-24 top-1/3 h-80 w-80 rounded-full bg-brand-500/20 blur-3xl" />

        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-6 py-20 lg:grid-cols-2 lg:py-28">
          <div>
            <span className="mb-5 inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-brand-200">
              AI-Powered Hiring Platform
            </span>
            <h1 className="text-4xl font-bold leading-[1.1] text-white sm:text-5xl">
              Smarter Hiring
              <br />
              Stronger <span className="text-brand-400">Teams</span>
            </h1>
            <p className="mt-5 max-w-md text-base text-ink-300">
              Use the power of AI to screen, rank, and understand candidates. Make data-driven hiring decisions —
              faster and better.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link
                to="/register"
                className="rounded-[var(--radius-control)] bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition-colors duration-150 hover:bg-brand-700"
              >
                Get Started
              </Link>
              <button className="flex items-center gap-2 rounded-[var(--radius-control)] border border-white/20 px-6 py-3 text-sm font-semibold text-white transition-colors duration-150 hover:bg-white/10">
                <PlayCircle size={17} /> Watch Demo
              </button>
            </div>
          </div>

          <div className="flex justify-center lg:justify-end">
            <div className="w-full max-w-xs rounded-2xl border border-white/10 bg-ink-900 p-5 shadow-2xl">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-300">Candidate Match</p>
              <div className="mt-3 flex items-center gap-4">
                <div className="relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-4 border-success">
                  <span className="text-lg font-bold text-white">92%</span>
                </div>
                <div>
                  <p className="text-sm font-semibold text-white">Great Match!</p>
                  <p className="text-xs text-ink-300">Rahul Verma</p>
                </div>
              </div>
              <ul className="mt-4 flex flex-col gap-2.5 border-t border-white/10 pt-4">
                {SAMPLE_MATCHES.map((c) => (
                  <li key={c.name} className="flex items-center justify-between text-sm">
                    <span className="text-ink-300">{c.name}</span>
                    <span className="font-semibold text-white">{c.score}%</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section className="border-b border-border bg-surface">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-6 py-10 sm:grid-cols-4">
          {FEATURES.map(({ icon: Icon, label }) => (
            <div key={label} className="flex flex-col items-center gap-2 text-center sm:flex-row sm:text-left">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Icon size={19} />
              </span>
              <span className="text-sm font-medium text-ink-700">{label}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
