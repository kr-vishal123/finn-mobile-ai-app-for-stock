"""Ask a question about one company, answered only from its own earnings-call transcripts.

retrieve  — BM25 over transcript pages (document_chunks); no embeddings needed at this scale
answer    — model writes a short answer that must cite [call · page] with verbatim quotes
verify    — code checks every quote really appears in the cited page; unverifiable citations are
            dropped, and an answer with no surviving citation is shown as passages only
fallback  — no key / model down: the best-matching passages, verbatim
"""

from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Company, Document, DocumentChunk
from app.models.enums import DocType
from app.services import llm

_STOP = set("""a an the and or of to in on for with at by from is are was were be been being this that these those it its
as about into over under what which who whom how why when where do does did can could would should will may might
we our you your they their he she his her them us i me my mr ms sir management company say said tell please
any some more most than then there here also just very much many have has had not no yes so if but""".split())


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]+|\d+(?:\.\d+)?%?", text.lower()) if w not in _STOP and len(w) > 1]


def store_pages(db: Session, doc: Document, pages: list[str]) -> None:
    """One chunk per transcript page (page numbers are the citation unit)."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    for i, text in enumerate(pages, start=1):
        t = re.sub(r"\s+", " ", text).strip()
        if len(t) > 80:
            db.add(DocumentChunk(document_id=doc.id, seq=i, page_start=i, page_end=i, text=t,
                                 token_count=len(t) // 4))


def retrieve(db: Session, company: Company, question: str, k: int = 5) -> list[dict]:
    rows = db.execute(
        select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.company_id == company.id, Document.doc_type == DocType.concall_transcript)
    ).all()
    if not rows:
        return []
    q = _tokens(question)
    if not q:
        return []
    docs = [(c, d, Counter(_tokens(c.text))) for c, d in rows]
    n, avg = len(docs), sum(sum(tf.values()) for _, _, tf in docs) / len(docs)
    df = Counter(t for _, _, tf in docs for t in set(tf))
    scored = []
    for c, d, tf in docs:
        length = sum(tf.values()) or 1
        s = 0.0
        for t in set(q):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * length / avg))
        if s > 0:
            scored.append((s, c, d))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, c, d in scored[:k]:
        out.append({"ref": f"{d.period_label or d.doc_date} p.{c.page_start}", "call": d.period_label,
                    "page": c.page_start, "url": d.url, "score": round(s, 2), "text": c.text,
                    "snippet": _best_snippet(c.text, q)})
    return out


def _best_snippet(text: str, q: list[str], width: int = 2) -> str:
    sents = re.split(r"(?<=[.?!])\s+(?=[A-Z])", text)
    best, best_i = -1, 0
    for i, s in enumerate(sents):
        sc = sum(1 for t in set(q) if t in s.lower())
        if sc > best:
            best, best_i = sc, i
    return " ".join(sents[best_i: best_i + width])[:450]


SYSTEM = """You answer an investor's question about one Indian listed company using ONLY the numbered
transcript excerpts provided (the company's own earnings calls). Rules:
- Use no outside knowledge, news or memory of the company. If the excerpts don't answer it, set
  not_found=true and say what they do cover instead, in one sentence.
- Answer in at most 90 words, plain and specific; keep numbers exactly as written in the excerpts.
- Distinguish management's statements from analysts' questions.
- Every claim needs a citation: the excerpt id and a verbatim quote of 6-30 words copied exactly from it."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "not_found": {"type": "boolean"},
        "citations": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "quote": {"type": "string"}},
            "required": ["id", "quote"], "additionalProperties": False}},
    },
    "required": ["answer", "not_found", "citations"],
    "additionalProperties": False,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%.]+", " ", s.lower()).strip()


def ask_company(db: Session, company: Company, question: str) -> dict:
    hits = retrieve(db, company, question)
    base = {"question": question, "symbol": company.nse_symbol,
            "passages": [{k: h[k] for k in ("ref", "url", "snippet", "page", "call")} for h in hits]}
    if not hits:
        return base | {"mode": "none", "answer": None, "citations": [],
                       "note": "No transcripts on file for this company yet."}
    tier = "strong" if llm.is_available("strong") else "cheap"
    if not llm.is_available(tier):
        return base | {"mode": "passages", "answer": None, "citations": [],
                       "note": "Showing the most relevant transcript passages (no model configured)."}
    excerpts = "\n\n".join(f"[{i}] ({h['ref']}) {h['text'][:3500]}" for i, h in enumerate(hits, start=1))
    try:
        out = llm.complete(db, task="company_qa", system=SYSTEM, tier=tier, schema=SCHEMA, max_tokens=8192,
                           prompt=f"Company: {company.name}\nQuestion: {question}\n\nExcerpts:\n{excerpts}")
        db.commit()
    except (llm.LLMUnavailable, ValueError, KeyError) as e:
        return base | {"mode": "passages", "answer": None, "citations": [],
                       "note": f"Model unavailable ({str(e)[:60]}); showing passages."}

    # Grounding check: keep only citations whose quote is really in the cited excerpt.
    cites, dropped = [], 0
    for c in out.get("citations", []):
        i = c.get("id")
        if not isinstance(i, int) or not 1 <= i <= len(hits):
            dropped += 1
            continue
        if _norm(c.get("quote", ""))[:120] and _norm(c["quote"])[:120] in _norm(hits[i - 1]["text"]):
            h = hits[i - 1]
            cites.append({"ref": h["ref"], "url": h["url"], "quote": c["quote"].strip()})
        else:
            dropped += 1
    model = get_settings().llm_strong_model if tier == "strong" else get_settings().llm_cheap_model
    if not cites and not out.get("not_found"):
        return base | {"mode": "passages", "answer": None, "citations": [], "model": model,
                       "note": "The model's answer couldn't be verified against the transcripts, so only passages are shown."}
    clean = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", out["answer"]).strip()  # citations render separately
    return base | {"mode": "answer", "answer": clean, "not_found": out.get("not_found", False),
                   "citations": cites, "unverified_dropped": dropped, "model": model}
