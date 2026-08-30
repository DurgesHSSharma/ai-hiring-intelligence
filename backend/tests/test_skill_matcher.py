"""Phase 5 acceptance (Phases.md): the word-boundary cases from PRD F4.2
are covered by unit tests and pass. Exercises the real skills.json
dictionary, not a fabricated stand-in — these are the literal terms a
false-positive/false-negative would show up on in production.
"""
from app.core.enums import SkillSource, SkillType
from app.ml.skills.skill_matcher import match_skills


def _canonicals(text: str) -> set[str]:
    return {m.canonical for m in match_skills(text)}


# --- the exact PRD F4.2 boundary cases -----------------------------------


def test_r_does_not_match_inside_react():
    assert "R" not in _canonicals("Experienced in React and Redux development.")


def test_r_matches_as_standalone_word():
    assert "R" in _canonicals("I write R for statistical analysis.")


def test_go_does_not_match_inside_google():
    assert "Go" not in _canonicals("Built scalable systems using Google Cloud.")


def test_go_matches_as_standalone_word():
    assert "Go" in _canonicals("I write Go microservices daily.")


def test_c_does_not_match_inside_cpp():
    assert "C" not in _canonicals("Systems programming in C++ for embedded devices.")


def test_c_does_not_match_inside_csharp():
    assert "C" not in _canonicals("Backend services written in C#.")


def test_c_matches_as_standalone_word():
    assert "C" in _canonicals("Wrote device drivers in C for the kernel.")


def test_dotnet_matches_despite_leading_period():
    assert ".NET" in _canonicals("Built APIs on .NET 8 and deployed to Azure.")


def test_csharp_matches_despite_hash():
    assert "C#" in _canonicals("Five years of experience with C# and ASP.NET.")


def test_nodejs_matches_dotted_form():
    assert "Node.js" in _canonicals("Backend built with Node.js and Express.")


def test_nodejs_matches_undotted_form():
    assert "Node.js" in _canonicals("Backend built with NodeJS and Express.")


def test_cpp_itself_still_matches():
    assert "C++" in _canonicals("Systems programming in C++ for embedded devices.")


# --- alias resolution and type tagging (F4.1/F4.3) ------------------------


def test_alias_resolves_to_canonical_name():
    matches = match_skills("Comfortable with sklearn and pandas pipelines.")
    canonicals = {m.canonical for m in matches}
    assert "scikit-learn" in canonicals
    assert "Pandas" in canonicals


def test_case_insensitive_matching():
    assert "Python" in _canonicals("Wrote scripts in PYTHON and python3.")


def test_multiple_aliases_of_same_skill_dedupe_to_one_match():
    matches = [m for m in match_skills("Skilled in JS... no wait, JavaScript, and ECMAScript.") if m.canonical == "JavaScript"]
    # "js" is deliberately not an alias (see skills.json build notes — it
    # collides with Node.js/Vue.js/etc.), so only the last two count here.
    assert len(matches) == 1


def test_all_four_skill_types_are_represented_in_the_dictionary():
    text = (
        "Python developer, proficient with Docker, strong communication skills, "
        "background in healthcare."
    )
    matches = match_skills(text)
    types_found = {m.skill_type for m in matches}
    assert types_found == {SkillType.TECHNICAL, SkillType.TOOL, SkillType.SOFT, SkillType.DOMAIN}


def test_every_match_is_dictionary_sourced_in_phase_5():
    # Semantic fallback (F4.4) doesn't exist until Phase 7.
    matches = match_skills("Python, Docker, communication, healthcare.")
    assert matches
    assert all(m.source == SkillSource.DICTIONARY for m in matches)


def test_empty_text_returns_no_matches():
    assert match_skills("") == []


def test_no_matching_skills_returns_empty_list():
    assert match_skills("The quick brown fox jumps over the lazy dog.") == []
