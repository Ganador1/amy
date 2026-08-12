"""Fast, resilient scholarly literature search.

The legacy Atlas LiteratureService queried up to 14 sources *sequentially*,
each with 3 retries × 10s timeout, plus a duplicate PaperQA2 pass. With arXiv
timing out and Semantic Scholar returning 429, a single query routinely blew
past the 90s subprocess deadline and returned ``{'error': 'timeout'}``.

This module replaces that path with a client that:

- queries multiple *reliable, key-free* sources CONCURRENTLY (asyncio.gather),
- gives each source a short per-call timeout (default 8s) and ONE retry,
- enforces a global deadline (default 18s) — whatever has arrived by then is
  returned; slow sources are simply dropped,
- normalizes every source into one paper schema,
- deduplicates by DOI / normalized title,
- computes a transparent support_score from how many independent sources and
  papers were found (NOT a fabricated number).

Empirically (May 2026) these sources answer in <2.5s without an API key:
OpenAlex, Crossref, Europe PMC, PubMed (NCBI E-utilities), DOAJ, CORE.
arXiv and Semantic Scholar are *opt-in* because they were unreliable
(timeouts / HTTP 429) from unauthenticated clients.

Only dependency: httpx (already required by the project).
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

try:  # structlog is a project dep, but keep this importable without it
    import structlog

    _log = structlog.get_logger()
except Exception:  # pragma: no cover
    import logging

    _log = logging.getLogger("literature_search")


DEFAULT_PER_SOURCE_TIMEOUT = float(os.getenv("LIT_PER_SOURCE_TIMEOUT", "8"))
DEFAULT_GLOBAL_DEADLINE = float(os.getenv("LIT_GLOBAL_DEADLINE", "18"))
DEFAULT_MAX_RESULTS = 8
# A contact e-mail makes us a "polite" client for Crossref / OpenAlex.
CONTACT_EMAIL = os.getenv("LIT_CONTACT_EMAIL", "amy-research@example.org")
# Optional keys — used only if present; never required.
OPENALEX_KEY = os.getenv("OPENALEX_API_KEY", "")
SEMANTIC_SCHOLAR_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
CORE_KEY = os.getenv("CORE_API_KEY", "")

# Terms used only to keep a literature result inside the requested scientific
# domain.  They are deliberately broad: topic-token overlap remains the main
# signal, while this vocabulary prevents a highly cited but unrelated paper
# from ranking above a less-cited relevant result.
DOMAIN_TERMS: dict[str, set[str]] = {
    "mathematics": {
        "algebra", "calculus", "conjecture", "equation", "geometry",
        "integer", "mathematics", "number", "prime", "proof", "theorem",
    },
    "physics": {
        "atom", "energy", "field", "particle", "physics", "quantum",
        "spectrum", "wave",
    },
    "chemistry": {
        "bond", "chemical", "chemistry", "compound", "molecular",
        "molecule", "organic", "reaction",
    },
    "biology": {
        "bioinformatics", "biology", "cell", "dna", "gene", "genome",
        "protein", "sequence",
    },
    "medicine": {
        "clinical", "disease", "drug", "medicine", "patient", "therapy",
        "treatment", "vaccine",
    },
    "statistics": {
        "confidence", "correlation", "distribution", "regression",
        "sample", "statistical", "statistics", "variance",
    },
    "astronomy": {
        "astronomy", "cosmic", "exoplanet", "galaxy", "planet", "star",
        "stellar",
    },
    "neuroscience": {
        "brain", "neural", "neuron", "neuroscience", "synaptic",
    },
    "climate": {
        "atmosphere", "climate", "co2", "emissions", "temperature",
    },
    "engineering": {
        "engineering", "manufacturing", "material", "structural", "system",
    },
}

_GENERIC_QUERY_TERMS = {
    "analysis", "computational", "evidence", "experiment", "investigation",
    "research", "result", "study", "verification", "using",
}


def _text_tokens(text: str) -> set[str]:
    """Return stable lexical tokens suitable for conservative relevance QA."""
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 3 and token not in _GENERIC_QUERY_TERMS
    }


def _paper_relevance(paper: "Paper", query: str, domain: str | None) -> dict[str, Any]:
    """Score explainable lexical relevance without inventing semantic certainty.

    This is intentionally a precision-oriented publication safeguard, not a
    general-purpose scholarly ranker.  A result must share at least one useful
    topic term (or, for an entirely generic query, a domain term) to be handed
    to the paper writer.
    """
    query_terms = _text_tokens(query)
    title_terms = _text_tokens(paper.title)
    abstract_terms = _text_tokens(paper.abstract)
    normalized_domain = (domain or "").strip().lower()
    domain_terms = DOMAIN_TERMS.get(normalized_domain, set())

    query_title = query_terms & title_terms
    query_abstract = query_terms & abstract_terms
    domain_matches = domain_terms & (title_terms | abstract_terms)
    topic_matches = query_title | query_abstract
    relevant = bool(topic_matches) if query_terms else bool(domain_matches)

    score = (
        4 * len(query_title)
        + len(query_abstract)
        + 2 * len(domain_terms & title_terms)
        + len(domain_terms & abstract_terms)
    )
    return {
        "relevant": relevant,
        "score": score,
        "topic_matches": sorted(topic_matches),
        "domain_matches": sorted(domain_matches),
    }


@dataclass
class Paper:
    title: str
    abstract: str = ""
    year: int | None = None
    doi: str = ""
    url: str = ""
    authors: list[str] = field(default_factory=list)
    source: str = ""
    citations: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "summary": self.abstract,  # heartbeat reads either key
            "year": self.year,
            "doi": self.doi,
            "url": self.url,
            "authors": self.authors,
            "source": self.source,
            "citations": self.citations,
        }


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _clean_abstract_from_inverted_index(inv: dict | None) -> str:
    """OpenAlex returns abstracts as an inverted index {word: [positions]}."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)[:2000]


