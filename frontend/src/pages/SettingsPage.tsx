import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useAuth } from "@/hooks/useAuth";
import { LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Settings</h1>
        <p className="mt-1 text-sm text-ink-500">Your account details.</p>
      </div>

      <Card className="max-w-md">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-100 text-lg font-bold text-brand-700">
            {(user?.name ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <div>
            <p className="font-semibold text-ink-900">{user?.name}</p>
            <p className="text-sm text-ink-500">{user?.email}</p>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
          <span className="text-sm text-ink-500">Role</span>
          <Badge tone="info">{user?.role}</Badge>
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
          <span className="text-sm text-ink-500">Member since</span>
          <span className="text-sm text-ink-700">{user ? new Date(user.created_at).toLocaleDateString() : "—"}</span>
        </div>
        <Button
          variant="outline"
          className="mt-6 w-full"
          onClick={() => {
            logout();
            navigate("/login");
          }}
        >
          <LogOut size={16} /> Log out
        </Button>
      </Card>
    </div>
  );
}
