"""Cover letter and CV bullet drafter — uses only facts from the resume + posting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic

from jobassist.schemas import JobPosting
from jobassist.store import Store, cache_key

_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are a professional job-application writer.
You must use ONLY facts explicitly stated in the resume and the job posting.
Do NOT invent, infer, or embellish any claims.
Respond with valid JSON only — no markdown fences, no commentary."""

_COVER_LETTER_PROMPT = """\
Write a concise, professional cover letter (3–4 paragraphs) for this application.

RESUME:
{resume}

JOB POSTING:
Company: {company}
Role: {role}
Location: {location}
Description:
{description}

Return JSON: {{"cover_letter": "<full letter text>"}}"""

_CV_BULLETS_PROMPT = """\
Write 3–5 achievement-focused CV bullet points tailored to this job.
Each bullet must begin with a strong action verb and be grounded in the resume.

RESUME:
{resume}

JOB POSTING:
Company: {company}
Role: {role}
Description:
{description}

Return JSON: {{"bullets": ["<bullet 1>", "<bullet 2>", ...]}}"""


@dataclass
class DraftedApplication:
    cover_letter: str
    bullets: list[str]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text.strip()


class CoverLetterDrafter:
    """Drafts cover letters and tailored CV bullets from resume + posting facts only."""

    def __init__(self, client: anthropic.AsyncAnthropic, resume: str, store: Store) -> None:
        self._client = client
        self._resume = resume
        self._store = store

    async def draft(self, posting: JobPosting) -> DraftedApplication:
        """Return a cover letter and bullet points for *posting*.

        Results are cached by (resume hash, posting hash) so the same
        posting never costs two LLM calls.
        """
        import hashlib

        resume_hash = hashlib.sha256(self._resume.encode()).hexdigest()
        ck = cache_key("draft_v1", resume_hash, posting.hash)

        cached = self._store.get_cached(ck)
        if cached is not None:
            data = json.loads(cached)
            return DraftedApplication(
                cover_letter=data["cover_letter"],
                bullets=data["bullets"],
            )

        cover_letter = await self._call_llm(
            _COVER_LETTER_PROMPT.format(
                resume=self._resume,
                company=posting.company,
                role=posting.role,
                location=posting.location,
                description=posting.description or "(no description provided)",
            )
        )
        bullets = await self._call_llm(
            _CV_BULLETS_PROMPT.format(
                resume=self._resume,
                company=posting.company,
                role=posting.role,
                description=posting.description or "(no description provided)",
            )
        )

        cl_text = self._extract_cover_letter(cover_letter)
        bullet_list = self._extract_bullets(bullets)

        result = DraftedApplication(cover_letter=cl_text, bullets=bullet_list)
        self._store.set_cached(ck, json.dumps({
            "cover_letter": cl_text,
            "bullets": bullet_list,
        }))
        return result

    async def _call_llm(self, user_prompt: str) -> str:
        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else ""

    def _extract_cover_letter(self, raw: str) -> str:
        try:
            data = json.loads(_strip_fences(raw))
            return str(data.get("cover_letter", ""))
        except (json.JSONDecodeError, AttributeError):
            return ""

    def _extract_bullets(self, raw: str) -> list[str]:
        try:
            data = json.loads(_strip_fences(raw))
            items = data.get("bullets", [])
            if isinstance(items, list):
                return [str(b) for b in items if str(b).strip()]
        except (json.JSONDecodeError, AttributeError):
            pass
        return []
