import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent

JSON_FILE = HERE / "raw_generation_output.json"
CSV_FILE = HERE / "llm_rating_sheet.csv"

HEADERS = [
    "question_id",
    "source_candidate",
    "source_resume_file",
    "job_title",
    "job_id",
    "generated_question",
    "category",
    "difficulty",
    "relevance_1_to_5",
    "specificity_1_to_5",
    "technical_quality_1_to_5",
    "resume_grounding_1_to_5",
    "optional_human_notes",
]


def main():
    # Read the real generated questions
    data = json.loads(JSON_FILE.read_text(encoding="utf-8"))

    rows = []

    for resume_file, candidate_data in data.items():
        candidate_id = candidate_data["candidate_id"]
        job_id = candidate_data["job_id"]

        response = candidate_data["response"]

        for question in response["questions"]:
            rows.append({
                "question_id": question["id"],
                "source_candidate": candidate_id,
                "source_resume_file": resume_file,
                "job_title": "Backend Software Engineer",
                "job_id": job_id,
                "generated_question": question["question"],
                "category": question["category"],
                "difficulty": question["difficulty"],
                "relevance_1_to_5": "",
                "specificity_1_to_5": "",
                "technical_quality_1_to_5": "",
                "resume_grounding_1_to_5": "",
                "optional_human_notes": "",
            })

    # Safety check: Phase 13 requires exactly 20 rows
    if len(rows) != 20:
        raise RuntimeError(
            f"Expected exactly 20 questions, but found {len(rows)}"
        )

    # Write the CSV
    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"SUCCESS: wrote {len(rows)} questions to:")
    print(CSV_FILE)

    print("\nQuestions by resume:")
    counts = {}

    for row in rows:
        resume = row["source_resume_file"]
        counts[resume] = counts.get(resume, 0) + 1

    for resume, count in counts.items():
        print(f"  {resume}: {count}")


if __name__ == "__main__":
    main()