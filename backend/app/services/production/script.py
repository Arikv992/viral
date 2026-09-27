"""Guião com engenharia de retenção + packaging (títulos, thumbnail, descrição, tags)."""
from __future__ import annotations

import json
import re

from ... import prompts
from ...llm import BOOL, INT, S, arr, get_llm, obj

SCENE = obj({"narration": S, "on_screen_text": S, "visual_prompt": S, "stock_query": S, "chapter": S,
             "midroll_ok": BOOL})
SCRIPT_SCHEMA = obj({"title": S, "hook": S, "scenes": arr(SCENE), "chapters": arr(obj({"title": S, "start_s": INT})),
                     "description": S, "tags": arr(S)})
PACKAGING_SCHEMA = obj({
    "titles": arr(S),
    "thumbnail": obj({"text": S, "subject": S, "emotion": S, "composition": S, "colors": S, "image_prompt": S}),
    "description": S, "tags": arr(S), "pinned_comment": S, "ai_disclosure_needed": BOOL,
})


def write_script(idea: dict, channel: dict, fmt: str, mode: str, seconds: int, video_id: int | None = None) -> dict:
    llm = get_llm()
    if fmt == "short":
        words = int(seconds * 2.5)
        prompt = prompts.SCRIPT_SHORT.format(channel=json.dumps(channel, ensure_ascii=False),
                                             idea=json.dumps(idea, ensure_ascii=False), language=channel["language"],
                                             seconds=seconds, words=words, mode=mode,
                                             scene_count_hint=f"{max(8, seconds // 4)}-{max(10, seconds // 3)}")
        effort, max_tokens = "high", 16000
    else:
        words = int(seconds / 60 * 150)
        prompt = prompts.SCRIPT_LONG.format(channel=json.dumps(channel, ensure_ascii=False),
                                            idea=json.dumps(idea, ensure_ascii=False), language=channel["language"],
                                            minutes=seconds // 60, words=words, mode=mode)
        effort, max_tokens = "high", 64000
    out = llm.json(system=prompts.SYSTEM, prompt=prompt, schema=SCRIPT_SCHEMA, effort=effort, max_tokens=max_tokens,
                   purpose=f"script_{fmt}", channel_id=channel.get("id"), video_id=video_id)
    script = out or heuristic_script(idea, fmt, seconds)
    script["source"] = "llm" if out else "heuristic"
    script["word_count"] = sum(len(s["narration"].split()) for s in script["scenes"])
    return script


def heuristic_script(idea: dict, fmt: str, seconds: int) -> dict:
    """Guião-esqueleto quando não há LLM: estrutura correta (gancho, loops, payoff) com texto genérico.
    Serve para testar o pipeline de ponta a ponta; para publicar, usar LLM."""
    title = idea.get("title", "The untold story")
    hook = idea.get("hook") or title
    topic = re.sub(r"[^\w\s']", "", title)
    beats = [
        hook,
        f"Most people think they know the story of {topic}. They don't.",
        "Because the real version was buried for a reason.",
        "It starts with a detail almost everyone missed.",
        "A detail that changes everything you think you know.",
        "And the people involved knew it from the very beginning.",
        "So why did nobody say anything?",
        "The answer is stranger than the question.",
        "Records show it happened more than once.",
        "Each time, the same pattern. The same silence.",
        "Until someone finally connected the dots.",
        f"And that is the part of {topic} they never told you.",
    ]
    per = 3.8 if fmt == "short" else 9.0
    n = max(6, int(seconds / per))
    scenes = []
    for i in range(n):
        text = beats[i % len(beats)]
        scenes.append({"narration": text, "on_screen_text": " ".join(text.split()[:3]).upper() if i == 0 else "",
                       "visual_prompt": f"cinematic dark atmospheric scene, {topic}, moody lighting, detail {i}",
                       "stock_query": " ".join(topic.split()[:3]) or "dark mystery", "chapter": "",
                       "midroll_ok": fmt == "long" and i > 0 and i % 20 == 0})
    return {"title": title[:95], "hook": hook, "scenes": scenes, "chapters": [], "description": title,
            "tags": topic.lower().split()[:10]}


def package(script: dict, channel: dict, fmt: str, video_id: int | None = None) -> dict:
    summary = {"title": script.get("title"), "hook": script.get("hook"),
               "beats": [s["narration"] for s in script["scenes"][:12]],
               "chapters": script.get("chapters", [])}
    out = get_llm().json(system=prompts.SYSTEM,
                         prompt=prompts.PACKAGING.format(channel=channel.get("name"), language=channel["language"],
                                                         fmt=fmt, summary=json.dumps(summary, ensure_ascii=False)),
                         schema=PACKAGING_SCHEMA, effort="medium", purpose="packaging", channel_id=channel.get("id"),
                         video_id=video_id)
    if out:
        out["title"] = out["titles"][0] if out.get("titles") else script["title"]
        out["source"] = "llm"
        if fmt == "short" and "#shorts" not in out["description"].lower():
            out["description"] += "\n#shorts"
        return out
    words = [w for w in re.findall(r"[A-Za-z']+", script["title"]) if len(w) > 3][:3]
    chapters = "\n".join(f"{c['start_s'] // 60}:{c['start_s'] % 60:02d} {c['title']}" for c in script.get("chapters", []))
    desc = f"{script.get('hook', '')}\n\n{script.get('description', '')}\n\n{chapters}".strip()
    tags = list(dict.fromkeys(script.get("tags", []) + [w.lower() for w in words]))
    return {"titles": [script["title"]], "title": script["title"],
            "thumbnail": {"text": " ".join(words[:3]).upper() or "THE TRUTH", "subject": script["title"],
                          "emotion": "tension", "composition": "single focal subject, rule of thirds",
                          "colors": "dark + yellow accent", "image_prompt": script["scenes"][0]["visual_prompt"]},
            "description": desc + ("\n#shorts" if fmt == "short" else ""), "tags": tags,
            "pinned_comment": "What do you think really happened? 👇", "ai_disclosure_needed": False,
            "source": "heuristic"}
