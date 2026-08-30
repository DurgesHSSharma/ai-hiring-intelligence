"""Unit tests for app/ml/extraction/field_extractor.py — the individual
regex/heuristic behaviors, isolated from the upload pipeline. Integration
with resume_service.py (dedupe, skill attachment) is covered separately
in test_resume_extraction.py.
"""
from datetime import date

from app.ml.extraction.field_extractor import (
    extract_certifications,
    extract_education,
    extract_email,
    extract_experience_section_text,
    extract_experience_years,
    extract_name,
    extract_phone,
    extract_projects,
    find_date_ranges,
    is_heading_word,
)

# --- email -----------------------------------------------------------------


def test_extract_email_found():
    assert extract_email("Contact: jane.doe@example.com for details.") == "jane.doe@example.com"


def test_extract_email_none_when_absent():
    assert extract_email("No contact information listed here.") is None


def test_extract_email_strips_trailing_punctuation():
    assert extract_email("Reach me at jane.doe@example.com.") == "jane.doe@example.com"


# --- phone -------------------------------------------------------------------


def test_extract_phone_dashed_format():
    assert extract_phone("Phone: 415-555-0142") == "415-555-0142"


def test_extract_phone_parenthesized_format():
    assert extract_phone("Call (415) 555-0142 anytime.") == "(415) 555-0142"


def test_extract_phone_with_country_code():
    assert extract_phone("+1 415 555 0142") == "+1 415 555 0142"


def test_extract_phone_none_when_absent():
    assert extract_phone("No phone number on this resume.") is None


def test_extract_phone_does_not_mistake_year_range_for_phone():
    # "2018-2020" is 8 digits with a separator — digit-count-compatible
    # with a phone number, so this is checked explicitly, not assumed.
    assert extract_phone("Senior Engineer, Acme Corp, 2018-2020") is None


# --- name --------------------------------------------------------------------


def test_extract_name_from_first_line():
    assert extract_name("Jordan Ellis\nBackend Engineer\njordan@example.com") == "Jordan Ellis"


def test_extract_name_skips_section_heading_first_line():
    text = "RESUME\nJordan Ellis\nBackend Engineer"
    assert extract_name(text) == "Jordan Ellis"


def test_extract_name_strips_honorific_prefix():
    assert extract_name("Dr. Nkechi Obi\nn.obi@example.com") == "Nkechi Obi"


def test_extract_name_honorific_stripping_does_not_touch_similar_names():
    # "Erika" is not "Er" + a name — the honorific regex requires
    # whitespace (or a period then whitespace) immediately after the
    # honorific token, so it must not fire mid-word.
    assert extract_name("Erika Johnson\nerika@example.com") == "Erika Johnson"


def test_extract_name_stops_rather_than_accepting_a_job_title():
    # The real name is a single word ("Ravindran"), which the shape regex
    # (2-4 capitalized words) cannot match. Before the fix, the heuristic
    # kept scanning and wrongly accepted the job-title line below, which
    # happens to have the same 2-4-capitalized-word shape. Now it must
    # stop at the first candidate line's failure and fall through to the
    # spaCy fallback instead of ever considering "Network Support
    # Specialist" a candidate.
    text = "Ravindran\nravindran.k@example.com\nEXPERIENCE\nNetwork Support Specialist\nAcme Corp"
    result = extract_name(text)
    assert result != "Network Support Specialist"


def test_extract_name_spacy_fallback_when_no_clean_first_line():
    # No name-shaped first line (starts with a lowercase summary sentence) —
    # falls to spaCy PERSON detection within the first 500 characters.
    text = "experienced engineer named Priya Kapoor with a decade in backend systems."
    assert extract_name(text) == "Priya Kapoor"


def test_extract_name_none_when_nothing_found():
    text = "1234567890\nsome numbers and no identifiable person at all really"
    assert extract_name(text) is None


# --- education ---------------------------------------------------------------


def test_extract_education_bachelor():
    name, level = extract_education("EDUCATION\nBachelor of Science in Computer Science, 2019")
    assert name == "Bachelor's Degree"
    assert level == 3


