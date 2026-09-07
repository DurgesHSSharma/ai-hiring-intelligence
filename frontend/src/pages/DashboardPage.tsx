import { Card } from "@/components/ui/Card";
import { ErrorState, Spinner } from "@/components/ui/AsyncState";
import { useAuth } from "@/hooks/useAuth";
import { analyticsService } from "@/services/analyticsService";
import { useQuery } from "@tanstack/react-query";
import { FileStack, ThumbsUp, UserCheck, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart, Bar } from "recharts";

const CHART_COLORS = ["#6c4fe8", "#9d8bf7", "#16a34a", "#d97706", "#2563eb"];

function StatCard({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number }) {
  return (
    <Card className="flex items-start justify-between">
      <div>
        <p className="text-sm text-ink-500">{label}</p>
        <p className="mt-2 text-3xl font-bold text-ink-900">{value.toLocaleString()}</p>
      </div>
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
        <Icon size={19} />
      </span>
    </Card>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();

  const overviewQuery = useQuery({ queryKey: ["analytics", "overview"], queryFn: () => analyticsService.overview() });
  const skillsQuery = useQuery({ queryKey: ["analytics", "skills"], queryFn: () => analyticsService.skills() });

  if (overviewQuery.isLoading || skillsQuery.isLoading) return <Spinner label="Loading your dashboard..." />;
  if (overviewQuery.isError) return <ErrorState message="Couldn't load dashboard analytics. Please try again." />;

  const funnel = overviewQuery.data!.funnel;
  const funnelChartData = [
    { stage: "Applied", count: funnel.total },
    { stage: "Shortlisted", count: funnel.shortlisted },
    { stage: "Interviewed", count: funnel.interviewed },
    { stage: "Selected", count: funnel.selected },
    { stage: "Rejected", count: funnel.rejected },
  ];

  const topSkills = skillsQuery.data?.top_candidate_skills.slice(0, 5) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Welcome back, {user?.name?.split(" ")[0]}! 👋</h1>
        <p className="mt-1 text-sm text-ink-500">Here's what's happening with your hiring pipeline.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={FileStack} label="Total Applications" value={funnel.total} />
        <StatCard icon={Users} label="Shortlisted" value={funnel.shortlisted} />
        <StatCard icon={UserCheck} label="Interviewed" value={funnel.interviewed} />
        <StatCard icon={ThumbsUp} label="Selected" value={funnel.selected} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Hiring Funnel</p>
          {funnel.total === 0 ? (
            <p className="py-12 text-center text-sm text-ink-300">No applications yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={funnelChartData}>
                <XAxis dataKey="stage" tick={{ fontSize: 12, fill: "#8b87ab" }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "#8b87ab" }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "#f4f3ff" }} contentStyle={{ borderRadius: 10, border: "1px solid #e7e5f0" }} />
                <Bar dataKey="count" fill="#6c4fe8" radius={[6, 6, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Top Skills in Applicants</p>
          {topSkills.length === 0 ? (
            <p className="py-12 text-center text-sm text-ink-300">No skill data yet.</p>
          ) : (
            <div className="flex items-center gap-4">
              <ResponsiveContainer width="55%" height={220}>
                <PieChart>
                  <Pie data={topSkills} dataKey="count" nameKey="skill_name" innerRadius={55} outerRadius={85} paddingAngle={2}>
                    {topSkills.map((entry, index) => (
                      <Cell key={entry.skill_name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e7e5f0" }} />
                </PieChart>
              </ResponsiveContainer>
              <ul className="flex flex-1 flex-col gap-2.5">
                {topSkills.map((skill, index) => (
                  <li key={skill.skill_name} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 text-ink-700">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }}
                      />
                      {skill.skill_name}
                    </span>
                    <span className="font-medium text-ink-500">{skill.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
