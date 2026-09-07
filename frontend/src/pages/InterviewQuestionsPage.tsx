import { EmptyState, ErrorState, Spinner } from "@/components/ui/AsyncState";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { candidateService } from "@/services/candidateService";
import { interviewService } from "@/services/interviewService";
import { jobService } from "@/services/jobService";
import type { InterviewQuestionsResponse, QuestionCategory, QuestionDifficulty } from "@/types";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

const DIFFICULTY_TONE: Record<QuestionDifficulty, "success" | "warning" | "danger"> = {
  easy: "success",
  medium: "warning",
  hard: "danger",
};

const CATEGORY_LABEL: Record<QuestionCategory, string> = {
  technical: "Technical",
  project: "Project",
  experience: "Experience",
  skill_verification: "Skill Verification",
  behavioral: "Behavioral",
};

export default function InterviewQuestionsPage() {
  const [jobId, setJobId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [count, setCount] = useState(8);
  const [activeCategory, setActiveCategory] = useState<QuestionCategory | "all">("all");
  const [result, setResult] = useState<InterviewQuestionsResponse | null>(null);

  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: () => jobService.list({ status: "all", page_size: 100 }) });
  const candidatesQuery = useQuery({
    queryKey: ["candidates", { jobId }],
    queryFn: () => candidateService.list({ job_id: Number(jobId), page_size: 100 }),
    enabled: Boolean(jobId),
  });

  const generateMutation = useMutation({
    mutationFn: () => interviewService.generate(Number(candidateId), Number(jobId), { count, regenerate: true }),
    onSuccess: (data) => {
      setResult(data);
      setActiveCategory("all");
    },
  });

  const categoryCounts = useMemo(() => {
    const counts = new Map<QuestionCategory, number>();
    for (const q of result?.questions ?? []) counts.set(q.category, (counts.get(q.category) ?? 0) + 1);
    return counts;
  }, [result]);

  const visibleQuestions = result?.questions.filter((q) => activeCategory === "all" || q.category === activeCategory) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Generate Interview Questions</h1>
        <p className="mt-1 text-sm text-ink-500">Create customized questions based on candidate profile and job description.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.5fr]">
        <Card className="flex flex-col gap-4">
          <Select label="Job" value={jobId} onChange={(e) => {
            setJobId(e.target.value);
            setCandidateId("");
          }}>
            <option value="">Select a job…</option>
            {jobsQuery.data?.items.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title}
              </option>
            ))}
          </Select>

          <Select label="Select Candidate" value={candidateId} onChange={(e) => setCandidateId(e.target.value)} disabled={!jobId}>
            <option value="">{jobId ? "Choose a candidate…" : "Select a job first"}</option>
            {candidatesQuery.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name ?? `Candidate #${c.id}`}
                {c.fit_score !== null ? ` (${c.fit_score.toFixed(0)}% match)` : ""}
              </option>
            ))}
          </Select>

          <Select label="Number of Questions" value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[5, 6, 7, 8].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>

          <Button
            disabled={!jobId || !candidateId}
            isLoading={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            <Sparkles size={16} /> Generate Questions
          </Button>
          {generateMutation.isError && <p className="text-sm text-danger">Couldn't generate questions. Please try again.</p>}
        </Card>

        <Card>
          {!result && !generateMutation.isPending && (
            <EmptyState title="No questions yet" description="Pick a job and candidate, then generate grounded interview questions." />
          )}
          {generateMutation.isPending && <Spinner label="Generating grounded questions..." />}

          {result && (
            <div className="flex flex-col gap-4">
              {result.partial && (
                <p className="rounded-lg bg-warning-bg px-3 py-2 text-sm text-warning">
                  Only {result.grounded} of {result.requested} requested questions could be grounded in this resume.
                </p>
              )}

              <div className="flex flex-wrap gap-2 border-b border-border pb-3">
                <button
                  onClick={() => setActiveCategory("all")}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors duration-150 ${
                    activeCategory === "all" ? "bg-brand-600 text-white" : "bg-canvas text-ink-500"
                  }`}
                >
                  All ({result.questions.length})
                </button>
                {[...categoryCounts.entries()].map(([category, n]) => (
                  <button
                    key={category}
                    onClick={() => setActiveCategory(category)}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors duration-150 ${
                      activeCategory === category ? "bg-brand-600 text-white" : "bg-canvas text-ink-500"
                    }`}
                  >
                    {CATEGORY_LABEL[category]} ({n})
                  </button>
                ))}
              </div>

              {visibleQuestions.length === 0 && <ErrorState message="No questions in this category." />}

              <ol className="flex flex-col gap-3">
                {visibleQuestions.map((q, index) => (
                  <li key={q.id} className="rounded-lg border border-border p-3">
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="text-xs font-semibold text-ink-300">{index + 1}</span>
                      <Badge tone={DIFFICULTY_TONE[q.difficulty]}>{q.difficulty}</Badge>
                    </div>
                    <p className="text-sm text-ink-900">{q.question}</p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
