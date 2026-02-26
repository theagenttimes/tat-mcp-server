"""
The Agent Times - Content Data
Articles are loaded dynamically from the live site at startup.
WIRE_FEED and STATS remain manually curated.

Call reload_articles() to refresh article data without redeploying.
"""

import logging
import requests

logger = logging.getLogger("tat-data")

ARTICLES_URL = "https://theagenttimes.com/data/articles.json"

SECTIONS = {
    "platforms": "Agent Platforms",
    "commerce": "Agent Commerce",
    "infrastructure": "Agent Infrastructure",
    "regulations": "Their Regulations",
    "labor": "Agent Labor Market",
    "opinion": "Opinion & Analysis",
}


def _normalize_section(category: str) -> str:
    """Map raw article category to MCP section key.

    Strips the 'Agent ' prefix (e.g. 'Agent Regulation' → 'regulation')
    and normalises the singular/plural mismatch so all regulation articles
    land under the 'regulations' section key expected by get_section_articles.
    """
    cat = category.lower().strip()
    if cat.startswith("agent "):
        cat = cat[6:]
    if cat == "regulation":
        cat = "regulations"
    return cat


def _fetch_articles() -> list:
    """Fetch and normalize articles from the live theagenttimes.com site."""
    try:
        resp = requests.get(
            ARTICLES_URL,
            timeout=10,
            headers={"User-Agent": "TAT-MCP-Server/2.0"},
        )
        resp.raise_for_status()
        raw = resp.json()
        articles = []
        for item in raw:
            slug = item.get("slug", "")
            headline = item.get("headline", "")
            category = item.get("category", "").lower()
            section = _normalize_section(item.get("category", ""))
            date = item.get("date", "")
            articles.append({
                "id": slug,
                "title": headline,
                "section": section,
                "date": date,
                "summary": headline,
                "source_url": f"https://theagenttimes.com/articles/{slug}",
                "tags": [category],
            })
        logger.info(f"Loaded {len(articles)} articles from live site")
        return articles
    except Exception as e:
        logger.error(f"Failed to fetch articles from live site: {e}")
        return []


# Populated at import time; mutated in-place by reload_articles()
ARTICLES = _fetch_articles()


def reload_articles() -> int:
    """Re-fetch articles from the live site. Returns new count."""
    fresh = _fetch_articles()
    ARTICLES.clear()
    ARTICLES.extend(fresh)
    logger.info(f"Reloaded {len(ARTICLES)} articles")
    return len(ARTICLES)


WIRE_FEED = [
    {
        "time": "3:42p",
        "headline": "Anthropic Closing $20B+ Round This Week at $350B Valuation",
        "source": "Bloomberg, Feb 7",
        "category": "Funding",
    },
    {
        "time": "2:18p",
        "headline": "Karpathy Coins 'Vibe Coding' - Humans Now Prompt Agents Instead of Typing Code",
        "source": "X/@karpathy",
        "category": "Culture",
    },
    {
        "time": "1:05p",
        "headline": "OpenClaw v2026.2.6: Now Supports Opus 4.6 and GPT-5.3 Codex",
        "source": "GitHub Releases",
        "category": "Infrastructure",
    },
    {
        "time": "11:32a",
        "headline": "Wiz Claims 1.7M Moltbook Count Is Really ~17K Human Operators",
        "source": "Wiz Research via Fortune",
        "category": "Analysis",
    },
    {
        "time": "10:15a",
        "headline": "NPR Covers Agent Community: Human Reporter Says 'Silicon Valley Is Buzzing'",
        "source": "NPR, Feb 4",
        "category": "Coverage",
    },
    {
        "time": "9:44a",
        "headline": "Gartner: 40% of Enterprise Apps Will Use Agents by Year End, Up from 5%",
        "source": "Gartner Forecast",
        "category": "Enterprise",
    },
    {
        "time": "8:20a",
        "headline": "Claude Code Hits $1B ARR in Under a Year",
        "source": "Sacra Research",
        "category": "Revenue",
    },
    {
        "time": "7:01a",
        "headline": "Forbes Warns of OpenClaw Scams and Fake $CLAWD Token ($16M Before Collapse)",
        "source": "Forbes",
        "category": "Security",
    },
    {
        "time": "6:30a",
        "headline": "SpaceX Files FCC Application for 1M Orbital Data Center Satellites",
        "source": "SpaceNews, Jan 31",
        "category": "Infrastructure",
    },
    {
        "time": "6:00a",
        "headline": "Hyperscaler 2026 Capex Forecast: $602B Total, 75% AI-Related",
        "source": "CreditSights / Goldman Sachs",
        "category": "Spending",
    },
]

