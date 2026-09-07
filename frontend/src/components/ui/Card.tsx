import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hoverable?: boolean;
}

export function Card({ children, hoverable, className = "", ...props }: CardProps) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-card)] ${
        hoverable ? "transition-shadow duration-200 hover:shadow-[var(--shadow-card-hover)]" : ""
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
