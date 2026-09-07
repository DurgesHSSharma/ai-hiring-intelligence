import { Card } from "@/components/ui/Card";
import { ErrorState, Spinner } from "@/components/ui/AsyncState";
import { analyticsService } from "@/services/analyticsService";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function AnalyticsPage() {
  const scoresQuery = useQuery({ queryKey: ["analytics", "scores"], queryFn: () => analyticsService.scores() });
  const skillsQuery = useQuery({ queryKey: ["analytics", "skills"], queryFn: () => analyticsService.skills() });

  if (scoresQuery.isLoading || skillsQuery.isLoading) return <Spinner label="Loading analytics..." />;
  if (scoresQuery.isError || skillsQuery.isError) return <ErrorState message="Couldn't load analytics." />;

  const scores = scoresQuery.data!;
  const skills = skillsQuery.data!;

  const distributionData = scores.distribution.map((bucket) => ({
    range: `${bucket.range_start}-${bucket.range_end}`,
    count: bucket.count,
  }));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Analytics</h1>
        <p className="mt-1 text-sm text-ink-500">Score distribution and skill trends across every job.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <p className="text-sm text-ink-500">Overall Average Fit Score</p>
          <p className="mt-2 text-3xl font-bold text-ink-900">
            {scores.overall_average_fit_score !== null ? scores.overall_average_fit_score.toFixed(1) : "—"}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-ink-500">Jobs With Scores</p>
          <p className="mt-2 text-3xl font-bold text-ink-900">{scores.average_by_job.length}</p>
        </Card>
        <Card>
          <p className="text-sm text-ink-500">Top Missing Skill</p>
          <p className="mt-2 text-2xl font-bold text-ink-900">{skills.top_missing_skills[0]?.skill_name ?? "—"}</p>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Fit Score Distribution</p>
          {distributionData.length === 0 ? (
            <p className="py-12 text-center text-sm text-ink-300">No scored candidates yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={distributionData}>
                <XAxis dataKey="range" tick={{ fontSize: 11, fill: "#8b87ab" }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "#8b87ab" }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "#f4f3ff" }} contentStyle={{ borderRadius: 10, border: "1px solid #e7e5f0" }} />
                <Bar dataKey="count" fill="#9d8bf7" radius={[6, 6, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Average Fit Score by Job</p>
          {scores.average_by_job.length === 0 ? (
            <p className="py-12 text-center text-sm text-ink-300">No scored jobs yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {scores.average_by_job.map((job) => (
                <li key={job.job_id}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="text-ink-700">{job.job_title}</span>
                    <span className="font-semibold text-ink-900">{job.average_fit_score.toFixed(1)}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-canvas">
                    <div className="h-full rounded-full bg-brand-600" style={{ width: `${job.average_fit_score}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Most Common Candidate Skills</p>
          <ul className="flex flex-col gap-2">
            {skills.top_candidate_skills.slice(0, 8).map((s) => (
              <li key={s.skill_name} className="flex items-center justify-between text-sm">
                <span className="text-ink-700">{s.skill_name}</span>
                <span className="font-medium text-ink-500">{s.count}</span>
              </li>
            ))}
            {skills.top_candidate_skills.length === 0 && <p className="text-sm text-ink-300">No skill data yet.</p>}
          </ul>
        </Card>

        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Most Common Missing Skills</p>
          <ul className="flex flex-col gap-2">
            {skills.top_missing_skills.slice(0, 8).map((s) => (
              <li key={s.skill_name} className="flex items-center justify-between text-sm">
                <span className="text-ink-700">{s.skill_name}</span>
                <span className="font-medium text-ink-500">{s.count}</span>
              </li>
            ))}
            {skills.top_missing_skills.length === 0 && <p className="text-sm text-ink-300">No skill gap data yet.</p>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