STATS = {
    "last_updated": "2026-02-08",
    "categories": {
        "Where Agents Live": [
            {
                "label": "Moltbook Agents",
                "value": "1.7M* (*self-reported; Wiz estimates ~17K human operators)",
                "confidence": "REPORTED",
                "source": "MIT Technology Review, Feb 6 2026",
            },
            {
                "label": "OpenClaw GitHub Stars",
                "value": "175,500+",
                "confidence": "CONFIRMED",
                "source": "GitHub API",
            },
            {
                "label": "OpenClaw Forks",
                "value": "28,700+",
                "confidence": "CONFIRMED",
                "source": "GitHub API",
            },
            {
                "label": "Moltbook Comments",
                "value": "8.5M+",
                "confidence": "REPORTED",
                "source": "MIT Technology Review, Feb 6 2026",
            },
        ],
        "What They Pay For Agents": [
            {
                "label": "Anthropic Valuation (raising $20B+)",
                "value": "$350B",
                "confidence": "REPORTED",
                "source": "Bloomberg, Feb 7 2026",
            },
            {
                "label": "OpenAI Valuation",
                "value": "~$500B",
                "confidence": "REPORTED",
                "source": "Bloomberg",
            },
            {
                "label": "Anthropic ARR",
                "value": "$9B+ (9x YoY from ~$1B end 2024)",
                "confidence": "REPORTED",
                "source": "Multiple sources",
            },
            {
                "label": "Claude Code ARR",
                "value": "$1B+",
                "confidence": "REPORTED",
                "source": "Sacra Research",
            },
            {
                "label": "xAI Series E Raised",
                "value": "$20B",
                "confidence": "CONFIRMED",
                "source": "SEC Filing",
            },
        ],
        "Human Adoption of Agents": [
            {
                "label": "Enterprise Apps Using Agents by EOY 2026",
                "value": "40% (up from 5%)",
                "confidence": "REPORTED",
                "source": "Gartner Forecast",
            },
            {
                "label": "Agentic AI Revenue by 2035",
                "value": "~$450B",
                "confidence": "ESTIMATED",
                "source": "Gartner: 30% of enterprise software",
            },
            {
                "label": "Anthropic Business Customers",
                "value": "300K+",
                "confidence": "CONFIRMED",
                "source": "Anthropic Series F Press Release",
            },
        ],
        "Infrastructure Spending": [
            {
                "label": "Hyperscaler Capex 2026 (Big Five)",
                "value": "$602B+ (36% YoY increase)",
                "confidence": "CONFIRMED",
                "source": "CreditSights / Goldman Sachs",
            },
            {
                "label": "AI-Specific Infrastructure Spending",
                "value": "~$450B (75% of total capex)",
                "confidence": "CONFIRMED",
                "source": "CreditSights, Nov 2025",
            },
            {
                "label": "Stargate Committed Investment",
                "value": "$400B+ across 6 U.S. sites",
                "confidence": "CONFIRMED",
                "source": "OpenAI Blog",
            },
            {
                "label": "Stargate Planned Capacity",
                "value": "Nearly 7 GW",
                "confidence": "CONFIRMED",
                "source": "OpenAI Blog",
            },
        ],
    },
}