# ─── Per-source fetchers. Each returns list[Paper]; each may raise. ───────────


async def _fetch_openalex(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    params = {"search": query, "per-page": k, "mailto": CONTACT_EMAIL}
    if OPENALEX_KEY:
        params["api_key"] = OPENALEX_KEY
    r = await client.get("https://api.openalex.org/works", params=params)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", [])[:k]:
        out.append(Paper(
            title=w.get("title") or "",
            abstract=_clean_abstract_from_inverted_index(w.get("abstract_inverted_index")),
            year=w.get("publication_year"),
            doi=(w.get("doi") or "").replace("https://doi.org/", ""),
            url=w.get("id", ""),
            authors=[a.get("author", {}).get("display_name", "")
                     for a in (w.get("authorships") or [])[:6]],
            source="OpenAlex",
            citations=w.get("cited_by_count"),
        ))
    return out


async def _fetch_crossref(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    params = {"query": query, "rows": k, "mailto": CONTACT_EMAIL,
              "select": "title,abstract,DOI,issued,author,URL,is-referenced-by-count"}
    r = await client.get("https://api.crossref.org/works", params=params)
    r.raise_for_status()
    out = []
    for it in r.json().get("message", {}).get("items", [])[:k]:
        title = (it.get("title") or [""])[0]
        year = None
        try:
            year = it.get("issued", {}).get("date-parts", [[None]])[0][0]
        except Exception:
            pass
        authors = []
        for a in (it.get("author") or [])[:6]:
            name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
            if name:
                authors.append(name)
        out.append(Paper(
            title=title,
            abstract=re.sub("<[^>]+>", "", it.get("abstract", "") or "")[:2000],
            year=year,
            doi=it.get("DOI", ""),
            url=it.get("URL", ""),
            authors=authors,
            source="Crossref",
            citations=it.get("is-referenced-by-count"),
        ))
    return out


async def _fetch_europepmc(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    params = {"query": query, "format": "json", "pageSize": k, "resultType": "core"}
    r = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params)
    r.raise_for_status()
    out = []
    for res in r.json().get("resultList", {}).get("result", [])[:k]:
        out.append(Paper(
            title=res.get("title", ""),
            abstract=(res.get("abstractText", "") or "")[:2000],
            year=int(res["pubYear"]) if str(res.get("pubYear", "")).isdigit() else None,
            doi=res.get("doi", ""),
            url=(f"https://europepmc.org/article/{res.get('source','')}/"
                 f"{res.get('id','')}") if res.get("id") else "",
            authors=[a.strip() for a in (res.get("authorString", "") or "").split(",")[:6]],
            source="Europe PMC",
            citations=res.get("citedByCount"),
        ))
    return out


async def _fetch_pubmed(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    key_params = {"api_key": os.getenv("NCBI_API_KEY")} if os.getenv("NCBI_API_KEY") else {}
    s = await client.get(f"{base}/esearch.fcgi", params={
        "db": "pubmed", "term": query, "retmax": k, "retmode": "json", **key_params})
    s.raise_for_status()
    ids = s.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summ = await client.get(f"{base}/esummary.fcgi", params={
        "db": "pubmed", "id": ",".join(ids), "retmode": "json", **key_params})
    summ.raise_for_status()
    result = summ.json().get("result", {})
    out = []
    for pid in ids[:k]:
        rec = result.get(pid)
        if not isinstance(rec, dict):
            continue
        year = None
        m = re.match(r"(\d{4})", rec.get("pubdate", ""))
        if m:
            year = int(m.group(1))
        doi = ""
        for aid in rec.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
        out.append(Paper(
            title=rec.get("title", ""),
            abstract="",  # esummary has no abstract; title+venue is enough as an anchor
            year=year,
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            authors=[a.get("name", "") for a in rec.get("authors", [])[:6]],
            source="PubMed",
        ))
    return out


async def _fetch_doaj(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    from urllib.parse import quote
    r = await client.get(
        f"https://doaj.org/api/search/articles/{quote(query)}", params={"pageSize": k})
    r.raise_for_status()
    out = []
    for res in r.json().get("results", [])[:k]:
        bib = res.get("bibjson", {})
        ident = bib.get("identifier", [])
        doi = next((i.get("id", "") for i in ident if i.get("type") == "doi"), "")
        links = bib.get("link", [])
        url = next((l.get("url", "") for l in links if l.get("url")), "")
        year = int(bib["year"]) if str(bib.get("year", "")).isdigit() else None
        out.append(Paper(
            title=bib.get("title", ""),
            abstract=(bib.get("abstract", "") or "")[:2000],
            year=year,
            doi=doi,
            url=url,
            authors=[a.get("name", "") for a in bib.get("author", [])[:6]],
            source="DOAJ",
        ))
    return out


async def _fetch_core(client: httpx.AsyncClient, query: str, k: int) -> list[Paper]:
    headers = {"Authorization": f"Bearer {CORE_KEY}"} if CORE_KEY else {}
    r = await client.get("https://api.core.ac.uk/v3/search/works",
                         params={"q": query, "limit": k}, headers=headers)
    r.raise_for_status()
    out = []
    for res in r.json().get("results", [])[:k]:
        out.append(Paper(
            title=res.get("title", "") or "",
            abstract=(res.get("abstract", "") or "")[:2000],
            year=res.get("yearPublished"),
            doi=res.get("doi", "") or "",
            url=res.get("downloadUrl", "") or "",
            authors=[a.get("name", "") for a in (res.get("authors") or [])[:6]],
            source="CORE",
        ))
    return out


# Reliable, key-free sources queried by default.
DEFAULT_SOURCES = {
    "openalex": _fetch_openalex,
    "crossref": _fetch_crossref,
    "europepmc": _fetch_europepmc,
    "pubmed": _fetch_pubmed,
    "doaj": _fetch_doaj,
    "core": _fetch_core,
}


async def _run_one(name, fn, client, query, k, per_timeout) -> tuple[str, list[Paper], str]:
    """Run one source with a timeout + a single retry. Never raises."""
    for attempt in (1, 2):
        try:
            papers = await asyncio.wait_for(fn(client, query, k), timeout=per_timeout)
            return name, papers, ""
        except asyncio.TimeoutError:
            err = "timeout"
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}"
            if e.response.status_code not in (429, 500, 502, 503, 504):
                break  # don't retry hard client errors
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}"
        if attempt == 1:
            await asyncio.sleep(0.3)
    return name, [], err


async def search_literature_async(
    query: str,
    *,
    domain: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    sources: dict | None = None,
    per_source_timeout: float = DEFAULT_PER_SOURCE_TIMEOUT,
    global_deadline: float = DEFAULT_GLOBAL_DEADLINE,
) -> dict[str, Any]:
    """Search several sources concurrently and merge the results.

    Returns a dict compatible with the rest of A.M.Y:
        {
          "papers": [ {title, abstract, summary, year, doi, url, authors, source}, ... ],
          "support_score": float,   # 0..1, from breadth of evidence
          "sources_queried": [...], "sources_succeeded": [...],
          "source_errors": {name: reason}, "elapsed": float,
        }
    """
    query = (query or "").strip()
    if not query:
        return {"papers": [], "support_score": 0.0, "error": "empty query",
                "sources_queried": [], "sources_succeeded": [], "source_errors": {}}

    sources = sources or DEFAULT_SOURCES
    loop = asyncio.get_event_loop()
    start = loop.time()

    timeout_cfg = httpx.Timeout(per_source_timeout, connect=5.0)
    headers = {"User-Agent": f"AMY-research/1.0 (mailto:{CONTACT_EMAIL})"}
    async with httpx.AsyncClient(timeout=timeout_cfg, headers=headers,
                                 follow_redirects=True) as client:
        # Map each task to its source name so a task that misses the global
        # deadline can be reported by name. (The old code read t._lit_name,
        # which was never set anywhere, so every deadline error collapsed to a
        # single bogus errors["?"] entry.)
        task_names: dict[asyncio.Task, str] = {
            asyncio.create_task(
                _run_one(name, fn, client, query, max_results, per_source_timeout)
            ): name
            for name, fn in sources.items()
        }
        done, pending = await asyncio.wait(set(task_names), timeout=global_deadline)
        for t in pending:
            t.cancel()

    succeeded: list[str] = []
    errors: dict[str, str] = {}
    all_papers: list[Paper] = []
    for t in done:
        try:
            name, papers, err = t.result()
        except Exception:  # cancelled / unexpected
            continue
        if papers:
            succeeded.append(name)
            all_papers.extend(papers)
        elif err:
            errors[name] = err
    for t in pending:
        errors[task_names[t]] = "deadline"

    # Deduplicate by DOI, then by normalized title.
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    merged: list[Paper] = []
    for p in all_papers:
        if not p.title:
            continue
        doi = p.doi.lower().strip()
        nt = _norm_title(p.title)
        if doi and doi in seen_doi:
            continue
        if nt and nt in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if nt:
            seen_title.add(nt)
        merged.append(p)

    # Publication-facing calls provide a domain.  In that mode, remove papers
    # with no lexical connection to the topic before citation count can lift an
    # unrelated but popular result to the top.  Raw/general searches that omit
    # a domain preserve the historical broad-search behavior.
    relevance_by_id: dict[int, dict[str, Any]] = {}
    filtered_irrelevant = 0
    if domain:
        relevant_papers: list[Paper] = []
        for paper in merged:
            relevance = _paper_relevance(paper, query, domain)
            relevance_by_id[id(paper)] = relevance
            if relevance["relevant"]:
                relevant_papers.append(paper)
            else:
                filtered_irrelevant += 1
        merged = relevant_papers

    # Relevance leads; abstracts, citations and recency break ties.
    merged.sort(
        key=lambda p: (
            relevance_by_id.get(id(p), {}).get("score", 0),
            bool(p.abstract),
            p.citations or 0,
            p.year or 0,
        ),
        reverse=True,
    )

    # Transparent support score: more independent sources + more papers = more
    # confidence, capped at 1.0. NOT a p-value, just an evidence-breadth signal.
    n_sources = len(set(p.source for p in merged))
    support = min(1.0, 0.15 * n_sources + 0.02 * min(len(merged), 20))

    elapsed = loop.time() - start
    _log.info("literature_search.done",
              query=query[:80], papers=len(merged),
              sources_ok=succeeded, errors=errors, elapsed=round(elapsed, 2))

    paper_dicts = []
    for paper in merged[:max_results * 2]:
        item = paper.to_dict()
        if domain:
            relevance = relevance_by_id[id(paper)]
            item["relevance_score"] = relevance["score"]
            item["relevance_matches"] = relevance["topic_matches"]
            item["domain_matches"] = relevance["domain_matches"]
        paper_dicts.append(item)

    return {
        "papers": paper_dicts,
        "support_score": round(support, 3),
        "sources_queried": list(sources.keys()),
        "sources_succeeded": succeeded,
        "source_errors": errors,
        "domain": domain,
        "relevance_filter_applied": bool(domain),
        "papers_filtered_irrelevant": filtered_irrelevant,
        "elapsed": round(elapsed, 2),
    }


def search_literature_sync(query: str, **kwargs) -> dict[str, Any]:
    """Blocking wrapper for non-async callers."""
    return asyncio.run(search_literature_async(query, **kwargs))
