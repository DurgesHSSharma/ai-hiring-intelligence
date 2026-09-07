import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Spinner({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-ink-300">
      <Loader2 size={28} className="animate-spin text-brand-500" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-danger-bg bg-danger-bg/40 py-16 text-center">
      <AlertCircle size={28} className="text-danger" />
      <p className="max-w-sm text-sm text-ink-700">{message}</p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-dashed border-border-strong py-16 text-center">
      <Inbox size={28} className="text-ink-300" />
      <div>
        <p className="text-sm font-medium text-ink-700">{title}</p>
        {description && <p className="mt-1 max-w-sm text-sm text-ink-300">{description}</p>}
      </div>
      {action}
    </div>
  );
}
