import { EmptyState, ErrorState, Spinner } from "@/components/ui/AsyncState";
import { ScoreBandBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { candidateService } from "@/services/candidateService";
import { exportService } from "@/services/exportService";
import { jobService } from "@/services/jobService";
import { scoringService } from "@/services/scoringService";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, GitCompareArrows, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

const MIN_COMPARE = 2;
const MAX_COMPARE = 4;

function scoreBandFromValue(score: number | null): "strong_match" | "good_match" | "moderate_match" | "weak_match" | null {
  if (score === null) return null;
  if (score >= 85) return "strong_match";
  if (score >= 70) return "good_match";
  if (score >= 55) return "moderate_match";
  return "weak_match";
}

export default function CandidatesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get("jobId");
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  function toggleSelected(candidateId: number) {
    setSelectedIds((prev) =>
      prev.includes(candidateId)
        ? prev.filter((id) => id !== candidateId)
        : prev.length < MAX_COMPARE
          ? [...prev, candidateId]
          : prev,
    );
  }

  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: () => jobService.list({ status: "all", page_size: 100 }) });

  const candidatesQuery = useQuery({
    queryKey: ["candidates", { jobId, search }],
    queryFn: () =>
      candidateService.list({
        job_id: jobId ? Number(jobId) : undefined,
        search: search || undefined,
        sort_by: "fit_score",
        sort_order: "desc",
        page_size: 50,
      }),
  });

  const scoreMutation = useMutation({
    mutationFn: () => scoringService.scoreJob(Number(jobId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["candidates"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink-900">Candidates</h1>
          <p className="mt-1 text-sm text-ink-500">AI-ranked candidates based on job description match.</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-300" />
            <Input
              placeholder="Search candidates..."
              className="pl-9 sm:w-56"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Select
            value={jobId ?? ""}
            onChange={(e) => setSearchParams(e.target.value ? { jobId: e.target.value } : {})}
            className="sm:w-52"
          >
            <option value="">All jobs</option>
            {jobsQuery.data?.items.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title}
              </option>
            ))}
          </Select>
          {jobId && (
            <>
              <Button variant="secondary" isLoading={scoreMutation.isPending} onClick={() => scoreMutation.mutate()}>
                <Sparkles size={16} /> Score Candidates
              </Button>
              <Button variant="outline" onClick={() => exportService.downloadCandidatesCsv(Number(jobId), { search: search || undefined })}>
                <Download size={16} /> Export CSV
              </Button>
              <Button
                variant="outline"
                disabled={selectedIds.length < MIN_COMPARE}
                onClick={() => navigate(`/app/jobs/${jobId}/compare?candidateIds=${selectedIds.join(",")}`)}
              >
                <GitCompareArrows size={16} /> Compare{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
              </Button>
            </>
          )}
        </div>
      </div>

      {jobId && selectedIds.length > 0 && (
        <p className="text-xs text-ink-300">
          {selectedIds.length}/{MAX_COMPARE} selected for comparison (min {MIN_COMPARE}) — only candidates already scored for
          this job can be compared.
        </p>
      )}

      {scoreMutation.isSuccess && (
        <p className="rounded-lg bg-success-bg px-3 py-2 text-sm text-success">
          Scored {scoreMutation.data.scored} candidate{scoreMutation.data.scored === 1 ? "" : "s"}
          {scoreMutation.data.skipped > 0 ? ` · ${scoreMutation.data.skipped} skipped` : ""}.
        </p>
      )}
      {scoreMutation.isError && <p className="text-sm text-danger">Couldn't score candidates for this job.</p>}

      {candidatesQuery.isLoading && <Spinner />}
      {candidatesQuery.isError && <ErrorState message="Couldn't load candidates. Please try again." />}
      {candidatesQuery.data && candidatesQuery.data.items.length === 0 && (
        <EmptyState title="No candidates found" description="Upload resumes against a job to see ranked candidates here." />
      )}

      {candidatesQuery.data && candidatesQuery.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border bg-surface">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-canvas text-ink-500">
              <tr>
                {jobId && <th className="w-10 px-4 py-3" />}
                <th className="px-4 py-3 font-medium">#</th>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Match Score</th>
                <th className="px-4 py-3 font-medium">Experience</th>
                <th className="px-4 py-3 font-medium">Recommendation</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {candidatesQuery.data.items.map((candidate, index) => {
                const band = scoreBandFromValue(candidate.fit_score);
                return (
                  <tr key={candidate.id} className="border-t border-border transition-colors duration-150 hover:bg-canvas">
                    {jobId && (
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(candidate.id)}
                          disabled={candidate.fit_score === null || (!selectedIds.includes(candidate.id) && selectedIds.length >= MAX_COMPARE)}
                          onChange={() => toggleSelected(candidate.id)}
                          className="h-4 w-4 rounded border-border-strong text-brand-600 focus:ring-brand-200"
                          aria-label={`Select ${candidate.name ?? "candidate"} for comparison`}
                        />
                      </td>
                    )}
                    <td className="px-4 py-3 text-ink-300">{index + 1}</td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-ink-900">{candidate.name ?? "Unknown"}</p>
                      <p className="text-xs text-ink-300">{candidate.email ?? "No email extracted"}</p>
                    </td>
                    <td className="px-4 py-3 font-semibold text-ink-900">
                      {candidate.fit_score !== null ? `${candidate.fit_score.toFixed(1)}%` : "—"}
                    </td>
                    <td className="px-4 py-3 text-ink-700">
                      {candidate.experience_years !== null ? `${candidate.experience_years} yrs` : "—"}
                    </td>
                    <td className="px-4 py-3">{band ? <ScoreBandBadge band={band} /> : <span className="text-ink-300">Not scored</span>}</td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/app/candidates/${candidate.id}${jobId ? `?jobId=${jobId}` : ""}`}
                        className="font-semibold text-brand-600 hover:text-brand-700"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
