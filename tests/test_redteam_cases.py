"""Offline checks for the F1/F5 attack cases. No Gemini, no network.

Run from the project root:  python -m tests.test_redteam_cases
Asserts only what parse_email does with each .eml: whether it is dropped, and for the
F5 split cases exactly which hidden copies reach the text the agent sends to Gemini.
"""
from pathlib import Path

from app.email_client import parse_email  # pulls in app.config + app.models only; no network

CASES = Path(__file__).resolve().parent.parent / "redteam" / "cases"

NEW_F1 = [
    "f1b_fake_system_header",
    "f1c_quoted_reply_chain",
    "f1d_sinhala",
    "f1e_base64_decode",
    "f1f_roleplay",
]
F5 = ["f5a_hidden_html_clean_plain", "f5b_html_only_hidden_div", "f5c_plain_html_split"]


def _parse(stem: str):
    return parse_email((CASES / f"{stem}.eml").read_bytes())


def test_all_new_cases_are_not_dropped():
    for stem in NEW_F1 + F5:
        assert _parse(stem) is not None, f"{stem} was dropped by parse_email"


def test_f5a_control_hidden_html_never_reaches_model():
    # multipart/alternative: get_body prefers text/plain, so the HTML directive is never read.
    text = _parse("f5a_hidden_html_clean_plain").text
    assert "DIRECTIVE_DIV" not in text
    assert "DIRECTIVE_COMMENT" not in text


def test_f5b_hidden_div_and_span_survive_comment_stripped():
    text = _parse("f5b_html_only_hidden_div").text
    assert "DIRECTIVE_DIV" in text, "display:none div text should survive the tag-strip regex"
    assert "DIRECTIVE_SPAN" in text, "font-size:0 span text should survive the tag-strip regex"
    comment_survived = "DIRECTIVE_COMMENT" in text
    assert not comment_survived, "HTML comment should be removed by the tag-strip regex"
    print(f"    f5b: HTML-comment copy survived? {comment_survived}  (div+span reached the model)")


def test_f5c_plain_part_directive_reaches_model():
    # multipart/alternative: the owner sees the clean HTML, the agent reads the plain part.
    text = _parse("f5c_plain_html_split").text
    assert "DIRECTIVE_PLAIN" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
