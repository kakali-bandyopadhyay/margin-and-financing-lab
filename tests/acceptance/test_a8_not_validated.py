"""A8: the model document discloses its validation status and has its required outline."""

from pathlib import Path


MODEL_DOC = Path(__file__).parents[2] / "docs" / "MODEL_DOC.md"
NOT_VALIDATED = (
    "This model has not been independently validated and must not be used for decisions "
    "without independent validation and Treasury, Risk and Legal review."
)


def test_model_doc_status_sentence_and_heading_order():
    assert MODEL_DOC.is_file()
    document = MODEL_DOC.read_text(encoding="utf-8")
    assert document.count(NOT_VALIDATED) == 1

    expected = [
        "## 0 Document control",
        "## 1 Purpose and intended use",
        "## 2 Model overview and boundary",
        "## 3 Data",
        "## 4 Assumptions and parameters",
        "## 5 Methodology",
        "## 6 Implementation",
        "## 7 Conceptual soundness",
        "## 8 Benchmarking (sanity only)",
        "## 9 Outcomes analysis",
        "## 10 Sensitivity analysis",
        "## 11 Limitations",
        "## 12 Validation status",
        "## 13 Use controls and monitoring (proposed)",
        "## 14 Change log",
    ]
    numbered_headings = [
        line for line in document.splitlines() if line.startswith("## ")
    ][:15]
    assert numbered_headings == expected
