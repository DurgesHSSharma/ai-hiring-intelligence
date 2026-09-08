import { EmptyState, ErrorState, Spinner } from "@/components/ui/AsyncState";
import { Badge, ScoreBandBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { ScoreRing } from "@/components/ui/ScoreRing";
import { ApiError } from "@/services/apiClient";
import { candidateService } from "@/services/candidateService";
import { interviewService } from "@/services/interviewService";
import { jobService } from "@/services/jobService";
import { scoringService } from "@/services/scoringService";
import type { QuestionDifficulty } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Info, Mail, MapPin, Phone, RefreshCcw, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

type Tab = "overview" | "skills" | "questions";

const DIFFICULTY_TONE: Record<QuestionDifficulty, "success" | "warning" | "danger"> = {
  easy: "success",
  medium: "warning",
  hard: "danger",
};

function SubScoreBar({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-ink-500">{label}</span>
        <span className="font-semibold text-ink-900">{value !== null ? value.toFixed(1) : "excluded"}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-canvas">
        <div
          className="h-full rounded-full bg-brand-600 transition-[width] duration-500 ease-out"
          style={{ width: `${value ?? 0}%` }}
        />
      </div>
    </div>
  );
}

function JobPicker({ onSelect }: { onSelect: (jobId: string) => void }) {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: () => jobService.list({ status: "all", page_size: 100 }) });
  return (
    <Card>
      <p className="mb-3 text-sm font-medium text-ink-700">
        Select a job to see this candidate's match score, skill gap, and interview questions.
      </p>
      <Select onChange={(e) => onSelect(e.target.value)} defaultValue="">
        <option value="" disabled>
          Choose a job…
        </option>
        {jobsQuery.data?.items.map((job) => (
          <option key={job.id} value={job.id}>
            {job.title}
          </option>
        ))}
      </Select>
    </Card>
  );
}

