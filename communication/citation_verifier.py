"""
Citation Verifier — Ensure every reference in a paper corresponds to a real publication.

Uses CrossRef (DOI resolution), PubMed E-utilities, and Semantic Scholar
to confirm that cited papers exist and are retrievable.
"""
import asyncio
import re
import threading
import urllib.request
import urllib.parse
import json

import structlog

log = structlog.get_logger()


class CitationVerifier:
    """Verify citations extracted from generated papers."""

    # Regex patterns for common citation formats
    CITATION_PATTERNS = [
        # Author et al. (YYYY)
        re.compile(r"([A-Z][a-z]+(?:\s+et\s+al\.?)?\s*\(\d{4}\))"),
        # DOI
        re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9a-z]+)", re.IGNORECASE),
        # PubMed ID
        re.compile(r"PMID:\s*(\d+)", re.IGNORECASE),
    ]

    def __init__(
        self,
        *,
        request_timeout: float = 8.0,
        total_timeout: float = 20.0,
        max_concurrency: int = 4,
    ):
        self.request_timeout = max(0.1, float(request_timeout))
        self.total_timeout = max(0.1, float(total_timeout))
        self.max_concurrency = max(1, int(max_concurrency))
        self._cache: dict[tuple[str, str], dict] = {}
        self._cache_lock = threading.Lock()

    def extract_citations(self, text: str) -> list[dict]:
        """Extract candidate citations from paper text."""
        found = []
        seen = set()

        for pattern in self.CITATION_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(0)
                if raw in seen:
                    continue

                if raw.lower().startswith("10."):
                    raw = raw.rstrip(").,;:")
                    if raw in seen:
                        continue
                    seen.add(raw)
                    found.append({"type": "doi", "raw": raw})
                elif raw.lower().startswith("pmid"):
                    seen.add(raw)
                    found.append({"type": "pmid", "raw": raw, "pmid": match.group(1)})
                else:
                    seen.add(raw)
                    found.append({"type": "author_year", "raw": raw})

        return found

    def verify_doi(self, doi: str) -> dict:
        """Resolve a DOI via doi.org and CrossRef."""
        url = f"https://doi.org/{doi}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AMY-CitationVerifier/1.0 (mailto:contact@amy.ai)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                # A 302 redirect to the publisher page is success
                status = resp.getcode()
                if status in (200, 301, 302, 303, 307, 308):
                    return {"verified": True, "url": resp.url}
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return {"verified": True, "url": e.headers.get("Location", url)}
            log.warning("citation_verifier.doi_http_error", doi=doi, code=e.code)
            if e.code != 404:
                crossref = self._verify_doi_crossref(doi)
                if crossref.get("verified"):
                    return crossref
        except Exception as e:
            log.warning("citation_verifier.doi_error", doi=doi, error=str(e))
            crossref = self._verify_doi_crossref(doi)
            if crossref.get("verified"):
                return crossref

        return {"verified": False, "url": None}

    def _verify_doi_crossref(self, doi: str) -> dict:
        """Verify DOI existence through CrossRef metadata without following publisher redirects."""
        encoded = urllib.parse.quote(doi, safe="")
        url = f"https://api.crossref.org/works/{encoded}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AMY-CitationVerifier/1.0 (mailto:contact@amy.ai)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                if resp.getcode() != 200:
                    return {"verified": False, "url": None, "source": "crossref"}
                data = json.loads(resp.read())
                message = data.get("message", {}) if isinstance(data, dict) else {}
                returned_doi = str(message.get("DOI", "")).lower()
                if returned_doi == doi.lower():
                    return {
                        "verified": True,
                        "url": f"https://doi.org/{doi}",
                        "source": "crossref",
                        "title": (message.get("title") or [""])[0],
                    }
        except Exception as e:
            log.warning("citation_verifier.crossref_error", doi=doi, error=str(e))
        return {"verified": False, "url": None, "source": "crossref"}

    def verify_pmid(self, pmid: str) -> dict:
        """Verify a PubMed ID via E-utilities."""
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        url = f"{base}/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AMY-CitationVerifier/1.0"})
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                data = json.loads(resp.read())
                result = data.get("result", {}).get(pmid, {})
                if result.get("title"):
                    return {
                        "verified": True,
                        "title": result.get("title", ""),
                        "pubdate": result.get("pubdate", ""),
                    }
        except Exception as e:
            log.warning("citation_verifier.pmid_error", pmid=pmid, error=str(e))
        return {"verified": False}

    def verify_author_year(self, raw: str) -> dict:
        """Find a Crossref candidate without overstating citation identity.

        ``Author (Year)`` is intrinsically ambiguous: even an exact author/year
        match cannot prove which work the paper intended to cite.  Candidate
        metadata is returned to help repair the reference, but the citation
        remains unverified until it carries a stable identifier or enough
        bibliographic metadata for an exact match.
        """
        match = re.match(r"([A-Z][a-z]+).*?\((\d{4})\)", raw)
        if not match:
            return {"verified": False, "note": "unparseable citation"}

        author = match.group(1)
        year = match.group(2)
        query = urllib.parse.urlencode(
            {
                "query.author": author,
                "filter": (
                    f"from-pub-date:{year}-01-01,"
                    f"until-pub-date:{year}-12-31"
                ),
                "rows": 5,
                "select": "DOI,title,author,issued,published",
            }
        )
        url = f"https://api.crossref.org/works?{query}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "AMY-CitationVerifier/1.0 "
                        "(mailto:contact@amy.ai)"
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                data = json.loads(resp.read())
                items = data.get("message", {}).get("items", [])
                for item in items:
                    families = {
                        str(person.get("family", "")).casefold()
                        for person in item.get("author", [])
                        if isinstance(person, dict)
                    }
                    if author.casefold() not in families:
                        continue
                    date_parts = (
                        item.get("issued", {}).get("date-parts")
                        or item.get("published", {}).get("date-parts")
                        or []
                    )
                    candidate_year = (
                        str(date_parts[0][0])
                        if date_parts and date_parts[0]
                        else ""
                    )
                    if candidate_year != year:
                        continue
                    doi = str(item.get("DOI", ""))
                    return {
                        "verified": False,
                        "candidate_match": True,
                        "title": (item.get("title") or [""])[0],
                        "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else None,
                        "source": "crossref",
                        "note": (
                            "author-year citation is ambiguous; add the DOI "
                            "or complete bibliographic metadata"
                        ),
                    }
        except Exception as e:
            log.warning(
                "citation_verifier.crossref_author_year_error",
                author=author,
                year=year,
                error=str(e),
            )
            return {
                "verified": False,
                "note": f"Crossref lookup unavailable: {e}",
            }
        return {
            "verified": False,
            "candidate_match": False,
            "source": "crossref",
            "note": "no exact Crossref author/year candidate found",
        }

    @staticmethod
    def _cache_key(citation: dict) -> tuple[str, str]:
        identifier = citation.get("pmid") or citation.get("raw") or ""
        return citation.get("type", ""), str(identifier).strip().lower()

    def _verify_one(self, citation: dict) -> dict:
        key = self._cache_key(citation)
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached is not None:
            return dict(cached)

        if citation["type"] == "doi":
            result = self.verify_doi(citation["raw"])
        elif citation["type"] == "pmid":
            result = self.verify_pmid(citation.get("pmid", ""))
        else:
            result = self.verify_author_year(citation["raw"])

        with self._cache_lock:
            self._cache[key] = dict(result)
        return result

    @staticmethod
    def _summarize(citations: list[dict], results: list[dict]) -> dict:
        verified_count = 0
        unverified = []

        for citation, result in zip(citations, results):
            citation["verified"] = result.get("verified", False)
            citation["details"] = result
            if citation["verified"]:
                verified_count += 1
            else:
                unverified.append(citation["raw"])

        return {
            "total": len(citations),
            "verified": verified_count,
            "unverified": unverified,
            "citations": citations,
            "all_verified": len(citations) > 0
            and verified_count == len(citations),
        }

    def verify_citations(self, text: str) -> dict:
        """Synchronous compatibility API for scripts and offline audits."""
        citations = self.extract_citations(text)
        results = [self._verify_one(citation) for citation in citations]
        return self._summarize(citations, results)

    async def verify_citations_async(self, text: str) -> dict:
        """Verify citations concurrently without blocking the event loop.

        ``urllib`` remains the small, dependency-light transport used by the
        synchronous verifier.  Each request is offloaded to a worker thread,
        concurrency is bounded, and the whole batch has one hard deadline.
        Citations still pending at the deadline are explicitly unverified.
        """
        citations = self.extract_citations(text)
        if not citations:
            return self._summarize([], [])

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run(index: int, citation: dict) -> tuple[int, dict]:
            async with semaphore:
                try:
                    result = await asyncio.to_thread(
                        self._verify_one,
                        citation,
                    )
                except Exception as exc:
                    log.warning(
                        "citation_verifier.async_error",
                        citation=citation.get("raw", ""),
                        error=str(exc),
                    )
                    result = {
                        "verified": False,
                        "note": f"verification error: {exc}",
                    }
                return index, result

        tasks = [
            asyncio.create_task(_run(index, citation))
            for index, citation in enumerate(citations)
        ]
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=self.total_timeout,
            )
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        results = [
            {
                "verified": False,
                "note": f"verification deadline exceeded ({self.total_timeout:g}s)",
            }
            for _ in citations
        ]
        for task in done:
            try:
                index, result = task.result()
            except asyncio.CancelledError:
                continue
            results[index] = result
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            log.warning(
                "citation_verifier.deadline_exceeded",
                pending=len(pending),
                total=len(citations),
                timeout=self.total_timeout,
            )

        return self._summarize(citations, results)

    def mark_unverified(self, text: str, unverified_raw: list[str]) -> str:
        """Append [UNVERIFIED] to unverified citations in the text."""
        for raw in unverified_raw:
            text = text.replace(raw, f"{raw} [UNVERIFIED]")
        return text
