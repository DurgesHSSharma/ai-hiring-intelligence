import json
import sys
from pathlib import Path

import httpx


BASE = "http://127.0.0.1:8000/api/v1"

RECRUITER_EMAIL = "ada@example.com"
RECRUITER_PASSWORD = "correct-horse-battery"

REPO_ROOT = Path(__file__).resolve().parents[2]

REAL_EVAL_DIR = (
    REPO_ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "real_eval_set"
)

JOB_PAYLOAD = {
    "title": "Backend Software Engineer",
    "description": (
        "Build and maintain REST APIs using Python and FastAPI "
        "on PostgreSQL."
    ),
    "required_skills": [
        "Python",
        "SQL",
        "AWS",
        "PostgreSQL",
        "Kubernetes",
    ],
    "min_experience_years": 3.0,
    "education_requirement": "Bachelor's",
    "seniority": "mid",
    "location": "Remote",
}

TARGET_FILES = [
    "resume_004.docx",
]

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-"
        "officedocument.wordprocessingml.document"
    ),
}


def main() -> None:
    out_dir = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).parent
    )

    client = httpx.Client(timeout=90.0)

    resp = client.post(
        f"{BASE}/auth/login",
        json={
            "email": RECRUITER_EMAIL,
            "password": RECRUITER_PASSWORD,
        },
    )

    resp.raise_for_status()

    headers = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    print("Logged in.")

    resp = client.post(
        f"{BASE}/jobs",
        headers=headers,
        json=JOB_PAYLOAD,
    )

    resp.raise_for_status()

    job = resp.json()
    job_id = job["id"]

    print(f"Created job {job_id}: {job['title']}")

    files = [
        REAL_EVAL_DIR / name
        for name in TARGET_FILES
    ]

    multipart = [
        (
            "files",
            (
                f.name,
                f.read_bytes(),
                CONTENT_TYPES[f.suffix.lower()],
            ),
        )
        for f in files
    ]

    resp = client.post(
        f"{BASE}/jobs/{job_id}/resumes",
        headers=headers,
        files=multipart,
    )

    resp.raise_for_status()

    upload = resp.json()

    print(
        f"Uploaded {upload['uploaded']} resumes, "
        f"{upload['failed']} failed."
    )

    filename_to_candidate = {
        r["filename"]: r["candidate_id"]
        for r in upload["results"]
    }

    out_path = out_dir / "raw_generation_output.json"

    if out_path.exists():
        all_results = json.loads(
            out_path.read_text()
        )
    else:
        all_results = {}

    for name in TARGET_FILES:
        cid = filename_to_candidate.get(name)

        if cid is None:
            print(
                f"SKIP {name}: no candidate_id "
                "(parse failed?)"
            )
            continue

        payload = {
            "job_id": job_id,
            "count": 5,
            "regenerate": False,
        }

        r = client.post(
            f"{BASE}/candidates/{cid}/interview-questions",
            headers=headers,
            json=payload,
        )

        print(
            name,
            "candidate_id=",
            cid,
            "status=",
            r.status_code,
        )

        if r.status_code == 200:
            body = r.json()

            all_results[name] = {
                "candidate_id": cid,
                "job_id": job_id,
                "response": body,
            }

            print(
                f"   requested={body['requested']} "
                f"generated={body['generated']} "
                f"grounded={body['grounded']} "
                f"partial={body['partial']} "
                f"questions_returned="
                f"{len(body['questions'])}"
            )

        else:
            try:
                error_body = r.json()
            except Exception:
                error_body = {
                    "status_code": r.status_code,
                    "text": r.text,
                }

            all_results[name] = {
                "candidate_id": cid,
                "job_id": job_id,
                "error": error_body,
            }

            print("   ERROR:", error_body)

    out_path.write_text(
        json.dumps(
            all_results,
            indent=2,
            default=str,
        )
    )

    print(
        f"\nSaved raw output to {out_path}"
    )

    print(
        "Next: hand-pick real generated questions "
        "from this file into llm_rating_sheet.csv."
    )


if __name__ == "__main__":
    main()