import { EmptyState, ErrorState, Spinner } from "@/components/ui/AsyncState";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Input";
import { jobService } from "@/services/jobService";
import type { JobCreateInput, JobSeniority } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, MapPin, Plus, Users, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

const EMPTY_FORM: JobCreateInput = {
  title: "",
  description: "",
  required_skills: [],
  min_experience_years: 0,
  education_requirement: "",
  seniority: "mid",
  location: "",
};

function CreateJobModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<JobCreateInput>(EMPTY_FORM);
  const [skillsInput, setSkillsInput] = useState("");

  const createJob = useMutation({
    mutationFn: () =>
      jobService.create({
        ...form,
        required_skills: skillsInput
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      onClose();
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    createJob.mutate();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-card-hover">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink-900">Create Job</h2>
          <button onClick={onClose} className="rounded-md p-1 text-ink-500 hover:bg-canvas" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Input
            label="Job Title"
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <Textarea
            label="Job Description"
            required
            rows={4}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <Input
            label="Required Skills (comma-separated)"
            placeholder="Python, SQL, AWS"
            value={skillsInput}
            onChange={(e) => setSkillsInput(e.target.value)}
          />
          <div className="grid grid-cols-2 gap-4">
            <Select
              label="Seniority"
              value={form.seniority}
              onChange={(e) => setForm({ ...form, seniority: e.target.value as JobSeniority })}
            >
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
              <option value="lead">Lead</option>
            </Select>
            <Input
              label="Min. Experience (years)"
              type="number"
              min={0}
              step={0.5}
              required
              value={form.min_experience_years}
              onChange={(e) => setForm({ ...form, min_experience_years: Number(e.target.value) })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Education Requirement"
              placeholder="Bachelor's degree"
              required
              value={form.education_requirement}
              onChange={(e) => setForm({ ...form, education_requirement: e.target.value })}
            />
            <Input
              label="Location"
              required
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
            />
          </div>
          {createJob.isError && <p className="text-sm text-danger">Couldn't create the job. Check the fields and try again.</p>}
          <div className="mt-2 flex justify-end gap-3">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" isLoading={createJob.isPending}>
              Create Job
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function JobsPage() {
  const [showCreate, setShowCreate] = useState(false);
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: () => jobService.list({ status: "all", page_size: 100 }) });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-ink-900">Jobs</h1>
          <p className="mt-1 text-sm text-ink-500">Open roles you're hiring for.</p>
        </div>
        <Button onClick={() => setShowCreate(true)}>
          <Plus size={16} /> New Job
        </Button>
      </div>

      {jobsQuery.isLoading && <Spinner />}
      {jobsQuery.isError && <ErrorState message="Couldn't load jobs. Please try again." />}
      {jobsQuery.data && jobsQuery.data.items.length === 0 && (
        <EmptyState
          title="No jobs yet"
          description="Create your first job to start uploading and ranking resumes against it."
          action={<Button onClick={() => setShowCreate(true)}>Create Job</Button>}
        />
      )}

      {jobsQuery.data && jobsQuery.data.items.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobsQuery.data.items.map((job) => (
            <Card key={job.id} hoverable className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold text-ink-900">{job.title}</h3>
                <Badge tone={job.status === "open" ? "success" : "neutral"}>{job.status === "open" ? "Open" : "Closed"}</Badge>
              </div>
              <div className="flex flex-col gap-1.5 text-sm text-ink-500">
                <span className="flex items-center gap-1.5">
                  <MapPin size={14} /> {job.location}
                </span>
                <span className="flex items-center gap-1.5">
                  <Briefcase size={14} /> {job.seniority} · {job.min_experience_years}+ yrs
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {job.required_skills.slice(0, 4).map((skill) => (
                  <span key={skill} className="rounded-full bg-canvas px-2.5 py-1 text-xs font-medium text-ink-500">
                    {skill}
                  </span>
                ))}
              </div>
              <div className="mt-1 flex items-center justify-between border-t border-border pt-3">
                <Link to={`/app/upload?jobId=${job.id}`} className="text-sm font-semibold text-brand-600 hover:text-brand-700">
                  Upload Resumes
                </Link>
                <Link
                  to={`/app/candidates?jobId=${job.id}`}
                  className="flex items-center gap-1 text-sm font-medium text-ink-500 hover:text-ink-900"
                >
                  <Users size={14} /> Candidates
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      {showCreate && <CreateJobModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}
