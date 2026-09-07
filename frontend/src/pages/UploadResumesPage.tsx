import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { jobService } from "@/services/jobService";
import { resumeService } from "@/services/resumeService";
import type { ResumeUploadResponse } from "@/types";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, File, UploadCloud, XCircle } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

export default function UploadResumesPage() {
  const [searchParams] = useSearchParams();
  const preselectedJobId = searchParams.get("jobId");

  const [jobId, setJobId] = useState<string>(preselectedJobId ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: () => jobService.list({ status: "open", page_size: 100 }) });

  const uploadMutation = useMutation({
    mutationFn: () => resumeService.upload(Number(jobId), files),
  });

  function addFiles(newFiles: FileList | null) {
    if (!newFiles) return;
    const valid = Array.from(newFiles).filter((f) => ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)));
    setFiles((prev) => [...prev, ...valid]);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    addFiles(event.dataTransfer.files);
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  const result: ResumeUploadResponse | undefined = uploadMutation.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold text-ink-900">Upload Resumes</h1>
        <p className="mt-1 text-sm text-ink-500">Upload resumes and match them against a job.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-150 ${
              isDragging ? "border-brand-400 bg-brand-50" : "border-border-strong"
            }`}
          >
            <UploadCloud size={32} className="text-brand-500" />
            <p className="text-sm font-medium text-ink-700">Drag & drop resumes here</p>
            <p className="text-xs text-ink-300">or</p>
            <Button type="button" variant="secondary" onClick={() => fileInputRef.current?.click()}>
              Choose Files
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_EXTENSIONS.join(",")}
              className="hidden"
              onChange={(e) => addFiles(e.target.files)}
            />
            <p className="text-xs text-ink-300">Supports PDF, DOCX (max 10MB each)</p>
          </div>

          {files.length > 0 && (
            <ul className="mt-4 flex flex-col gap-2">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2 text-sm">
                  <span className="flex items-center gap-2 truncate text-ink-700">
                    <File size={15} className="shrink-0 text-ink-300" />
                    <span className="truncate">{file.name}</span>
                  </span>
                  <button onClick={() => removeFile(index)} className="text-ink-300 hover:text-danger" aria-label="Remove file">
                    <XCircle size={16} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <p className="mb-3 text-sm font-semibold text-ink-900">Job</p>
          {jobsQuery.data && jobsQuery.data.items.length > 0 ? (
            <Select value={jobId} onChange={(e) => setJobId(e.target.value)}>
              <option value="">Select a job…</option>
              {jobsQuery.data.items.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.title}
                </option>
              ))}
            </Select>
          ) : (
            <p className="text-sm text-ink-500">
              No open jobs yet.{" "}
              <Link to="/app/jobs" className="font-semibold text-brand-600">
                Create one first
              </Link>
              .
            </p>
          )}

          <Button
            className="mt-4 w-full"
            disabled={!jobId || files.length === 0}
            isLoading={uploadMutation.isPending}
            onClick={() => uploadMutation.mutate()}
          >
            Analyze Resumes
          </Button>
          {uploadMutation.isError && <p className="mt-2 text-sm text-danger">Upload failed. Please try again.</p>}
        </Card>
      </div>

      {result && (
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm font-semibold text-ink-900">Upload Results</p>
            <p className="text-sm text-ink-500">
              {result.uploaded} succeeded · {result.failed} failed
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-ink-300">
                  <th className="pb-2 font-medium">File Name</th>
                  <th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((item) => (
                  <tr key={item.filename} className="border-b border-border last:border-0">
                    <td className="py-2.5 text-ink-700">{item.filename}</td>
                    <td className="py-2.5">
                      {item.status === "parsed" ? (
                        <Badge tone="success">
                          <CheckCircle2 size={12} className="mr-1 inline" /> Parsed
                        </Badge>
                      ) : item.status === "partial" ? (
                        <Badge tone="warning">Partial</Badge>
                      ) : (
                        <Badge tone="danger">Failed</Badge>
                      )}
                    </td>
                    <td className="py-2.5 text-ink-500">
                      {item.candidate_id ? (
                        <Link to={`/app/candidates/${item.candidate_id}`} className="font-medium text-brand-600">
                          View candidate
                        </Link>
                      ) : (
                        item.error ?? "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
