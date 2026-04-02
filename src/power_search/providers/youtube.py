"""YouTube provider — Gemini-native video processing + Tavily search."""

from __future__ import annotations

import re
import requests

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"
)

# Gemini Flash pricing for video: ~$0.02-0.05 per 15-min video
# 8 hours free/day on free tier
COST_PER_VIDEO_SUMMARY = 0.01  # conservative estimate for summary
COST_PER_VIDEO_TRANSCRIPT = 0.03  # transcript generates more output tokens


class GeminiYouTubeProvider:
    """Process YouTube videos natively through Gemini's FileData support.

    Handles two intents:
    - YOUTUBE_VIDEO: given a URL, get transcript/summary via Gemini
    - YOUTUBE: search for videos (Tavily) then summarize top results (Gemini)
    """

    name = "gemini_youtube"
    intents = [Intent.YOUTUBE_VIDEO, Intent.YOUTUBE]

    def available(self) -> bool:
        return get_config().get_key("GEMINI_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        if intent == Intent.YOUTUBE_VIDEO or YOUTUBE_URL_RE.search(query):
            return self._process_video(query, intent, **kwargs)
        return self._search_and_summarize(query, intent, **kwargs)

    def _process_video(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        """Pass a YouTube URL to Gemini for transcript/summary."""
        api_key = get_config().require_key("GEMINI_API_KEY")
        model = kwargs.get("model", "gemini-2.5-flash")

        # Extract URL from query
        match = YOUTUBE_URL_RE.search(query)
        if match:
            video_id = match.group(1)
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            video_url = query.strip()
            video_id = None

        mode = kwargs.get("mode", "summary")  # "summary", "transcript", "analyze"
        prompt = _build_prompt(mode, query, video_url)

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"fileData": {"fileUri": video_url, "mimeType": "video/*"}},
                    ]
                }]
            },
            timeout=120,  # video processing can be slow
        )
        resp.raise_for_status()
        data = resp.json()

        content = _extract_text(data)
        usage_data = data.get("usageMetadata", {})
        tokens_in = usage_data.get("promptTokenCount", 0)
        tokens_out = usage_data.get("candidatesTokenCount", 0)
        cost = (tokens_in * 0.30 / 1_000_000) + (tokens_out * 2.50 / 1_000_000)

        return SearchResult(
            content=content,
            provider=self.name,
            cost=cost,
            intent=intent,
            query=query,
            sources=[video_url],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata={"video_id": video_id, "mode": mode},
        )

    def _search_and_summarize(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        """Search YouTube via Tavily, then summarize top results with Gemini."""
        api_key = get_config().require_key("GEMINI_API_KEY")
        tavily_key = get_config().get_key("TAVILY_API_KEY")

        # Step 1: Find videos
        videos = self._find_videos(query, tavily_key)
        if not videos:
            return SearchResult(
                content="No YouTube videos found for this query.",
                provider=self.name,
                cost=0.016 if tavily_key else 0.036,  # tavily or grounded search cost
                intent=intent,
                query=query,
            )

        # Step 2: Summarize top videos with Gemini
        model = kwargs.get("model", "gemini-2.5-flash")
        max_videos = kwargs.get("max_videos", 3)
        top_videos = videos[:max_videos]

        results_text = []
        total_cost = 0.016 if tavily_key else 0.036  # search cost
        total_tokens_in = 0
        total_tokens_out = 0
        sources = []

        for video in top_videos:
            url = video["url"]
            title = video.get("title", "")
            sources.append(url)

            try:
                resp = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{
                            "parts": [
                                {"text": f"Summarize the key points of this YouTube video in 3-5 bullet points. Include any notable quotes or insights."},
                                {"fileData": {"fileUri": url, "mimeType": "video/*"}},
                            ]
                        }]
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()

                summary = _extract_text(data)
                usage_data = data.get("usageMetadata", {})
                t_in = usage_data.get("promptTokenCount", 0)
                t_out = usage_data.get("candidatesTokenCount", 0)
                vid_cost = (t_in * 0.30 / 1_000_000) + (t_out * 2.50 / 1_000_000)

                total_cost += vid_cost
                total_tokens_in += t_in
                total_tokens_out += t_out

                results_text.append(f"## {title}\n{url}\n\n{summary}\n")
            except Exception as e:
                results_text.append(f"## {title}\n{url}\n\n*Could not process video: {e}*\n")

        return SearchResult(
            content="\n".join(results_text),
            provider=self.name,
            cost=total_cost,
            intent=intent,
            query=query,
            sources=sources,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            metadata={"videos_found": len(videos), "videos_summarized": len(top_videos)},
        )

    def _find_videos(self, query: str, tavily_key: str | None) -> list[dict]:
        """Find YouTube videos — prefers Tavily, falls back to Gemini grounded search."""
        if tavily_key:
            return self._find_via_tavily(query, tavily_key)
        return self._find_via_gemini_grounded(query)

    def _find_via_tavily(self, query: str, api_key: str) -> list[dict]:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        results = client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_domains=["youtube.com"],
            include_raw_content=False,
        )
        return [
            {"url": r["url"], "title": r.get("title", ""), "snippet": r.get("content", "")}
            for r in results.get("results", [])
        ]

    def _find_via_gemini_grounded(self, query: str) -> list[dict]:
        """Fallback: use Gemini grounded search to find YouTube videos."""
        api_key = get_config().require_key("GEMINI_API_KEY")
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": f"Find the top 5 YouTube videos about: {query}. Return each as a title and URL."}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract YouTube URLs from grounding chunks
        videos = []
        grounding = data.get("candidates", [{}])[0].get("groundingMetadata", {})
        for chunk in grounding.get("groundingChunks", []):
            web = chunk.get("web", {})
            uri = web.get("uri", "")
            if "youtube.com" in uri or "youtu.be" in uri:
                videos.append({"url": uri, "title": web.get("title", ""), "snippet": ""})
        return videos


def _build_prompt(mode: str, query: str, video_url: str) -> str:
    """Build the Gemini prompt based on the requested mode."""
    if mode == "transcript":
        return "Provide a detailed transcript of this video with timestamps. Format each line as [MM:SS] text."
    if mode == "analyze":
        extra = query.replace(video_url, "").strip()
        base = "Analyze this video in detail."
        if extra:
            base += f" Focus on: {extra}"
        return base
    # Default: summary
    return "Summarize this video. Include: main topic, key points (as bullets), notable quotes, and takeaways."


def _extract_text(data: dict) -> str:
    """Extract text from Gemini response."""
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "\n".join(p["text"] for p in parts if "text" in p)
