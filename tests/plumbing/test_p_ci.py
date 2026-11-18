from pathlib import Path


def test_ci_workflow_contains_required_configuration():
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"

    assert workflow_path.is_file()
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "python -m pytest -W error -q" in workflow
    assert "mfl.cli run --seed 42" in workflow
    assert 'python-version: ["3.11", "3.14"]' in workflow
    assert "permissions:" in workflow
    assert "contents: read" in workflow