export default function CandidateDetailPage() {
  const { candidateId: candidateIdParam } = useParams();
  const candidateId = Number(candidateIdParam);
  const [searchParams, setSearchParams] = useSearchParams();
  const jobIdParam = searchParams.get("jobId");
  const jobId = jobIdParam ? Number(jobIdParam) : null;
  const [tab, setTab] = useState<Tab>("overview");
  const queryClient = useQueryClient();

  const candidateQuery = useQuery({
    queryKey: ["candidate", candidateId],
    queryFn: () => candidateService.get(candidateId),
  });

  const scoreQuery = useQuery({
    queryKey: ["candidateScore", candidateId, jobId],
    queryFn: () => scoringService.candidateScore(candidateId, jobId!),
    enabled: jobId !== null,
  });

  const skillGapQuery = useQuery({
    queryKey: ["skillGap", candidateId, jobId],
    queryFn: () => scoringService.skillGap(candidateId, jobId!),
    enabled: jobId !== null,
  });

  const questionsQuery = useQuery({
    queryKey: ["interviewQuestions", candidateId, jobId],
    queryFn: () => interviewService.get(candidateId, jobId!),
    enabled: jobId !== null && tab === "questions",
    retry: false,
  });

  const generateMutation = useMutation({
    mutationFn: (regenerate: boolean) => interviewService.generate(candidateId, jobId!, { regenerate }),
    onSuccess: (data) => {
      queryClient.setQueryData(["interviewQuestions", candidateId, jobId], data);
    },
  });

  if (candidateQuery.isLoading) return <Spinner />;
  if (candidateQuery.isError || !candidateQuery.data) return <ErrorState message="Couldn't load this candidate." />;

  const candidate = candidateQuery.data;
  const questionsNotFound = questionsQuery.error instanceof ApiError && questionsQuery.error.status === 404;

  return (
    <div className="flex flex-col gap-6">
      <Link to="/app/candidates" className="flex w-fit items-center gap-1.5 text-sm font-medium text-ink-500 hover:text-ink-900">
        <ArrowLeft size={15} /> Back to Candidates
      </Link>

      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-100 text-lg font-bold text-brand-700">
            {(candidate.name ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h1 className="text-xl font-bold text-ink-900">{candidate.name ?? "Unknown candidate"}</h1>
            <p className="text-sm text-ink-500">
              {candidate.education ?? "Education not extracted"}
              {candidate.experience_years !== null ? ` · ${candidate.experience_years} yrs experience` : ""}
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => candidateService.downloadResumeFile(candidateId)}>
          <Download size={16} /> Download Resume
        </Button>
      </div>

      {!jobId && <JobPicker onSelect={(id) => setSearchParams({ jobId: id })} />}

      <div className="flex gap-1 border-b border-border">
        {(
          [
            ["overview", "Overview"],
            ["skills", "Skills & Match"],
            ["questions", "Interview Questions"],
          ] as [Tab, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 ${
              tab === value ? "border-brand-600 text-brand-700" : "border-transparent text-ink-500 hover:text-ink-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="flex flex-col items-center justify-center gap-3 text-center">
            {jobId && scoreQuery.data ? (
              <>
                <ScoreRing value={scoreQuery.data.final_fit_score} />
                <ScoreBandBadge band={scoreQuery.data.band} />
              </>
            ) : jobId && scoreQuery.isLoading ? (
              <Spinner />
            ) : jobId && scoreQuery.isError ? (
              <p className="text-sm text-ink-300">Not scored against this job yet.</p>
            ) : (
              <p className="text-sm text-ink-300">Select a job above to see match score.</p>
            )}
          </Card>

          <Card>
            <p className="mb-3 text-sm font-semibold text-ink-900">Key Information</p>
            <ul className="flex flex-col gap-2.5 text-sm text-ink-700">
              <li className="flex items-center gap-2">
                <Mail size={14} className="text-ink-300" /> {candidate.email ?? "Not extracted"}
              </li>
              <li className="flex items-center gap-2">
                <Phone size={14} className="text-ink-300" /> {candidate.phone ?? "Not extracted"}
              </li>
              <li className="flex items-center gap-2">
                <MapPin size={14} className="text-ink-300" /> {candidate.education ?? "Not extracted"}
              </li>
            </ul>
          </Card>

          <Card>
            <p className="mb-3 text-sm font-semibold text-ink-900">Skills</p>
            <div className="flex flex-wrap gap-1.5">
              {[...candidate.skills.technical, ...candidate.skills.tool].slice(0, 10).map((skill) => (
                <span key={skill.skill_name} className="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
                  {skill.skill_name}
                </span>
              ))}
              {candidate.skills.technical.length + candidate.skills.tool.length === 0 && (
                <p className="text-sm text-ink-300">No skills extracted.</p>
              )}
            </div>
          </Card>

          {jobId && skillGapQuery.data && (
            <>
              <Card className="lg:col-span-2">
                <p className="mb-3 text-sm font-semibold text-ink-900">Matched Skills</p>
                <div className="flex flex-wrap gap-1.5">
                  {skillGapQuery.data.matched.map((m) => (
                    <span key={m.skill} className="rounded-full bg-success-bg px-2.5 py-1 text-xs font-medium text-success">
                      {m.skill}
                      {m.source === "semantic" ? " ~" : ""}
                    </span>
                  ))}
                  {skillGapQuery.data.matched.length === 0 && <p className="text-sm text-ink-300">No skill overlap found.</p>}
                </div>
              </Card>
              <Card>
                <p className="mb-3 text-sm font-semibold text-ink-900">Missing Skills</p>
                <div className="flex flex-wrap gap-1.5">
                  {skillGapQuery.data.missing.map((skill) => (
                    <span key={skill} className="rounded-full bg-danger-bg px-2.5 py-1 text-xs font-medium text-danger">
                      {skill}
                    </span>
                  ))}
                  {skillGapQuery.data.missing.length === 0 && <p className="text-sm text-ink-300">No gaps — all required skills matched.</p>}
                </div>
              </Card>
            </>
          )}
        </div>
      )}

      {tab === "skills" && (
        <Card className="max-w-xl">
          {!jobId ? (
            <p className="text-sm text-ink-300">Select a job above to see the score breakdown.</p>
          ) : scoreQuery.data ? (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-ink-900">Fit Score Breakdown</p>
                <p className="text-2xl font-bold text-ink-900">{scoreQuery.data.final_fit_score.toFixed(1)}</p>
              </div>
              <SubScoreBar label="Resume Match" value={scoreQuery.data.resume_match_score} />
              <SubScoreBar label="Skill Match" value={scoreQuery.data.skill_match_score} />
              <SubScoreBar label="Experience" value={scoreQuery.data.experience_score} />
              <SubScoreBar label="Education" value={scoreQuery.data.education_score} />
              {scoreQuery.data.excluded_sub_scores.length > 0 && (
                <p className="text-xs text-ink-300">
                  {scoreQuery.data.excluded_sub_scores.join(", ")} excluded from the composite (unknown for this candidate) —
                  remaining weights renormalized.
                </p>
              )}
              <p className="text-xs text-ink-300">
                Scored via {scoreQuery.data.scoring_method} · {scoreQuery.data.is_stale ? "stale, job description changed since scoring" : "up to date"}
              </p>
            </div>
          ) : (
            <p className="text-sm text-ink-300">Not scored against this job yet.</p>
          )}
        </Card>
      )}

      {tab === "questions" && (
        <div className="flex flex-col gap-4">
          {!jobId ? (
            <p className="text-sm text-ink-300">Select a job above to generate interview questions.</p>
          ) : (
            <>
              <div className="flex items-start gap-2 rounded-lg bg-info-bg px-3 py-2.5 text-sm text-info">
                <Info size={16} className="mt-0.5 shrink-0" />
                <p>
                  <span className="font-semibold">Privacy notice:</span> AI interview-question generation sends
                  this candidate's resume text to the configured LLM provider. Resume text may include personal
                  information such as name, email, or phone number. This transfer occurs when you request
                  AI-generated interview questions.
                </p>
              </div>

              <div className="flex justify-end">
                <Button
                  variant={questionsQuery.data ? "outline" : "primary"}
                  isLoading={generateMutation.isPending}
                  onClick={() => generateMutation.mutate(Boolean(questionsQuery.data))}
                >
                  {questionsQuery.data ? <RefreshCcw size={16} /> : <Sparkles size={16} />}
                  {questionsQuery.data ? "Regenerate" : "Generate Questions"}
                </Button>
              </div>

              {questionsQuery.isLoading && <Spinner />}
              {generateMutation.isError && <ErrorState message="Couldn't generate questions right now. Please try again." />}
              {questionsQuery.isError && !questionsNotFound && (
                <ErrorState message="Couldn't load interview questions." />
              )}
              {questionsNotFound && !generateMutation.data && (
                <EmptyState title="No questions generated yet" description="Generate grounded interview questions from this candidate's resume." />
              )}

              {(questionsQuery.data ?? generateMutation.data) && (
                <div className="flex flex-col gap-3">
                  {(generateMutation.data ?? questionsQuery.data)!.partial && (
                    <p className="rounded-lg bg-warning-bg px-3 py-2 text-sm text-warning">
                      Only {(generateMutation.data ?? questionsQuery.data)!.grounded} of{" "}
                      {(generateMutation.data ?? questionsQuery.data)!.requested} requested questions could be grounded in this resume.
                    </p>
                  )}
                  {(generateMutation.data ?? questionsQuery.data)!.questions.map((q, index) => (
                    <Card key={q.id}>
                      <div className="mb-2 flex items-center gap-2">
                        <span className="text-sm font-semibold text-ink-300">{index + 1}.</span>
                        <Badge tone="info">{q.category.replace("_", " ")}</Badge>
                        <Badge tone={DIFFICULTY_TONE[q.difficulty]}>{q.difficulty}</Badge>
                      </div>
                      <p className="text-sm text-ink-900">{q.question}</p>
                      {q.rationale && <p className="mt-1.5 text-xs text-ink-300">{q.rationale}</p>}
                    </Card>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
