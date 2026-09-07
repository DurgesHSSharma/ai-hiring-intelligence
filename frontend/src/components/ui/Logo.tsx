import { BarChart3 } from "lucide-react";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
        <BarChart3 size={18} strokeWidth={2.5} />
      </span>
      <span className="text-lg font-bold tracking-tight text-ink-900">HireIntel</span>
    </div>
  );
}
