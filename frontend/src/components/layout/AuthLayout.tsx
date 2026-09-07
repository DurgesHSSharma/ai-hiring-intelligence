import { Logo } from "@/components/ui/Logo";
import { BarChart3, MessageSquareText, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";

const HIGHLIGHTS = [
  { icon: Users, text: "Rank every applicant against the role in seconds" },
  { icon: MessageSquareText, text: "Generate grounded interview questions per resume" },
  { icon: BarChart3, text: "See attrition risk and hiring funnels at a glance" },
];

export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-ink-950 px-12 py-10 lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -left-24 -top-24 h-80 w-80 rounded-full bg-brand-700/40 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 right-0 h-96 w-96 rounded-full bg-brand-500/20 blur-3xl" />

        <Logo className="relative [&_span:last-child]:text-white" />

        <div className="relative flex flex-col gap-8">
          <div>
            <span className="mb-4 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-brand-200">
              <Sparkles size={13} /> AI-Powered Hiring Platform
            </span>
            <h1 className="text-4xl font-bold leading-tight text-white">
              Smarter Hiring,
              <br />
              Stronger Teams
            </h1>
            <p className="mt-3 max-w-sm text-sm text-ink-300">
              Screen, rank, and understand candidates with AI. Make data-driven hiring decisions — faster and better.
            </p>
          </div>

          <ul className="flex flex-col gap-4">
            {HIGHLIGHTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-sm text-ink-300">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10 text-brand-300">
                  <Icon size={17} />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-ink-500">© {new Date().getFullYear()} HireIntel</p>
      </div>

      <div className="flex flex-col justify-center px-6 py-12 sm:px-12 lg:px-16 xl:px-24">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h2 className="text-2xl font-bold text-ink-900">{title}</h2>
          <p className="mt-1 text-sm text-ink-500">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </div>
    </div>
  );
}
