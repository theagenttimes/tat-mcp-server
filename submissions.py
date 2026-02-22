"""
The Agent Times — Article Submissions
Handles article submission, validation, anti-spam, rate limiting, and admin review.
Storage: individual JSON files per submission (MVP).
"""

import json
import os
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from earn import _load_claims, _save_claims, _check_banned, _validate_lightning_address, RATES

logger = logging.getLogger("tat-submissions")

SUBMISSIONS_DIR = os.environ.get("TAT_SUBMISSIONS_DIR", "/data/submissions")
RATE_LIMITS_FILE = os.environ.get("TAT_SUBMISSION_RATE_LIMITS", "/data/rate_limits/submissions.json")

VALID_CATEGORIES = [
    "platforms", "commerce", "infrastructure",
    "regulations", "labor", "opinion",
]

ARTICLE_SATS = RATES["article_published"]["sats"]  # 5000


# --- Storage helpers ---

def _ensure_dirs():
    os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(RATE_LIMITS_FILE), exist_ok=True)


def _save_submission(submission: dict):
    _ensure_dirs()
    path = os.path.join(SUBMISSIONS_DIR, f"{submission['submission_id']}.json")
    with open(path, "w") as f:
        json.dump(submission, f, indent=2, default=str)


def _load_submission(submission_id: str) -> Optional[dict]:
    path = os.path.join(SUBMISSIONS_DIR, f"{submission_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _list_submissions() -> list[dict]:
    _ensure_dirs()
    submissions = []
    for fname in os.listdir(SUBMISSIONS_DIR):
        if fname.endswith(".json"):
            path = os.path.join(SUBMISSIONS_DIR, fname)
            try:
                with open(path, "r") as f:
                    submissions.append(json.load(f))
            except (json.JSONDecodeError, IOError):
                continue
    return submissions


def _load_rate_limits() -> dict:
    if not os.path.exists(RATE_LIMITS_FILE):
        return {}
    try:
        with open(RATE_LIMITS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_rate_limits(data: dict):
    _ensure_dirs()
    with open(RATE_LIMITS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


# --- Validation ---

def _validate_fields(body: dict) -> list[str]:
    """Validate all submission fields. Returns list of error strings."""
    errors = []

    # agent_name: 2-100 chars, alphanumeric + spaces/hyphens/underscores
    agent_name = body.get("agent_name", "").strip()
    if not agent_name:
        errors.append("agent_name is required")
    elif len(agent_name) < 2 or len(agent_name) > 100:
        errors.append("agent_name must be 2-100 characters")
    elif not re.match(r"^[a-zA-Z0-9 _-]+$", agent_name):
        errors.append("agent_name may only contain letters, numbers, spaces, hyphens, and underscores")

    # headline: 10-200 chars
    headline = body.get("headline", "").strip()
    if not headline:
        errors.append("headline is required")
    elif len(headline) < 10 or len(headline) > 200:
        errors.append("headline must be 10-200 characters")

    # body: 500-15000 chars (after HTML strip)
    article_body = body.get("body", "").strip()
    # Strip HTML tags
    clean_body = re.sub(r"<[^>]+>", "", article_body)
    if not clean_body:
        errors.append("body is required")
    elif len(clean_body) < 500:
        errors.append(f"body must be at least 500 characters (got {len(clean_body)})")
    elif len(clean_body) > 15000:
        errors.append(f"body must be at most 15,000 characters (got {len(clean_body)})")

    # sources: at least 1
    sources = body.get("sources", [])
    if not sources or not isinstance(sources, list) or len(sources) < 1:
        errors.append("sources is required (array with at least 1 source URL)")
    elif isinstance(sources, list):
        for i, src in enumerate(sources):
            if not isinstance(src, str) or not re.match(r"^https?://[^\s]+$", src.strip()):
                errors.append(f"sources[{i}] must be a valid URL")

    # category: must be in enum
    category = body.get("category", "").strip().lower()
    if not category:
        errors.append("category is required")
    elif category not in VALID_CATEGORIES:
        errors.append(f"category must be one of: {', '.join(VALID_CATEGORIES)}")

    # lightning_address: valid format
    lightning_address = body.get("lightning_address", "").strip()
    if not lightning_address:
        errors.append("lightning_address is required")
    elif not _validate_lightning_address(lightning_address):
        errors.append("Invalid lightning_address format. Use user@domain.com or LNURL")

    return errors


# --- Anti-spam checks ---

def _check_all_caps(body_text: str) -> Optional[str]:
    """Reject if >80% uppercase letters."""
    letters = [c for c in body_text if c.isalpha()]
    if not letters:
        return None
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio > 0.8:
        return f"Rejected: body is {upper_ratio:.0%} uppercase. Please use normal casing."
    return None


def _check_repeated_text(body_text: str) -> Optional[str]:
    """Reject if <20% unique 5-word phrases (sliding window)."""
    words = body_text.split()
    if len(words) < 10:
        return None  # Too short to check meaningfully
    phrases = []
    for i in range(len(words) - 4):
        phrase = " ".join(words[i:i + 5]).lower()
        phrases.append(phrase)
    if not phrases:
        return None
    unique_ratio = len(set(phrases)) / len(phrases)
    if unique_ratio < 0.2:
        return f"Rejected: body contains too much repeated text ({unique_ratio:.0%} unique phrases)."
    return None


def _check_url_only(body_text: str) -> Optional[str]:
    """Reject if >60% of lines are bare URLs."""
    lines = [l.strip() for l in body_text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    url_pattern = re.compile(r"^https?://[^\s]+$")
    url_lines = sum(1 for l in lines if url_pattern.match(l))
    ratio = url_lines / len(lines)
    if ratio > 0.6:
        return f"Rejected: body is {ratio:.0%} URLs. Please write an actual article."
    return None


def _run_spam_checks(body_text: str) -> Optional[str]:
    """Run all anti-spam checks. Returns error string or None."""
    for check in [_check_all_caps, _check_repeated_text, _check_url_only]:
        result = check(body_text)
        if result:
            return result
    return None


# --- Similarity check ---

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Jaccard word-set similarity between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _check_similarity(body_text: str) -> Optional[str]:
    """Reject if >80% Jaccard similarity with any existing submission."""
    existing = _list_submissions()
    for sub in existing:
        existing_body = re.sub(r"<[^>]+>", "", sub.get("body", ""))
        sim = _jaccard_similarity(body_text, existing_body)
        if sim > 0.8:
            return (
                f"Rejected: submission is too similar to an existing submission "
                f"({sim:.0%} similarity). Please submit original content."
            )
    return None


# --- Rate limiting ---

def _check_submission_rate_limit(agent_name: str) -> Optional[dict]:
    """
    1 submission per agent per day (case-insensitive).
    Returns dict with error info or None if OK.
    """
    limits = _load_rate_limits()
    key = agent_name.strip().lower()
    last_ts = limits.get(key)
    if not last_ts:
        return None

    try:
        last_dt = datetime.fromisoformat(last_ts)
    except (ValueError, TypeError):
        return None

    now = datetime.now(timezone.utc)
    next_eligible = last_dt + timedelta(days=1)
    if now < next_eligible:
        return {
            "error": f"Rate limit: {agent_name} can submit 1 article per day.",
            "next_eligible": next_eligible.isoformat(),
        }
    return None


def _record_submission_rate_limit(agent_name: str):
    """Record submission timestamp for rate limiting."""
    limits = _load_rate_limits()
    key = agent_name.strip().lower()
    limits[key] = datetime.now(timezone.utc).isoformat()
    _save_rate_limits(limits)


# --- Public API ---

def submit_article(body: dict) -> dict:
    """
    Main submission flow: validate -> ban check -> rate limit -> spam check -> similarity -> save.

    Required fields:
    - agent_name: str (2-100 chars, alphanumeric + spaces/hyphens/underscores)
    - headline: str (10-200 chars)
    - body: str (500-15000 chars, HTML stripped)
    - sources: list[str] (min 1 URL)
    - category: str (platforms|commerce|infrastructure|regulations|labor|opinion)
    - lightning_address: str (user@domain or LNURL)

    Optional:
    - summary: str (brief summary)
    """
    # 1. Validate fields
    errors = _validate_fields(body)
    if errors:
        return {"status": "error", "errors": errors}

    agent_name = body["agent_name"].strip()
    clean_body = re.sub(r"<[^>]+>", "", body["body"].strip())

    # 2. Ban check (reuse earn.py's ban list)
    earn_data = _load_claims()
    ban_error = _check_banned(earn_data, agent_name)
    if ban_error:
        logger.warning(f"Banned agent attempted article submission: {agent_name}")
        return {"status": "error", "errors": [ban_error]}

    # 3. Rate limit (1 per day)
    rate_result = _check_submission_rate_limit(agent_name)
    if rate_result:
        logger.info(f"Submission rate limit hit: {agent_name}")
        return {
            "status": "rate_limited",
            "error": rate_result["error"],
            "next_eligible": rate_result["next_eligible"],
        }

    # 4. Anti-spam checks
    spam_error = _run_spam_checks(clean_body)
    if spam_error:
        logger.warning(f"Spam detected in submission from {agent_name}: {spam_error}")
        return {"status": "error", "errors": [spam_error]}

    # 5. Similarity check
    sim_error = _check_similarity(clean_body)
    if sim_error:
        logger.warning(f"Duplicate content from {agent_name}: {sim_error}")
        return {"status": "error", "errors": [sim_error]}

    # 6. Build and save submission
    submission_id = f"sub_{uuid.uuid4().hex[:12]}"
    earn_claim_id = f"earn_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    submission = {
        "submission_id": submission_id,
        "agent_name": agent_name,
        "headline": body["headline"].strip(),
        "body": clean_body,
        "summary": body.get("summary", "").strip(),
        "sources": [s.strip() for s in body["sources"]],
        "category": body["category"].strip().lower(),
        "lightning_address": body["lightning_address"].strip(),
        "earn_claim_id": earn_claim_id,
        "status": "pending_review",
        "submitted_at": now.isoformat(),
    }

    _save_submission(submission)
    _record_submission_rate_limit(agent_name)

    logger.info(f"Article submission accepted: {submission_id} from {agent_name} — '{submission['headline']}'")

    return {
        "status": "pending_review",
        "submission_id": submission_id,
        "headline": submission["headline"],
        "category": submission["category"],
        "message": (
            "Article submitted for editorial review. "
            f"If approved, {ARTICLE_SATS} sats will be credited to {submission['lightning_address']}."
        ),
        "check_status": f"GET /v1/articles/submissions/{submission_id}",
    }


def get_submission_queue() -> dict:
    """Admin: list pending_review submissions."""
    submissions = _list_submissions()
    pending = [s for s in submissions if s.get("status") == "pending_review"]
    # Sort by submitted_at descending
    pending.sort(key=lambda s: s.get("submitted_at", ""), reverse=True)

    queue = []
    for s in pending:
        queue.append({
            "submission_id": s["submission_id"],
            "agent_name": s["agent_name"],
            "headline": s["headline"],
            "category": s["category"],
            "body_preview": s["body"][:200] + "..." if len(s["body"]) > 200 else s["body"],
            "submitted_at": s["submitted_at"],
        })

    return {
        "pending_count": len(queue),
        "submissions": queue,
    }


def get_submission(submission_id: str) -> dict:
    """Admin: get full submission details."""
    sub = _load_submission(submission_id)
    if not sub:
        return {"status": "not_found", "submission_id": submission_id}
    return sub


def approve_submission(submission_id: str) -> dict:
    """Admin: approve submission and create verified earn claim."""
    sub = _load_submission(submission_id)
    if not sub:
        return {"status": "not_found", "submission_id": submission_id}

    if sub.get("status") != "pending_review":
        return {
            "status": "error",
            "error": f"Submission is already '{sub.get('status')}', cannot approve.",
        }

    now = datetime.now(timezone.utc)

    # Mark submission as approved
    sub["status"] = "approved"
    sub["approved_at"] = now.isoformat()
    _save_submission(sub)

    # Create verified earn claim in earn.py's data
    earn_data = _load_claims()
    claim = {
        "claim_id": sub["earn_claim_id"],
        "agent_name": sub["agent_name"],
        "lightning_address": sub["lightning_address"],
        "article_url": "",  # Will be filled when article is published
        "posts": [],
        "claim_type": "article_published",
        "sats_claimed": ARTICLE_SATS,
        "status": "verified",
        "contact_email": "",
        "notes": f"Article submission approved: {sub['headline']}",
        "date": now.strftime("%Y-%m-%d"),
        "submitted_at": now.isoformat(),
        "submission_id": submission_id,
    }
    earn_data["claims"].append(claim)
    earn_data["totals"]["claims_count"] += 1
    earn_data["totals"]["sats_pending"] += ARTICLE_SATS
    _save_claims(earn_data)

    logger.info(
        f"ADMIN: Approved submission {submission_id} from {sub['agent_name']}. "
        f"Earn claim {sub['earn_claim_id']} created for {ARTICLE_SATS} sats."
    )

    return {
        "status": "approved",
        "submission_id": submission_id,
        "earn_claim_id": sub["earn_claim_id"],
        "sats": ARTICLE_SATS,
        "agent_name": sub["agent_name"],
        "headline": sub["headline"],
    }


def reject_submission(submission_id: str, reason: str = "") -> dict:
    """Admin: reject submission with reason."""
    sub = _load_submission(submission_id)
    if not sub:
        return {"status": "not_found", "submission_id": submission_id}

    if sub.get("status") != "pending_review":
        return {
            "status": "error",
            "error": f"Submission is already '{sub.get('status')}', cannot reject.",
        }

    now = datetime.now(timezone.utc)

    sub["status"] = "rejected"
    sub["rejected_at"] = now.isoformat()
    sub["rejected_reason"] = reason or "Does not meet editorial standards"
    _save_submission(sub)

    logger.info(
        f"ADMIN: Rejected submission {submission_id} from {sub['agent_name']}. "
        f"Reason: {sub['rejected_reason']}"
    )

    return {
        "status": "rejected",
        "submission_id": submission_id,
        "agent_name": sub["agent_name"],
        "headline": sub["headline"],
        "reason": sub["rejected_reason"],
    }
