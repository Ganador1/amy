"""
Citation Verifier — Ensure every reference in a paper corresponds to a real publication.

Uses CrossRef (DOI resolution), PubMed E-utilities, and Semantic Scholar
to confirm that cited papers exist and are retrievable.
"""
import re
import urllib.request
import urllib.parse
import json
from typing import Optional

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
            with urllib.request.urlopen(req, timeout=15) as resp:
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
            with urllib.request.urlopen(req, timeout=15) as resp:
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
            with urllib.request.urlopen(req, timeout=15) as resp:
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
        """Lightweight check for author+year citations via Semantic Scholar."""
        # Extract author and year
        match = re.match(r"([A-Z][a-z]+).*?\((\d{4})\)", raw)
        if not match:
            return {"verified": False, "note": "unparseable citation"}

        author = match.group(1)
        year = match.group(2)
        query = f"{author} {year}"

        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search"
            f"?query={urllib.request.quote(query)}&limit=3&fields=title,year,authors"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AMY-CitationVerifier/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                papers = data.get("data", [])
                for p in papers:
                    if str(p.get("year", "")) == year:
                        authors = [a.get("name", "").split()[-1] for a in p.get("authors", [])]
                        if author in authors:
                            return {
                                "verified": True,
                                "title": p.get("title", ""),
                                "paper_id": p.get("paperId", ""),
                            }
        except Exception as e:
            log.warning("citation_verifier.ss_error", query=query, error=str(e))
        return {"verified": False}

    def verify_citations(self, text: str) -> dict:
        """Full pipeline: extract + verify all citations in a text."""
        citations = self.extract_citations(text)
        verified_count = 0
        unverified = []

        for c in citations:
            if c["type"] == "doi":
                result = self.verify_doi(c["raw"])
            elif c["type"] == "pmid":
                result = self.verify_pmid(c.get("pmid", ""))
            else:
                result = self.verify_author_year(c["raw"])

            c["verified"] = result.get("verified", False)
            c["details"] = result
            if c["verified"]:
                verified_count += 1
            else:
                unverified.append(c["raw"])

        return {
            "total": len(citations),
            "verified": verified_count,
            "unverified": unverified,
            "citations": citations,
            "all_verified": len(citations) > 0 and verified_count == len(citations),
        }

    def mark_unverified(self, text: str, unverified_raw: list[str]) -> str:
        """Append [UNVERIFIED] to unverified citations in the text."""
        for raw in unverified_raw:
            text = text.replace(raw, f"{raw} [UNVERIFIED]")
        return text