def test_extract_education_master():
    name, level = extract_education("EDUCATION\nM.S. in Data Science, State University")
    assert name == "Master's Degree"
    assert level == 4


def test_extract_education_highest_level_wins():
    text = "EDUCATION\nBachelor of Science in Computer Science\nMaster of Business Administration (MBA)"
    name, level = extract_education(text)
    assert level == 4
    assert name == "Master's Degree"


def test_extract_education_none_when_absent():
    name, level = extract_education("No education section on this resume at all.")
    assert (name, level) == (None, None)


def test_extract_education_phd():
    name, level = extract_education("Ph.D. in Computer Science, 2015")
    assert level == 5
    assert name == "PhD"


def test_extract_education_bare_ba():
    name, level = extract_education("EDUCATION\nBA Graphic Communication, Northbrook College, 2018")
    assert level == 3
    assert name == "Bachelor's Degree"


def test_extract_education_bare_bs():
    name, level = extract_education("EDUCATION\nBS Computer Science, Fernwood College, 2019")
    assert level == 3


def test_extract_education_b_eng():
    name, level = extract_education("EDUCATION\nB.Eng. Information Science, Sagami Institute, 2015")
    assert level == 3


def test_extract_education_bare_diploma_maps_to_associate():
    name, level = extract_education("EDUCATION\nDiploma in Computer Networking, Government Polytechnic, 2021")
    assert level == 2
    assert name == "Associate Degree"


def test_extract_education_bare_bachelors_possessive():
    # Phase 6: job.education_requirement is free text like "Bachelor's" (no
    # trailing "degree") — this exact phrasing is what backend/scripts/seed.py
    # and the job fixtures across the test suite already use, so it must
    # resolve on the same ladder used for resume education.
    name, level = extract_education("Bachelor's")
    assert level == 3
    assert name == "Bachelor's Degree"


def test_extract_education_bare_masters_possessive():
    name, level = extract_education("Master's")
    assert level == 4
    assert name == "Master's Degree"


# --- experience years ---------------------------------------------------------

_AS_OF = date(2026, 8, 28)


def test_experience_single_role_with_present():
    text = "EXPERIENCE\nSenior Engineer, Acme Corp\nJan 2021 - Present"
    years = extract_experience_years(text, as_of=_AS_OF)
    # Jan 2021 through Aug 2026 inclusive = 68 months = 5.7 years.
    assert years == 5.7


def test_experience_returns_none_when_nothing_parses():
    text = "Experienced freelance designer. Skilled in Figma. No dates listed anywhere."
    assert extract_experience_years(text, as_of=_AS_OF) is None


def test_experience_never_returns_zero_for_unparseable_text():
    # A stronger form of the None check: sweep several date-free texts and
    # confirm none of them ever comes back as a false 0.0.
    texts = [
        "Skilled communicator with strong leadership abilities.",
        "",
        "References available upon request.",
    ]
    for text in texts:
        result = extract_experience_years(text, as_of=_AS_OF)
        assert result is None or result != 0.0


def test_experience_gap_between_roles_is_not_bridged():
    text = (
        "EXPERIENCE\n"
        "Engineer, X Corp\nJan 2015 - Dec 2016\n\n"
        "Engineer, Y Corp\nJan 2018 - Dec 2019\n"
    )
    # 2 years + 2 years, with a real 2017 gap that must NOT be counted.
    assert extract_experience_years(text, as_of=_AS_OF) == 4.0


def test_experience_contiguous_roles_are_merged_without_phantom_gap():
    text = (
        "EXPERIENCE\n"
        "Engineer, X Corp\nJan 2018 - Mar 2019\n\n"
        "Engineer, Y Corp\nApr 2019 - Mar 2020\n"
    )
    # 15 months + 12 months, contiguous (no day lost or invented) = 27 months = 2.25 -> 2.2.
    assert extract_experience_years(text, as_of=_AS_OF) == 2.2


