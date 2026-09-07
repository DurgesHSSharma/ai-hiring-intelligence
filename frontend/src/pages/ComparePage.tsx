import { ErrorState, Spinner } from "@/components/ui/AsyncState";
import { ApiError } from "@/services/apiClient";
import { scoringService } from "@/services/scoringService";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Minus } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

export default function ComparePage() {
  const { jobId: jobIdParam } = useParams();
  const jobId = Number(jobIdParam);
  const [searchParams] = useSearchParams();
  const candidateIds = (searchParams.get("candidateIds") ?? "")
    .split(",")
    .map(Number)
    .filter((n) => !Number.isNaN(n));

  const compareQuery = useQuery({
    queryKey: ["compare", jobId, candidateIds],
    queryFn: () => scoringService.compare(jobId, candidateIds),
    enabled: candidateIds.length >= 2,
  });

  const backLink = `/app/candidates?jobId=${jobId}`;

  if (candidateIds.length < 2) {
    return <ErrorState message="Select at least 2 candidates from the Candidates page to compare them." />;
  }
  if (compareQuery.isLoading) return <Spinner label="Building comparison..." />;
  if (compareQuery.isError) {
    const message =
      compareQuery.error instanceof ApiError
        ? compareQuery.error.message
        : "Couldn't build the comparison. Please try again.";
    return <ErrorState message={message} />;
  }

  const data = compareQuery.data!;
  const candidatesById = new Map(data.candidates.map((c) => [c.candidate_id, c]));

  return (
    <div className="flex flex-col gap-6">
      <Link to={backLink} className="flex w-fit items-center gap-1.5 text-sm font-medium text-ink-500 hover:text-ink-900">
        <ArrowLeft size={15} /> Back to Candidates
      </Link>

      <div>
        <h1 className="text-2xl font-bold text-ink-900">Compare Candidates</h1>
        <p className="mt-1 text-sm text-ink-500">Side-by-side fit score and skill comparison for this job.</p>
      </div>

      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border bg-surface">
        <table className="w-full min-w-[600px] text-left text-sm">
          <thead className="bg-canvas text-ink-500">
            <tr>
              <th className="px-4 py-3 font-medium">Metric</th>
              {data.candidate_ids.map((id) => (
                <th key={id} className="px-4 py-3 font-medium text-ink-900">
                  {candidatesById.get(id)?.candidate_name ?? `Candidate #${id}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.matrix.map((row) => (
              <tr key={row.metric} className="border-t border-border">
                <td className="px-4 py-3 font-medium text-ink-700">{row.label}</td>
                {data.candidate_ids.map((id) => {
                  const value = row.values[id];
                  const isBest = row.best_candidate_id === id;
                  return (
                    <td key={id} className={`px-4 py-3 ${isBest ? "font-bold text-success" : "text-ink-900"}`}>
                      {value ?? "—"}
                      {isBest && value !== null && " ★"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.candidates.map((candidate) => (
          <div key={candidate.candidate_id} className="rounded-[var(--radius-card)] border border-border bg-surface p-5">
            <p className="mb-3 font-semibold text-ink-900">{candidate.candidate_name ?? `Candidate #${candidate.candidate_id}`}</p>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-300">Matched Skills</p>
            <ul className="mb-3 flex flex-col gap-1">
              {candidate.matched_skills.length === 0 && <li className="text-sm text-ink-300">None</li>}
              {candidate.matched_skills.map((s) => (
                <li key={s.skill} className="flex items-center gap-1.5 text-sm text-ink-700">
                  <Check size={13} className="text-success" /> {s.skill}
                </li>
              ))}
            </ul>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-300">Missing Skills</p>
            <ul className="flex flex-col gap-1">
              {candidate.missing_skills.length === 0 && <li className="text-sm text-ink-300">None</li>}
              {candidate.missing_skills.map((skill) => (
                <li key={skill} className="flex items-center gap-1.5 text-sm text-ink-700">
                  <Minus size={13} className="text-danger" /> {skill}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
