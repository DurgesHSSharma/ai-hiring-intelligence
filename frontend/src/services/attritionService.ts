import { apiRequest } from "@/services/apiClient";
import type {
  AttritionBatchPredictResponse,
  AttritionPredictInput,
  AttritionPredictResponse,
  Employee,
  ModelInfo,
  Page,
} from "@/types";

export const attritionService = {
  predict: (input: AttritionPredictInput) =>
    apiRequest<AttritionPredictResponse>("/attrition/predict", { method: "POST", body: input }),
  predictBatch: (records: AttritionPredictInput[]) =>
    apiRequest<AttritionBatchPredictResponse>("/attrition/predict/batch", { method: "POST", body: { records } }),
  employees: (page = 1, pageSize = 20) =>
    apiRequest<Page<Employee>>("/attrition/employees", { query: { page, page_size: pageSize } }),
  modelInfo: () => apiRequest<ModelInfo>("/attrition/model-info"),
};
