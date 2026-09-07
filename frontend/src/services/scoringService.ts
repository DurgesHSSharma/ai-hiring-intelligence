import { apiRequest } from "@/services/apiClient";
import type {
  CandidateScore,
  CompareCandidatesResponse,
  Page,
  RankingEntry,
  ScoreJobResponse,
  SkillGap,
} from "@/types";

export const scoringService = {
  scoreJob: (jobId: number, options: { candidateIds?: number[]; force?: boolean } = {}) =>
    apiRequest<ScoreJobResponse>(`/jobs/${jobId}/score`, {
      method: "POST",
      body: { candidate_ids: options.candidateIds ?? null, force: options.force ?? false },
    }),
  rankings: (jobId: number, page = 1, pageSize = 20) =>
    apiRequest<Page<RankingEntry>>(`/jobs/${jobId}/rankings`, { query: { page, page_size: pageSize } }),
  candidateScore: (candidateId: number, jobId: number) =>
    apiRequest<CandidateScore>(`/candidates/${candidateId}/score`, { query: { job_id: jobId } }),
  skillGap: (candidateId: number, jobId: number) =>
    apiRequest<SkillGap>(`/candidates/${candidateId}/skill-gap`, { query: { job_id: jobId } }),
  compare: (jobId: number, candidateIds: number[]) =>
    apiRequest<CompareCandidatesResponse>(`/jobs/${jobId}/compare`, {
      query: { candidate_ids: candidateIds.join(",") },
    }),
};
