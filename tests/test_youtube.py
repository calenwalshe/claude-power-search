"""Tests for YouTube provider utilities."""

from power_search.providers.youtube import (
    YOUTUBE_URL_RE,
    _build_prompt,
    _extract_text,
)


class TestYouTubeUrlParsing:
    def test_standard_url(self):
        m = YOUTUBE_URL_RE.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert m and m.group(1) == "dQw4w9WgXcQ"

    def test_short_url(self):
        m = YOUTUBE_URL_RE.search("https://youtu.be/dQw4w9WgXcQ")
        assert m and m.group(1) == "dQw4w9WgXcQ"

    def test_no_protocol(self):
        m = YOUTUBE_URL_RE.search("youtube.com/watch?v=abc123def45")
        assert m and m.group(1) == "abc123def45"

    def test_non_youtube_url(self):
        m = YOUTUBE_URL_RE.search("https://example.com/watch?v=abc")
        assert m is None

    def test_embedded_in_text(self):
        m = YOUTUBE_URL_RE.search("check out https://www.youtube.com/watch?v=test1234567 please")
        assert m and m.group(1) == "test1234567"


class TestBuildPrompt:
    def test_summary_mode(self):
        p = _build_prompt("summary", "query", "https://youtube.com/watch?v=x")
        assert "Summarize" in p

    def test_transcript_mode(self):
        p = _build_prompt("transcript", "query", "https://youtube.com/watch?v=x")
        assert "transcript" in p.lower()
        assert "timestamp" in p.lower()

    def test_analyze_mode(self):
        p = _build_prompt("analyze", "analyze the coding parts", "")
        assert "Analyze" in p
        assert "coding parts" in p


class TestExtractText:
    def test_single_part(self):
        data = {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}
        assert _extract_text(data) == "hello"

    def test_multiple_parts(self):
        data = {"candidates": [{"content": {"parts": [
            {"text": "line 1"},
            {"text": "line 2"},
        ]}}]}
        assert _extract_text(data) == "line 1\nline 2"

    def test_empty_response(self):
        data = {"candidates": [{}]}
        assert _extract_text(data) == ""
