import { apiRequest } from "@/services/apiClient";
import type { InterviewQuestionsResponse } from "@/types";

export const interviewService = {
  generate: (candidateId: number, jobId: number, options: { count?: number; regenerate?: boolean } = {}) =>
    apiRequest<InterviewQuestionsResponse>(`/candidates/${candidateId}/interview-questions`, {
      method: "POST",
      body: { job_id: jobId, count: options.count ?? 8, regenerate: options.regenerate ?? false },
    }),
  get: (candidateId: number, jobId: number) =>
    apiRequest<InterviewQuestionsResponse>(`/candidates/${candidateId}/interview-questions`, {
      query: { job_id: jobId },
    }),
};
