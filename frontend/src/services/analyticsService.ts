import { apiRequest } from "@/services/apiClient";
import type {
  AnalyticsFilterParams,
  AttritionAnalyticsResponse,
  OverviewResponse,
  ScoresResponse,
  SkillsResponse,
} from "@/types";

export const analyticsService = {
  overview: (params: AnalyticsFilterParams = {}) =>
    apiRequest<OverviewResponse>("/analytics/overview", { query: params }),
  skills: (params: AnalyticsFilterParams = {}) => apiRequest<SkillsResponse>("/analytics/skills", { query: params }),
  scores: (params: AnalyticsFilterParams = {}) => apiRequest<ScoresResponse>("/analytics/scores", { query: params }),
  attrition: (params: AnalyticsFilterParams = {}) =>
    apiRequest<AttritionAnalyticsResponse>("/analytics/attrition", { query: params }),
};
