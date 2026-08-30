"""Phase 4 acceptance: file validation tiers (extension/MIME/magic-bytes/size),
per-file batch continuation, text extraction + cleaning correctness, the
100-character guard, resume-file streaming, and delete-removes-file.
"""
import io
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.config import settings
from app.core.enums import JobSeniority, ParseStatus
from app.core.exceptions import FileValidationError
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import Job
from app.utils.files import validate_and_read_upload

FIXTURES = Path(__file__).parent / "fixtures"


def _make_job(db_session, title: str = "Backend Engineer") -> Job:
    job = Job(
        title=title,
        description="Build and ship backend services.",
        required_skills=["Python"],
        min_experience_years=0.0,
        education_requirement="Bachelor's",
        seniority=JobSeniority.MID,
        location="Remote",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _part(filename: str, content: bytes, content_type: str):
    return ("files", (filename, content, content_type))


def _pdf(name: str = "sample_resume.pdf", as_name: str | None = None):
    return _part(as_name or name, (FIXTURES / name).read_bytes(), "application/pdf")


def _docx(name: str = "sample_resume.docx", as_name: str | None = None):
    return _part(
        as_name or name,
        (FIXTURES / name).read_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# --- batch success -----------------------------------------------------------


def test_upload_mixed_valid_files_creates_parsed_candidates(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [_pdf(as_name="a.pdf"), _docx(as_name="b.docx")]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert body["uploaded"] == 2
    assert body["failed"] == 0
    for result in body["results"]:
        assert result["status"] == "parsed"
        assert result["candidate_id"] is not None
        assert result["code"] is None

    candidates = db_session.query(Candidate).all()
    assert len(candidates) == 2
    for c in candidates:
        assert len(c.resume_text) >= 100
        assert c.parse_status == ParseStatus.PARSED
        assert db_session.query(Application).filter_by(candidate_id=c.id, job_id=job.id).count() == 1


def test_upload_10_files_creates_10_candidates(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [_pdf(as_name=f"pdf_{i}.pdf") for i in range(5)] + [_docx(as_name=f"docx_{i}.docx") for i in range(5)]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 10
    assert body["failed"] == 0
    assert len(body["results"]) == 10

    candidates = db_session.query(Candidate).all()
    assert len(candidates) == 10
    assert all(len(c.resume_text) > 0 for c in candidates)


# --- per-file failure isolation ------------------------------------------------


def test_corrupt_file_isolated_other_nine_succeed(client, db_session, auth_headers, upload_dir):
    job = _make_job(db_session)
    parts = [_pdf(as_name=f"good_{i}.pdf") for i in range(9)] + [_part("corrupt.pdf", (FIXTURES / "corrupt.pdf").read_bytes(), "application/pdf")]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 9
    assert body["failed"] == 1

    failed_results = [r for r in body["results"] if r["status"] == "parse_failed"]
    assert len(failed_results) == 1
    failed = failed_results[0]
    assert failed["filename"] == "corrupt.pdf"
    assert failed["code"] == "RESUME_PARSE_FAILED"
    # Correction: a parse failure still gets a candidate row (PRD F3.7).
    assert failed["candidate_id"] is not None

    candidate = db_session.get(Candidate, failed["candidate_id"])
    assert candidate.parse_status == ParseStatus.PARSE_FAILED
    assert candidate.parse_error is not None
    assert candidate.resume_text == ""
    # The stored file is kept so the recruiter can open it and see why.
    assert (upload_dir / candidate.resume_path).exists()
    # An application row exists too, so it shows up in the job's candidate list.
    assert db_session.query(Application).filter_by(candidate_id=candidate.id, job_id=job.id).count() == 1


def test_image_only_pdf_recorded_parse_failed_too_short(client, db_session, auth_headers, upload_dir):
    job = _make_job(db_session)
    parts = [_part("scan.pdf", (FIXTURES / "image_only.pdf").read_bytes(), "application/pdf")]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 0
    assert body["failed"] == 1
    result = body["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "RESUME_TEXT_TOO_SHORT"
    assert result["candidate_id"] is not None  # not silently dropped — PRD F3.7

    candidate = db_session.get(Candidate, result["candidate_id"])
    assert candidate.parse_status == ParseStatus.PARSE_FAILED
    assert "100" in candidate.parse_error
    assert (upload_dir / candidate.resume_path).exists()
    assert db_session.query(Application).filter_by(candidate_id=candidate.id, job_id=job.id).count() == 1


def test_txt_upload_rejected_per_file_no_candidate_row(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [_part("notes.txt", b"This is not a resume, just plain text.", "text/plain")]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    # Amended acceptance criterion: file-level rejection, embedded in a 200
    # batch response — see Phases.md and Memory.md.
    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 0
    assert body["failed"] == 1
    result = body["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"
    assert result["candidate_id"] is None  # a .txt was never a resume — no row at all

    assert db_session.query(Candidate).count() == 0


def test_oversized_upload_rejected_per_file(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [_part("huge.pdf", (FIXTURES / "oversized.pdf").read_bytes(), "application/pdf")]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 200
    body = response.json()
    result = body["results"][0]
    assert result["status"] == "parse_failed"
    assert result["code"] == "FILE_TOO_LARGE"
    assert result["candidate_id"] is None

    assert db_session.query(Candidate).count() == 0


# --- request-level checks -------------------------------------------------


def test_upload_job_not_found(client, auth_headers):
    response = client.post(
        "/api/v1/jobs/999999/resumes", headers=auth_headers, files=[_part("a.txt", b"x", "text/plain")]
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_upload_empty_file_list_returns_400(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_FILES_PROVIDED"


def test_upload_batch_exceeding_limit_returns_400(client, db_session, auth_headers):
    job = _make_job(db_session)
    parts = [_part(f"f{i}.pdf", b"x", "application/pdf") for i in range(settings.MAX_FILES_PER_BATCH + 1)]

    response = client.post(f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=parts)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BATCH_LIMIT_EXCEEDED"


# --- extraction/cleaning correctness ------------------------------------------


def test_pdf_text_cleaned_correctly(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf(as_name="jane.pdf")]
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text

    # Running header/footer stripped, real content (including the candidate's
    # own name, which appears only once and isn't a repeat) untouched.
    assert "Jane Doe - Resume" not in text
    assert "Page 1 of 2" not in text
    assert "Page 2 of 2" not in text
    assert text.startswith("Jane Doe")
    # Hyphenated line-wraps repaired, not left as two fragments.
    assert "responsive" in text
    assert "respon-" not in text
    assert "conversion" in text
    assert "conver-" not in text
    # Section order preserved: SUMMARY before EXPERIENCE before EDUCATION before SKILLS.
    assert text.index("SUMMARY") < text.index("EXPERIENCE") < text.index("EDUCATION") < text.index("SKILLS")


# Exact-match regression pin, captured before any column-splitting logic was
# ever considered. PDF extraction has no column-detection code path today —
# this is the single source of truth for "the single-column fallback is
# byte-identical to what extract_text has always produced." If a future
# change to text_extractor.py/text_cleaner.py alters this fixture's output
# at all, this test — not a human rereading printed output — is what has to
# fail first.
_SAMPLE_RESUME_PDF_EXPECTED_TEXT = (
    "Jane Doe\nFrontend Engineer\nSUMMARY\nExperienced frontend engineer with a background in "
    "building responsive, accessible web applications using modern JavaScript frameworks.\n"
    "EXPERIENCE\nSenior Frontend Engineer, Northwind Retail -- 2021 to Present\nLed the redesign "
    "of the customer checkout flow, improving conversion rate by fourteen percent over two "
    "quarters.\nMentored two junior engineers and ran the weekly frontend guild.\nFrontend "
    "Engineer, Bluecrest Software -- 2018 to 2021\nBuilt and maintained the shared component "
    "library used across\nfive internal products.\n\nEDUCATION\nB.S. in Computer Science, "
    "Rivertown State University, 2018\nSKILLS\nJavaScript, TypeScript, React, CSS, Node.js, Git, "
    "Jest, Webpack\nCERTIFICATIONS\nCertified Scrum Master, 2022"
)


def test_pdf_extraction_output_pinned_exactly(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf(as_name="pinned.pdf")]
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text
    assert text == _SAMPLE_RESUME_PDF_EXPECTED_TEXT


def test_dates_column_fixture_stays_single_flow_today(client, db_session, auth_headers):
    """No column-splitting code exists yet (see Memory.md — the threshold
    investigation found the gap-fraction signal alone can't safely separate
    this fixture's 90% confidence from real_resume.pdf's 100%, so nothing
    was wired up). This just pins today's actual, unsplit behavior: title
    and date stay on one line, nothing is torn apart. Whatever detection
    design eventually lands must not break this fixture worse than doing
    nothing does.
    """
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf("dates_column_resume.pdf", as_name="jordan.pdf")]
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text
    assert "Senior Data Engineer, Acme Corp" in text
    assert "2021 - Present" in text
    # Title and date are still one physical line — not split apart.
    lines = text.split("\n")
    assert any("Senior Data Engineer, Acme Corp" in l and "2021 - Present" in l for l in lines)


def test_dates_column_proportional_fixture_stays_single_flow_today(client, db_session, auth_headers):
    """Same fixture, rebuilt in Helvetica (proportional) with the date
    column placed via absolute text-matrix positioning rather than
    character-count padding — a ragged gap before a fixed-position date,
    matching a real tab-stop template rather than monospace worst-case.
    Measured gutter confidence didn't drop (100% at the tightest candidate,
    over more spanning rows than the Courier version) — see Memory.md. This
    pins the same "stays unsplit today" baseline for that fixture too.
    """
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes",
        headers=auth_headers,
        files=[_pdf("dates_column_resume_proportional.pdf", as_name="jordan2.pdf")],
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text
    lines = text.split("\n")
    assert any("Senior Data Engineer, Acme Corp" in l and "2021 - Present" in l for l in lines)


def test_docx_text_extracted_in_order(client, db_session, auth_headers):
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_docx(as_name="marcus.docx")]
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text

    assert text.startswith("Marcus Chen")
    assert text.index("SUMMARY") < text.index("EXPERIENCE") < text.index("EDUCATION") < text.index("SKILLS")


def test_docx_table_sidebar_content_extracted_in_place(client, db_session, auth_headers):
    """document.paragraphs alone never sees table cells — a 2-column table
    layout (a common way to fake a sidebar in Word) would silently lose the
    entire sidebar with no error. This proves the fix: table content is
    present and lands in the right position relative to the paragraphs
    before and after the table.
    """
    job = _make_job(db_session)
    response = client.post(
        f"/api/v1/jobs/{job.id}/resumes",
        headers=auth_headers,
        files=[_part("priya.docx", (FIXTURES / "two_column_table_resume.docx").read_bytes(),
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")],
    )
    candidate_id = response.json()["results"][0]["candidate_id"]
    text = db_session.get(Candidate, candidate_id).resume_text

    # Sidebar (right table cell) content is present at all — the bug this
    # fixes made it vanish entirely, not just reorder it.
    for expected in ["SKILLS", "Figma", "CONTACT", "priya.nair@example.com"]:
        assert expected in text

    # And in the right place: paragraph before the table, then the table's
    # left cell in full, then its right cell in full, then the paragraph
    # after the table — true document order, not "paragraphs first, table
    # content appended at the end."
    assert (
        text.index("Priya Nair")
        < text.index("EXPERIENCE")
        < text.index("EDUCATION")
        < text.index("SKILLS")
        < text.index("CONTACT")
        < text.index("REFERENCES available")
    )


# --- validator-level proof of the 415/413 pairing (Rules.md 5.2:
# FileValidationError carries both statuses depending on which check fails) --


def test_validator_raises_415_for_txt():
    upload = UploadFile(
        file=io.BytesIO(b"plain text, not a resume"),
        filename="notes.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    try:
        validate_and_read_upload(upload)
        assert False, "expected FileValidationError"
    except FileValidationError as exc:
        assert exc.http_status == 415
        assert exc.code == "UNSUPPORTED_FILE_TYPE"


def test_validator_raises_413_for_oversized_pdf():
    content = (FIXTURES / "oversized.pdf").read_bytes()
    upload = UploadFile(
        file=io.BytesIO(content), filename="huge.pdf", headers=Headers({"content-type": "application/pdf"})
    )
    try:
        validate_and_read_upload(upload)
        assert False, "expected FileValidationError"
    except FileValidationError as exc:
        assert exc.http_status == 413
        assert exc.code == "FILE_TOO_LARGE"


def test_validator_rejects_renamed_non_word_zip():
    """PK\\x03\\x04 alone only proves 'this is a zip' — a spreadsheet renamed
    .docx must still be rejected, via the word/document.xml check."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")  # xlsx marker, not word/
    buf.seek(0)

    upload = UploadFile(
        file=buf,
        filename="fake.docx",
        headers=Headers(
            {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        ),
    )
    try:
        validate_and_read_upload(upload)
        assert False, "expected FileValidationError"
    except FileValidationError as exc:
        assert exc.http_status == 415
        assert exc.code == "UNSUPPORTED_FILE_TYPE"


# --- resume-file streaming -----------------------------------------------


def test_get_resume_file_streams_correct_content_type(client, db_session, auth_headers):
    job = _make_job(db_session)
    upload_response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf(as_name="original_name.pdf")]
    )
    candidate_id = upload_response.json()["results"][0]["candidate_id"]

    response = client.get(f"/api/v1/candidates/{candidate_id}/resume-file", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "original_name.pdf" in response.headers["content-disposition"]
    assert response.content == (FIXTURES / "sample_resume.pdf").read_bytes()


def test_get_resume_file_404_for_missing_candidate(client, auth_headers):
    response = client.get("/api/v1/candidates/999999/resume-file", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"


# --- delete removes the stored file too -----------------------------------


def test_delete_candidate_removes_stored_file(client, db_session, auth_headers, upload_dir):
    job = _make_job(db_session)
    upload_response = client.post(
        f"/api/v1/jobs/{job.id}/resumes", headers=auth_headers, files=[_pdf(as_name="to_delete.pdf")]
    )
    candidate_id = upload_response.json()["results"][0]["candidate_id"]
    resume_path = db_session.get(Candidate, candidate_id).resume_path
    stored_file = upload_dir / resume_path
    assert stored_file.exists()

    response = client.delete(f"/api/v1/candidates/{candidate_id}", headers=auth_headers)
    assert response.status_code == 200
    assert not stored_file.exists()