def test_experience_year_only_range():
    text = "EXPERIENCE\nEngineer, Acme Corp\n2018 - 2020"
    # Jan 2018 - Dec 2020 inclusive = 36 months = 3.0 years.
    assert extract_experience_years(text, as_of=_AS_OF) == 3.0


def test_experience_scoped_to_experience_section_not_education():
    # A "2015-2019" college date range must not be counted as work experience
    # when a real EXPERIENCE section with its own dates exists.
    text = (
        "EDUCATION\nBachelor of Science, State University, 2015-2019\n\n"
        "EXPERIENCE\nEngineer, Acme Corp\nJan 2020 - Dec 2021\n"
    )
    assert extract_experience_years(text, as_of=_AS_OF) == 2.0


def test_experience_recognizes_appointments_heading():
    # A resume using academic/clinical-CV heading vocabulary must still
    # scope to just that section, not fall back to scanning the whole
    # resume (which would pick up EDUCATION's own dates too).
    text = (
        "EDUCATION\nPh.D. Epidemiology, State University, 2010 - 2014\n\n"
        "APPOINTMENTS\nSenior Research Fellow, Institute\n2018 - 2024\n"
        "Postdoctoral Researcher, University\n2014 - 2018\n"
    )
    assert extract_experience_years(text, as_of=_AS_OF) == 11.0


def test_experience_recognizes_positions_and_career_history_headings():
    assert extract_experience_years(
        "POSITIONS\nEngineer, Acme Corp\nJan 2020 - Dec 2021\n", as_of=_AS_OF
    ) == 2.0
    assert extract_experience_years(
        "CAREER HISTORY\nEngineer, Acme Corp\nJan 2020 - Dec 2021\n", as_of=_AS_OF
    ) == 2.0


# --- projects / certifications -------------------------------------------------


def test_extract_projects_from_section():
    text = "PROJECTS\nPersonal Finance Tracker\n- React and Node.js app.\n\nCERTIFICATIONS\nAWS Certified"
    projects = extract_projects(text)
    assert "Personal Finance Tracker" in projects
    assert "AWS Certified" not in projects


def test_extract_certifications_from_section():
    text = "CERTIFICATIONS\nAWS Certified Solutions Architect\nPMP\n\nPROJECTS\nSomething else"
    certs = extract_certifications(text)
    assert certs == ["AWS Certified Solutions Architect", "PMP"]


def test_extract_projects_empty_when_no_section():
    assert extract_projects("No projects section here.") == []


def test_extract_certifications_empty_when_no_section():
    assert extract_certifications("No certifications section here.") == []


# --- experience_section_text / date_ranges / heading_word (Phase 8 grounding-filter fix) ---


def test_extract_experience_section_text_returns_section_body():
    text = "EXPERIENCE\nSenior Engineer\nAcme Corp | 2019 - 2022\n\nEDUCATION\nB.S. Computer Science"
    section = extract_experience_section_text(text)
    assert section is not None
    assert "Senior Engineer" in section
    assert "B.S. Computer Science" not in section


def test_extract_experience_section_text_none_when_no_heading():
    assert extract_experience_section_text("No headings anywhere in this resume.") is None


def test_find_date_ranges_matches_a_range():
    matches = find_date_ranges("Senior Engineer at Acme Corp | Sep 2019 - Dec 2022")
    assert len(matches) == 1
    assert matches[0].group(0) == "Sep 2019 - Dec 2022"


def test_find_date_ranges_matches_numeric_and_present():
    matches = find_date_ranges("07/2021 - Present")
    assert len(matches) == 1


def test_find_date_ranges_empty_when_no_range():
    assert find_date_ranges("A line with no dates in it at all.") == []


def test_is_heading_word_matches_case_insensitively():
    assert is_heading_word("EXPERIENCE")
    assert is_heading_word("experience")
    assert is_heading_word("Education")


def test_is_heading_word_false_for_ordinary_word():
    assert not is_heading_word("python")
    assert not is_heading_word("corvid")
