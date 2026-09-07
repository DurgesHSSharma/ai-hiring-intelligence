import { EmptyState, ErrorState, Spinner } from "@/components/ui/AsyncState";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Input";
import { RiskLevelBadge } from "@/components/ui/Badge";
import { ScoreRing } from "@/components/ui/ScoreRing";
import { analyticsService } from "@/services/analyticsService";
import { attritionService } from "@/services/attritionService";
import type { AttritionPredictInput, AttritionPredictResponse } from "@/types";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, TrendingDown } from "lucide-react";
import { useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const RISK_COLORS: Record<string, string> = { low: "#16a34a", medium: "#d97706", high: "#dc2626" };

const EMPTY_INPUT: AttritionPredictInput = {
  age: 30,
  department: "Sales",
  job_level: 2,
  monthly_income: 5000,
  years_at_company: 3,
  years_since_last_promotion: 1,
  years_with_curr_manager: 2,
  total_working_years: 6,
  job_satisfaction: 3,
  environment_satisfaction: 3,
  relationship_satisfaction: 3,
  performance_rating: 3,
  stock_option_level: 0,
  business_travel: "Travel_Rarely",
  distance_from_home: 5,
  percent_salary_hike: 12,
  overtime: false,
};

function numberField(label: string, key: keyof AttritionPredictInput, value: AttritionPredictInput, setValue: (v: AttritionPredictInput) => void, min = 0) {
  return (
    <Input
      label={label}
      type="number"
      min={min}
      value={(value[key] as number | null) ?? ""}
      onChange={(e) => setValue({ ...value, [key]: e.target.value === "" ? null : Number(e.target.value) })}
    />
  );
}

export default function AttritionPage() {
  const [form, setForm] = useState<AttritionPredictInput>(EMPTY_INPUT);
  const [result, setResult] = useState<AttritionPredictResponse | null>(null);

  const predictMutation = useMutation({
    mutationFn: () => attritionService.predict(form),
    onSuccess: setResult,
  });

  const overviewQuery = useQuery({ queryKey: ["analytics", "attrition"], queryFn: () => analyticsService.attrition() });

  const riskChartData = overviewQuery.data?.by_risk_level.map((r) => ({ name: r.risk_level, value: r.count })) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Employee Attrition Prediction</h1>
        <p className="mt-1 text-sm text-ink-500">Predict attrition risk and get actionable insights.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <p className="mb-4 text-sm font-semibold text-ink-900">Employee Profile</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {numberField("Age", "age", form, setForm)}
            {numberField("Job Level", "job_level", form, setForm)}
            {numberField("Monthly Income", "monthly_income", form, setForm)}
            {numberField("Years at Company", "years_at_company", form, setForm)}
            {numberField("Yrs Since Promotion", "years_since_last_promotion", form, setForm)}
            {numberField("Yrs With Manager", "years_with_curr_manager", form, setForm)}
            {numberField("Total Working Years", "total_working_years", form, setForm)}
            {numberField("Distance From Home", "distance_from_home", form, setForm)}
            {numberField("% Salary Hike", "percent_salary_hike", form, setForm)}
            <Select
              label="Job Satisfaction (1-4)"
              value={form.job_satisfaction ?? ""}
              onChange={(e) => setForm({ ...form, job_satisfaction: Number(e.target.value) })}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
            <Select
              label="Environment Satisfaction (1-4)"
              value={form.environment_satisfaction ?? ""}
              onChange={(e) => setForm({ ...form, environment_satisfaction: Number(e.target.value) })}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
            <Select
              label="Relationship Satisfaction (1-4)"
              value={form.relationship_satisfaction ?? ""}
              onChange={(e) => setForm({ ...form, relationship_satisfaction: Number(e.target.value) })}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
            <Select
              label="Performance Rating (1-4)"
              value={form.performance_rating ?? ""}
              onChange={(e) => setForm({ ...form, performance_rating: Number(e.target.value) })}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
            <Select
              label="Stock Option Level (0-3)"
              value={form.stock_option_level ?? ""}
              onChange={(e) => setForm({ ...form, stock_option_level: Number(e.target.value) })}
            >
              {[0, 1, 2, 3].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
            <Select
              label="Business Travel"
              value={form.business_travel ?? ""}
              onChange={(e) => setForm({ ...form, business_travel: e.target.value })}
            >
              <option value="Non-Travel">Non-Travel</option>
              <option value="Travel_Rarely">Travel Rarely</option>
              <option value="Travel_Frequently">Travel Frequently</option>
            </Select>
            <Select
              label="Overtime"
              value={form.overtime ? "true" : "false"}
              onChange={(e) => setForm({ ...form, overtime: e.target.value === "true" })}
            >
              <option value="false">No</option>
              <option value="true">Yes</option>
            </Select>
            <Input
              label="Department"
              value={form.department ?? ""}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
            />
          </div>
          <Button className="mt-5 w-full" isLoading={predictMutation.isPending} onClick={() => predictMutation.mutate()}>
            Predict Attrition
          </Button>
          {predictMutation.isError && <p className="mt-2 text-sm text-danger">Couldn't run the prediction. Please try again.</p>}
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <p className="mb-4 text-sm font-semibold text-ink-900">Prediction Result</p>
            {!result ? (
              <EmptyState title="No prediction yet" description="Fill in the employee profile and predict attrition risk." />
            ) : (
              <div className="flex flex-col items-center gap-4">
                <ScoreRing value={result.probability * 100} label="probability" colorClass={result.flagged ? "text-danger" : "text-success"} />
                <RiskLevelBadge level={result.risk_level} />
                {result.top_factors.length > 0 && (
                  <div className="w-full">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-300">Top Contributing Factors</p>
                    <ul className="flex flex-col gap-1.5">
                      {result.top_factors.slice(0, 5).map((f) => (
                        <li key={f.feature} className="flex items-center justify-between text-sm">
                          <span className="flex items-center gap-1.5 text-ink-700">
                            <AlertTriangle size={13} className="text-warning" /> {f.feature.replaceAll("_", " ")}
                          </span>
                          <span className="font-medium text-ink-500">{f.contribution.toFixed(3)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="text-center text-xs text-ink-300">{result.calibration_known_limitation}</p>
              </div>
            )}
          </Card>

          <Card>
            <p className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink-900">
              <TrendingDown size={16} /> Attrition Analysis Results
            </p>
            {overviewQuery.isLoading && <Spinner />}
            {overviewQuery.isError && <ErrorState message="Couldn't load attrition analytics." />}
            {overviewQuery.data && overviewQuery.data.total_employees_with_prediction === 0 && (
              <p className="text-sm text-ink-300">No employees with predictions yet.</p>
            )}
            {overviewQuery.data && overviewQuery.data.total_employees_with_prediction > 0 && (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width="50%" height={160}>
                  <PieChart>
                    <Pie data={riskChartData} dataKey="value" nameKey="name" innerRadius={40} outerRadius={65} paddingAngle={2}>
                      {riskChartData.map((entry) => (
                        <Cell key={entry.name} fill={RISK_COLORS[entry.name]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e7e5f0" }} />
                  </PieChart>
                </ResponsiveContainer>
                <ul className="flex flex-1 flex-col gap-2 text-sm">
                  {overviewQuery.data.by_risk_level.map((r) => (
                    <li key={r.risk_level} className="flex items-center justify-between">
                      <span className="flex items-center gap-2 text-ink-700">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: RISK_COLORS[r.risk_level] }} />
                        {r.risk_level}
                      </span>
                      <span className="font-medium text-ink-500">{r.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
