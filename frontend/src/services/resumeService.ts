import { apiRequest } from "@/services/apiClient";
import type { ResumeUploadResponse } from "@/types";

export const resumeService = {
  upload: (jobId: number, files: File[]) => {
    const formData = new FormData();
    for (const file of files) formData.append("files", file);
    return apiRequest<ResumeUploadResponse>(`/jobs/${jobId}/resumes`, { method: "POST", formData });
  },
};
