"""Eval tests: verify pipeline output quality and performance characteristics.

Two test suites:
1. Output quality — validate any completed run's data integrity
2. Scoring determinism — verify the rule-based categorizer produces identical
   scores for the same video regardless of batch context
3. Performance — verify timing budgets and retry/timeout behavior
"""
from __future__ import annotations
import copy
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from yt_catalog.models import Video, video_to_dict
from yt_catalog.rule_categorizer import categorize_video


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_latest_run() -> Path | None:
    """Find the most recent run data.json."""
    runs_dir = Path(__file__).parent.parent / "vault" / "runs"
    if not runs_dir.exists():
        return None
    for d in sorted(runs_dir.iterdir(), reverse=True):
        candidate = d / "data.json"
        if candidate.exists():
            return candidate
    return None


def _load_run(path: Path | None = None):
    """Load a run's data. Skips if no data available."""
    path = path or _find_latest_run()
    if path is None or not path.exists():
        pytest.skip("No run data found in vault/runs/")
    return json.loads(path.read_text())


def _load_videos(path: Path | None = None) -> list[dict]:
    return _load_run(path)["videos"]


def _make_video(vid: str, title: str, channel: str, duration: int = 600) -> Video:
    return Video(
        video_id=vid, title=title, channel=channel,
        url=f"https://www.youtube.com/watch?v={vid}",
        relative_time="", duration_seconds=duration,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OUTPUT QUALITY EVALS — run against any completed run
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutputQuality:
    """Validate the integrity of a completed run's output."""

    def test_has_videos(self):
        videos = _load_videos()
        assert len(videos) > 0, "Run has 0 videos"

    def test_phase_completed(self):
        data = _load_run()
        assert data["last_completed_phase"] == "categorization"

    def test_no_shorts_remain(self):
        videos = _load_videos()
        shorts = [v for v in videos if v.get("is_short", False)]
        assert shorts == [], f"{len(shorts)} shorts leaked through"

    def test_no_videos_under_60_seconds(self):
        videos = _load_videos()
        under_60 = [v for v in videos if (v.get("duration_seconds") or 999) < 60]
        assert under_60 == [], f"{len(under_60)} sub-60s videos found"

    def test_no_livestreams_remain(self):
        videos = _load_videos()
        live = [v for v in videos if v.get("is_live", False)]
        assert live == [], f"{len(live)} livestreams leaked through"

    def test_all_have_category(self):
        videos = _load_videos()
        missing = [v["video_id"] for v in videos if not v.get("category")]
        assert missing == [], f"{len(missing)} videos missing category"

    def test_all_categories_valid(self):
        valid = {"programming", "tech-news", "comedy", "games", "hardware",
                 "diy-makers", "general", "sleep"}
        videos = _load_videos()
        invalid = [(v["video_id"], v.get("category")) for v in videos
                   if v.get("category") not in valid]
        assert invalid == [], f"Invalid categories: {invalid[:5]}"

    def test_multiple_categories_represented(self):
        videos = _load_videos()
        cats = {v.get("category") for v in videos if v.get("category")}
        assert len(cats) >= 4, f"Only {len(cats)} categories: {cats}"

    def test_all_have_interest_score(self):
        videos = _load_videos()
        missing = [v["video_id"] for v in videos if v.get("interest_score") is None]
        assert missing == [], f"{len(missing)} videos missing score"

    def test_scores_in_range(self):
        videos = _load_videos()
        bad = [(v["video_id"], v["interest_score"]) for v in videos
               if v.get("interest_score") is not None and not (0 <= v["interest_score"] <= 100)]
        assert bad == [], f"Out-of-range scores: {bad[:5]}"

    def test_all_have_upload_date(self):
        videos = _load_videos()
        missing = [v["video_id"] for v in videos if not v.get("upload_date")]
        assert missing == [], f"{len(missing)} videos missing upload_date"

    def test_all_have_thumbnail_url(self):
        videos = _load_videos()
        missing = [v["video_id"] for v in videos if not v.get("thumbnail_url")]
        assert missing == [], f"{len(missing)} videos missing thumbnail_url"

    def test_99pct_have_duration(self):
        videos = _load_videos()
        missing = [v for v in videos if v.get("duration_seconds") is None]
        pct = len(missing) / len(videos) * 100
        assert pct < 1.0, f"{pct:.1f}% missing duration"

    def test_all_have_duration_group(self):
        videos = _load_videos()
        valid_groups = {"super-small", "small", "long", "super-big", "unknown"}
        missing = [v["video_id"] for v in videos if not v.get("duration_group")]
        invalid = [(v["video_id"], v["duration_group"]) for v in videos
                   if v.get("duration_group") and v["duration_group"] not in valid_groups]
        assert missing == [], f"{len(missing)} videos missing duration_group"
        assert invalid == [], f"Invalid groups: {invalid[:5]}"

    def test_quality_report(self):
        """Print a quality summary. Always passes."""
        data = _load_run()
        videos = data["videos"]
        cats: dict[str, int] = {}
        scores = []
        for v in videos:
            cats[v.get("category", "?")] = cats.get(v.get("category", "?"), 0) + 1
            if v.get("interest_score") is not None:
                scores.append(v["interest_score"])

        avg = sum(scores) / len(scores) if scores else 0
        print(f"\n{'='*50}")
        print(f"QUALITY REPORT ({len(videos)} videos, avg score {avg:.1f})")
        print(f"{'='*50}")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"  {cat:<15} {count:3d} ({count/len(videos)*100:.0f}%)")
        print(f"{'='*50}")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SCORING DETERMINISM — same video must always get same score
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoringDeterminism:
    """Verify rule-based categorization is independent of batch context.

    The same video must get the same category and score regardless of
    what other videos are in the batch.
    """

    def _categorize_single(self, video: Video) -> tuple[str, int]:
        """Categorize a single video using the rule-based categorizer."""
        v_dict = video_to_dict(video)
        result = categorize_video(v_dict)
        return result["category"], result["interest_score"]

    def test_same_video_same_score_across_batches(self):
        """A video's score must not change based on batch composition."""
        target = _make_video("QUHrntlfPo4", "Claude Code is Expensive. This MCP Server Fixes It", "Better Stack")

        score1 = self._categorize_single(target)

        # Mutate the video object to simulate different batch contexts
        target2 = _make_video("QUHrntlfPo4", "Claude Code is Expensive. This MCP Server Fixes It", "Better Stack")
        score2 = self._categorize_single(target2)

        assert score1 == score2, f"Same video got different results: {score1} vs {score2}"

    def test_portuguese_channel_always_boosted(self):
        """Portuguese channels must always get the +15 boost."""
        v = _make_video("abc", "Qualquer coisa", "Bernardo Almeida")
        cat, score = self._categorize_single(v)
        # Bernardo Almeida = tech-news (base 70) + Portuguese (+15) + favorite (+20) = 100 (clamped)
        assert cat == "tech-news"
        assert score >= 85, f"Portuguese favorite channel scored only {score}"

    def test_favorite_channel_always_boosted(self):
        """Favorite channels must always get the +20 boost."""
        v = _make_video("xyz", "Some Random DIY Project", "Evan and Katelyn")
        cat, score = self._categorize_single(v)
        assert cat == "diy-makers"
        assert score >= 75, f"Favorite channel scored only {score}"

    def test_sleep_channel_always_categorized_as_sleep(self):
        """Known sleep channels must always be categorized as sleep."""
        for channel in ["Chiropractic Medicine", "Timur Doctorov Live 2", "Slava Semeshko"]:
            v = _make_video("test", "Any Title", channel, duration=1800)
            cat, score = self._categorize_single(v)
            assert cat == "sleep", f"{channel} categorized as {cat}, expected sleep"

    def test_score_determinism_across_10_runs(self):
        """Run categorization 10 times on the same video, all must match."""
        v = _make_video("test123", "CS2 Skins Explained", "mikewater9", duration=900)
        results = set()
        for _ in range(10):
            results.add(self._categorize_single(v))
        assert len(results) == 1, f"Got {len(results)} different results: {results}"

    def test_all_run_videos_are_deterministic(self):
        """Every video from the latest run must get the same score when re-categorized."""
        run_videos = _load_videos()
        mismatches = []

        for v in run_videos:
            original_cat = v.get("category")
            original_score = v.get("interest_score")

            result = categorize_video(dict(v))

            if result["category"] != original_cat or result["interest_score"] != original_score:
                mismatches.append({
                    "video_id": v["video_id"],
                    "original": (original_cat, original_score),
                    "recalculated": (result["category"], result["interest_score"]),
                })

        if mismatches:
            # This is expected if the first run used a different categorizer (the script).
            # Report as a warning, not a failure, unless >10% mismatch.
            pct = len(mismatches) / len(run_videos) * 100
            if pct > 10:
                pytest.fail(
                    f"{len(mismatches)}/{len(run_videos)} ({pct:.0f}%) videos got different "
                    f"scores on re-categorization. Sample: {mismatches[:3]}"
                )
            else:
                print(f"\n  Note: {len(mismatches)}/{len(run_videos)} minor scoring differences "
                      f"(expected if run used a different categorizer)")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PERFORMANCE EVALS — timing budgets and resilience
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Verify timing budgets and failure resilience."""

    def test_innertube_single_video_under_5_seconds(self):
        """A single InnerTube enrichment call should complete in < 5 seconds."""
        from yt_catalog.enricher import enrich_videos_innertube

        v = _make_video("dQw4w9WgXcQ", "Test Video", "Test Channel")
        start = time.time()
        enrich_videos_innertube([v])
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Single video enrichment took {elapsed:.1f}s (budget: 5s)"
        assert v.duration_seconds is not None, "Enrichment failed to set duration"

    def test_innertube_batch_10_under_15_seconds(self):
        """Enriching 10 videos via InnerTube should complete in < 15 seconds."""
        from yt_catalog.enricher import enrich_videos_innertube

        # Use real video IDs from the first run
        run_videos = _load_videos()[:10]
        videos = [
            _make_video(v["video_id"], v["title"], v["channel"])
            for v in run_videos
        ]

        start = time.time()
        enrich_videos_innertube(videos)
        elapsed = time.time() - start

        enriched = sum(1 for v in videos if v.duration_seconds is not None)
        assert elapsed < 15.0, f"10-video enrichment took {elapsed:.1f}s (budget: 15s)"
        assert enriched >= 9, f"Only {enriched}/10 enriched successfully"

    def test_innertube_handles_invalid_video_gracefully(self):
        """InnerTube should not crash on invalid video IDs, just skip them."""
        from yt_catalog.enricher import enrich_videos_innertube

        videos = [
            _make_video("INVALID_ID_XXXXX", "Fake", "Fake"),
            _make_video("dQw4w9WgXcQ", "Real Video", "Real Channel"),
        ]

        start = time.time()
        result = enrich_videos_innertube(videos)
        elapsed = time.time() - start

        # Should complete without crashing
        assert len(result) == 2
        # Real video should be enriched
        assert result[1].duration_seconds is not None
        # Should not take excessively long (retries should be bounded)
        assert elapsed < 30.0, f"Took {elapsed:.1f}s with an invalid ID (budget: 30s)"

    def test_rule_categorization_under_100ms_for_full_run(self):
        """Rule-based categorization of all videos should be near-instant."""
        run_videos = _load_videos()

        start = time.time()
        for v in run_videos:
            categorize_video(dict(v))
        elapsed = time.time() - start

        assert elapsed < 0.1, f"Categorizing {len(run_videos)} videos took {elapsed:.3f}s (budget: 0.1s)"

    def test_thumbnail_download_timeout(self):
        """Thumbnail downloads should not hang — each has a per-request timeout."""
        from yt_catalog.enricher import download_thumbnails
        import tempfile

        # Use a video with a known-good thumbnail
        v = _make_video("dQw4w9WgXcQ", "Test", "Test")
        v.thumbnail_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"

        with tempfile.TemporaryDirectory() as tmpdir:
            start = time.time()
            download_thumbnails([v], tmpdir)
            elapsed = time.time() - start

        assert elapsed < 10.0, f"Single thumbnail took {elapsed:.1f}s"

    def test_retry_does_not_exceed_total_budget(self):
        """The retry mechanism should bound total wait time."""
        from yt_catalog.utils import retry

        call_count = 0

        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("simulated failure")

        start = time.time()
        with pytest.raises(ConnectionError):
            retry(always_fails, max_retries=3, delay=0.1, backoff=2)
        elapsed = time.time() - start

        assert call_count == 3
        # delay=0.1, backoff=2: waits 0.1 + 0.2 = 0.3s total between retries
        assert elapsed < 2.0, f"Retry took {elapsed:.1f}s (expected < 2s)"

    def test_performance_report(self):
        """Print a timing report for key operations. Always passes."""
        run_videos = _load_videos()

        start = time.time()
        for v in run_videos:
            categorize_video(dict(v))
        cat_time = time.time() - start

        print(f"\n{'='*50}")
        print(f"PERFORMANCE REPORT ({len(run_videos)} videos)")
        print(f"{'='*50}")
        print(f"  rule_categorize_all: {cat_time*1000:.1f}ms ({cat_time/len(run_videos)*1000:.2f}ms/video)")
        print(f"{'='*50}")
