import { apiRequest } from "@/services/apiClient";
import type {
  ApplicationOut,
  ApplicationStatus,
  CandidateDetail,
  CandidateListItem,
  CandidateListParams,
  Page,
} from "@/types";

function contentDispositionFilename(header: string | null, fallback: string): string {
  const match = header?.match(/filename="?([^"]+)"?/);
  return match?.[1] ?? fallback;
}

export const candidateService = {
  list: (params: CandidateListParams = {}) =>
    apiRequest<Page<CandidateListItem>>("/candidates", {
      query: {
        job_id: params.job_id,
        search: params.search,
        min_score: params.min_score,
        max_score: params.max_score,
        skills: params.skills,
        min_experience: params.min_experience,
        education_level: params.education_level,
        status: params.status,
        sort_by: params.sort_by,
        sort_order: params.sort_order,
        page: params.page,
        page_size: params.page_size,
      },
    }),
  get: (candidateId: number) => apiRequest<CandidateDetail>(`/candidates/${candidateId}`),
  remove: (candidateId: number) =>
    apiRequest<{ id: number; deleted: boolean }>(`/candidates/${candidateId}`, { method: "DELETE" }),
  async downloadResumeFile(candidateId: number): Promise<void> {
    const response = await apiRequest<Response>(`/candidates/${candidateId}/resume-file`, { raw: true });
    const blob = await response.blob();
    const filename = contentDispositionFilename(response.headers.get("Content-Disposition"), `resume_${candidateId}`);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(objectUrl);
  },
  updateApplicationStatus: (applicationId: number, status: ApplicationStatus) =>
    apiRequest<ApplicationOut>(`/applications/${applicationId}`, { method: "PATCH", body: { status } }),
};
