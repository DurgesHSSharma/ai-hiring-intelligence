// Mirrors backend/app/schemas/*.py and core/enums.py field-for-field.
// Keep in sync with docs/API.md whenever the backend contract changes.

export type UserRole = "recruiter" | "manager" | "analyst" | "admin";
export type JobSeniority = "junior" | "mid" | "senior" | "lead";
export type JobStatus = "open" | "closed";
export type ApplicationStatus = "new" | "shortlisted" | "interviewed" | "selected" | "rejected";
export type ParseStatus = "parsed" | "partial" | "parse_failed";
export type SkillType = "technical" | "tool" | "soft" | "domain";
export type SkillSource = "dictionary" | "semantic";
export type ScoringMethod = "tfidf" | "embedding";
export type QuestionCategory = "technical" | "project" | "experience" | "skill_verification" | "behavioral";
export type QuestionDifficulty = "easy" | "medium" | "hard";
export type RiskLevel = "low" | "medium" | "high";
export type ScoreBand = "strong_match" | "good_match" | "moderate_match" | "weak_match";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

// ---- Auth ----

export interface User {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

// ---- Jobs ----

export interface Job {
  id: number;
  title: string;
  description: string;
  required_skills: string[];
  min_experience_years: number;
  education_requirement: string;
  seniority: JobSeniority;
  location: string;
  status: JobStatus;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface JobTopCandidate {
  candidate_id: number;
  name: string | null;
  final_fit_score: number;
}

export interface JobDetail extends Job {
  candidate_count: number;
  average_fit_score: number | null;
  top_candidate: JobTopCandidate | null;
}

export interface JobCreateInput {
  title: string;
  description: string;
  required_skills: string[];
  min_experience_years: number;
  education_requirement: string;
  seniority: JobSeniority;
  location: string;
}

export interface SuggestedSkill {
  canonical: string;
  type: SkillType;
}

// ---- Candidates ----

export interface CandidateSkill {
  skill_name: string;
  skill_type: SkillType;
  source: SkillSource;
}

export interface GroupedSkills {
  technical: CandidateSkill[];
  tool: CandidateSkill[];
  soft: CandidateSkill[];
  domain: CandidateSkill[];
}

export interface CandidateListItem {
  id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  education: string | null;
  education_level: number | null;
  experience_years: number | null;
  projects: unknown[];
  certifications: unknown[];
  parse_status: ParseStatus;
  parse_error: string | null;
  created_at: string;
  fit_score: number | null;
}

export interface CandidateDetail extends CandidateListItem {
  skills: GroupedSkills;
}

export interface ApplicationOut {
  id: number;
  candidate_id: number;
  job_id: number;
  status: ApplicationStatus;
  created_at: string;
  updated_at: string;
}

export interface CandidateListParams {
  job_id?: number;
  search?: string;
  min_score?: number;
  max_score?: number;
  skills?: string[];
  min_experience?: number;
  education_level?: number;
  status?: ApplicationStatus;
  sort_by?: "created_at" | "fit_score" | "experience" | "name";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

// ---- Resumes ----

export interface ResumeUploadResult {
  filename: string;
  status: ParseStatus;
  candidate_id: number | null;
  code: string | null;
  error: string | null;
}

export interface ResumeUploadResponse {
  job_id: number;
  uploaded: number;
  failed: number;
  results: ResumeUploadResult[];
}

// ---- Scoring ----

export interface CandidateScore {
  candidate_id: number;
  job_id: number;
  resume_match_score: number;
  skill_match_score: number;
  experience_score: number | null;
  education_score: number | null;
  final_fit_score: number;
  band: ScoreBand;
  scoring_method: ScoringMethod;
  score_version: number;
  is_stale: boolean;
  excluded_sub_scores: string[];
}

export interface RankingEntry extends CandidateScore {
  candidate_name: string | null;
  candidate_email: string | null;
}

export interface ScoreJobResultItem {
  candidate_id: number;
  status: "scored" | "skipped";
  final_fit_score: number | null;
  code: string | null;
  reason: string | null;
}

export interface ScoreJobResponse {
  job_id: number;
  scored: number;
  skipped: number;
  results: ScoreJobResultItem[];
}

export interface SkillGapMatch {
  skill: string;
  source: SkillSource;
  matched_via: string | null;
}

export interface SkillGap {
  candidate_id: number;
  job_id: number;
  matched: SkillGapMatch[];
  missing: string[];
  additional: string[];
  percentage: number;
}

export interface ComparisonCandidateDetail {
  candidate_id: number;
  candidate_name: string | null;
  matched_skills: SkillGapMatch[];
  missing_skills: string[];
}

export interface ComparisonMetricRow {
  metric: string;
  label: string;
  direction: "higher_is_better" | "lower_is_better";
  values: Record<number, number | null>;
  best_candidate_id: number | null;
}

export interface CompareCandidatesResponse {
  job_id: number;
  candidate_ids: number[];
  candidates: ComparisonCandidateDetail[];
  matrix: ComparisonMetricRow[];
}

// ---- Interview questions ----

export interface InterviewQuestion {
  id: number;
  question: string;
  category: QuestionCategory;
  difficulty: QuestionDifficulty;
  rationale: string | null;
  generation_batch: string;
  created_at: string;
}

export interface InterviewQuestionsResponse {
  candidate_id: number;
  job_id: number;
  generation_batch: string;
  requested: number;
  generated: number;
  grounded: number;
  partial: boolean;
  questions: InterviewQuestion[];
}

// ---- Attrition ----

export interface EmployeeFeaturesInput {
  age?: number | null;
  distance_from_home?: number | null;
  monthly_income?: number | null;
  percent_salary_hike?: number | null;
  total_working_years?: number | null;
  years_at_company?: number | null;
  years_since_last_promotion?: number | null;
  years_with_curr_manager?: number | null;
  job_level?: number | null;
  job_satisfaction?: number | null;
  environment_satisfaction?: number | null;
  relationship_satisfaction?: number | null;
  performance_rating?: number | null;
  stock_option_level?: number | null;
  department?: string | null;
  business_travel?: string | null;
  overtime?: boolean | null;
}

export interface AttritionPredictInput extends EmployeeFeaturesInput {
  employee_id?: number | null;
}

export interface TopFactor {
  feature: string;
  contribution: number;
}

export interface AttritionPredictResponse {
  employee_id: number | null;
  prediction_id: number | null;
  probability: number;
  flagged: boolean;
  decision_threshold: number;
  calibration_method: string;
  model_family: string;
  imbalance_strategy: string;
  model_version: string;
  top_factors: TopFactor[];
  risk_level: RiskLevel;
  risk_level_status: string;
  calibration_known_limitation: string;
}

export interface AttritionBatchResultItem {
  index: number;
  employee_id: number | null;
  status: "predicted" | "failed";
  prediction: AttritionPredictResponse | null;
  code: string | null;
  reason: string | null;
}

export interface AttritionBatchPredictResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: AttritionBatchResultItem[];
}

export interface LatestPrediction {
  probability: number;
  risk_level: RiskLevel | null;
  model_version: string;
  prediction_date: string;
}

export interface Employee {
  id: number;
  age: number;
  department: string;
  job_level: number;
  monthly_income: number;
  years_at_company: number;
  years_since_last_promotion: number;
  years_with_curr_manager: number;
  total_working_years: number;
  job_satisfaction: number;
  environment_satisfaction: number;
  relationship_satisfaction: number;
  performance_rating: number;
  overtime: boolean;
  business_travel: string;
  distance_from_home: number;
  percent_salary_hike: number;
  stock_option_level: number;
  latest_prediction: LatestPrediction | null;
}

export interface ModelInfo {
  model_family: string;
  imbalance_strategy: string;
  calibration_method: string;
  calibrated_decision_threshold: number;
  model_version: string;
  feature_names: string[];
  raw_evaluation_threshold: number;
  raw_evaluation_metrics: Record<string, unknown>;
  calibrated_evaluation_metrics: Record<string, unknown>;
  calibration_brier_improvement_mean: number | null;
  calibration_brier_improvement_std: number | null;
  calibration_known_limitation: string;
  risk_band_status: "resolved";
  risk_band_note: string;
  risk_tier_scheme: string;
  risk_tier_high_cutoff: number;
  risk_tier_medium_cutoff: number;
  risk_tier_percentile_method: string;
  risk_tier_oof_seeds: number[];
  risk_tier_oof_population: number;
  risk_tier_derivation_date: string;
  risk_tier_known_limitation: string;
}

// ---- Analytics ----

export interface AnalyticsFilters {
  job_id: number | null;
  date_from: string | null;
  date_to: string | null;
}

export interface AnalyticsFilterParams {
  job_id?: number;
  from?: string;
  to?: string;
  [key: string]: unknown;
}

export interface FunnelCounts {
  total: number;
  new: number;
  shortlisted: number;
  interviewed: number;
  selected: number;
  rejected: number;
}

export interface OverviewResponse {
  filters: AnalyticsFilters;
  funnel: FunnelCounts;
}

export interface SkillCount {
  skill_name: string;
  count: number;
}

export interface SkillsResponse {
  filters: AnalyticsFilters;
  top_candidate_skills: SkillCount[];
  top_missing_skills: SkillCount[];
}

export interface ScoreBucket {
  range_start: number;
  range_end: number;
  count: number;
}

export interface JobAverageScore {
  job_id: number;
  job_title: string;
  average_fit_score: number;
  candidate_count: number;
}

export interface ScoresResponse {
  filters: AnalyticsFilters;
  overall_average_fit_score: number | null;
  average_by_job: JobAverageScore[];
  distribution: ScoreBucket[];
}

export interface RiskLevelCount {
  risk_level: RiskLevel;
  count: number;
}

export interface DepartmentRisk {
  department: string;
  average_probability: number;
  employee_count: number;
}

export interface AttritionAnalyticsResponse {
  filters: AnalyticsFilters;
  job_id_filter_applied: boolean;
  total_employees_with_prediction: number;
  by_risk_level: RiskLevelCount[];
  by_department: DepartmentRisk[];
}
