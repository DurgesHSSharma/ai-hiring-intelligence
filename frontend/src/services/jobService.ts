import { apiRequest } from "@/services/apiClient";
import type { Job, JobCreateInput, JobDetail, Page, SuggestedSkill } from "@/types";

export interface JobListParams {
  search?: string;
  status?: "open" | "closed" | "all";
  page?: number;
  page_size?: number;
}

export const jobService = {
  list: (params: JobListParams = {}) =>
    apiRequest<Page<Job>>("/jobs", {
      query: { search: params.search, status: params.status, page: params.page, page_size: params.page_size },
    }),
  create: (input: JobCreateInput) => apiRequest<Job>("/jobs", { method: "POST", body: input }),
  get: (jobId: number) => apiRequest<JobDetail>(`/jobs/${jobId}`),
  update: (jobId: number, input: Partial<JobCreateInput> & { status?: "open" | "closed" }) =>
    apiRequest<Job>(`/jobs/${jobId}`, { method: "PATCH", body: input }),
  remove: (jobId: number) => apiRequest<{ id: number; deleted: boolean }>(`/jobs/${jobId}`, { method: "DELETE" }),
  suggestedSkills: (jobId: number) => apiRequest<{ job_id: number; suggested: SuggestedSkill[] }>(`/jobs/${jobId}/suggested-skills`),
};
