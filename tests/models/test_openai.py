from types import SimpleNamespace

import models.openai as openai_module
from models.openai import OpenAILLM


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.outputs.pop(0))


class FakeOpenAIClient:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


def make_llm(monkeypatch, outputs):
    client = FakeOpenAIClient(outputs)
    monkeypatch.setattr(openai_module, "OpenAI", lambda: client)
    return OpenAILLM(), client


def test_analyze_document_sends_pdf_with_responses_api(monkeypatch, tmp_path):
    llm, client = make_llm(
        monkeypatch,
        [
            """---
TITLE: 2024 Tax Form
SUGGESTED_PATH: Taxes/2024
CONFIDENCE: 9
YEAR: 2024
DATE: 2025-01
ENTITY: IRS
SUMMARY: Tax form for the 2024 reporting year.
---"""
        ],
    )
    pdf_path = tmp_path / "tax-form.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test content")

    result = llm.analyze_document(
        pdf_path=str(pdf_path),
        layout="- Taxes\n  - By year",
        path_validator=lambda path: path == "Taxes/2024",
    )

    assert result is not None
    assert result.title == "2024 Tax Form"
    assert result.suggested_path == "Taxes/2024"

    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.5"

    content = call["input"][0]["content"]
    assert content[0]["type"] == "input_file"
    assert content[0]["filename"] == "tax-form.pdf"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert content[1]["type"] == "input_text"
    assert "SUGGESTED_PATH" in content[1]["text"]


def test_text_helpers_use_gpt_55_responses_api(monkeypatch):
    llm, client = make_llm(
        monkeypatch,
        [
            "MATCH",
            "DUPLICATE: JPMorgan | JP Morgan",
            "MATCH: Goldman Sachs",
        ],
    )

    assert llm.compare_names("JPMorgan", "J.P. Morgan") is True
    assert llm.find_duplicate_pair(["JPMorgan", "JP Morgan", "Chase"]) == (
        "JPMorgan",
        "JP Morgan",
    )
    assert llm.find_matching_folder("GS", ["Goldman Sachs", "Chase"]) == "Goldman Sachs"

    assert len(client.responses.calls) == 3
    for call in client.responses.calls:
        assert call["model"] == "gpt-5.5"
        content = call["input"][0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "input_text"
        assert content[0]["text"]
