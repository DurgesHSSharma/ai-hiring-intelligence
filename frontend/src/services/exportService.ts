import { apiRequest } from "@/services/apiClient";
import type { CandidateListParams } from "@/types";

export const exportService = {
  async downloadCandidatesCsv(jobId: number, params: Omit<CandidateListParams, "job_id" | "page" | "page_size"> = {}) {
    const response = await apiRequest<Response>(`/jobs/${jobId}/export/csv`, {
      raw: true,
      query: {
        search: params.search,
        min_score: params.min_score,
        max_score: params.max_score,
        skills: params.skills,
        min_experience: params.min_experience,
        education_level: params.education_level,
        status: params.status,
        sort_by: params.sort_by,
        sort_order: params.sort_order,
      },
    });
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `job_${jobId}_candidates.csv`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  },
};
