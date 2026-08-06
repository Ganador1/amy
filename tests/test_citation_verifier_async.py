"""Hermetic tests for bounded asynchronous citation verification."""

import asyncio
import json
import threading

from communication.citation_verifier import CitationVerifier


def test_author_year_candidate_is_not_overstated_as_verified(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1000/example",
                                "title": ["A candidate publication"],
                                "author": [{"family": "Smith"}],
                                "issued": {"date-parts": [[2020, 6, 1]]},
                            }
                        ]
                    }
                }
            ).encode()

    requested_urls = []

    def _urlopen(request, timeout):
        requested_urls.append(request.full_url)
        assert timeout == 3
        return _Response()

    monkeypatch.setattr(
        "communication.citation_verifier.urllib.request.urlopen",
        _urlopen,
    )
    result = CitationVerifier(request_timeout=3).verify_author_year(
        "Smith et al. (2020)"
    )

    assert result["verified"] is False
    assert result["candidate_match"] is True
    assert result["doi"] == "10.1000/example"
    assert "ambiguous" in result["note"]
    assert "query.author=Smith" in requested_urls[0]


async def test_async_citation_verification_runs_requests_concurrently(monkeypatch):
    verifier = CitationVerifier(
        request_timeout=1,
        total_timeout=1,
        max_concurrency=3,
    )
    release = threading.Event()
    state_lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def _verify(raw):
        with state_lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        release.wait(timeout=1)
        with state_lock:
            state["active"] -= 1
        return {"verified": True, "title": raw}

    monkeypatch.setattr(verifier, "verify_author_year", _verify)
    task = asyncio.create_task(
        verifier.verify_citations_async(
            "Smith (2020), Jones (2021), and Brown (2022)"
        )
    )

    for _ in range(100):
        with state_lock:
            if state["max_active"] >= 3:
                break
        await asyncio.sleep(0.005)
    release.set()
    result = await task

    assert state["max_active"] == 3
    assert result["verified"] == 3
    assert result["all_verified"] is True


async def test_async_citation_verification_has_a_batch_deadline(monkeypatch):
    verifier = CitationVerifier(
        request_timeout=1,
        total_timeout=0.02,
        max_concurrency=1,
    )
    release = threading.Event()

    def _verify(_raw):
        release.wait(timeout=0.2)
        return {"verified": True}

    monkeypatch.setattr(verifier, "verify_author_year", _verify)
    result = await verifier.verify_citations_async(
        "Smith (2020) and Jones (2021)"
    )
    release.set()

    assert result["verified"] == 0
    assert result["all_verified"] is False
    assert all(
        "deadline exceeded" in citation["details"]["note"]
        for citation in result["citations"]
    )


async def test_async_citation_verification_reuses_cached_results(monkeypatch):
    verifier = CitationVerifier(total_timeout=1)
    calls = 0

    def _verify(_raw):
        nonlocal calls
        calls += 1
        return {"verified": True}

    monkeypatch.setattr(verifier, "verify_author_year", _verify)
    first = await verifier.verify_citations_async("Smith (2020)")
    second = await verifier.verify_citations_async("Smith (2020)")

    assert first["all_verified"] is True
    assert second["all_verified"] is True
    assert calls == 1


async def test_async_citation_verification_propagates_cancellation(monkeypatch):
    verifier = CitationVerifier(total_timeout=60, max_concurrency=1)
    started = threading.Event()
    release = threading.Event()

    def _verify(_raw):
        started.set()
        release.wait(timeout=1)
        return {"verified": True}

    monkeypatch.setattr(verifier, "verify_author_year", _verify)
    task = asyncio.create_task(
        verifier.verify_citations_async("Smith (2020) and Jones (2021)")
    )
    for _ in range(100):
        if started.is_set():
            break
        await asyncio.sleep(0.005)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("citation verification swallowed cancellation")
    finally:
        release.set()
