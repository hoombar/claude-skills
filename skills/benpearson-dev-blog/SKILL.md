---
name: benpearson-dev-blog
description: Use when generating, drafting, editing, or preparing Hugo blog posts for benpearson.dev, especially with local preview, page bundles, frontmatter, draft posts, Cloudflare Pages, or Ben's website writing voice.
---

# benpearson.dev Blog

Generate draft Hugo posts directly in the `benpearson.dev` repository while preserving Ben's writing voice and keeping publishing explicit.

## Core Rules

- Work directly in `/home/ben/dev/benpearson.dev` unless the user gives another path.
- Do not use Obsidian for this workflow. Do not read from or write to the vault unless the user explicitly asks.
- Read `/home/ben/dev/benpearson.dev/README.md` before creating or editing a post.
- Create posts as Hugo page bundles: `content/writing/<slug>/index.md`.
- Put post media in the same bundle as `index.md`; reference media with relative paths.
- Set `draft: true` by default.
- Do not commit, push, or publish unless the user explicitly asks.
- Preview drafts with `hugo server -D --port 1313`.

## Required Frontmatter

Use this shape unless the repo README has changed:

```yaml
---
title: "Readable Public Title"
slug: readable-public-title
content_type: post
summary: "Short summary for listings."
date: YYYY-MM-DD
draft: true
tags:
  - example
---
```

`content_type` must be `post` or `lab`. Use `lab` for experiments, build notes, implementation write-ups, and rougher practical notes. Use `post` for more polished articles.

## Workflow

1. Read the Hugo repo README.
2. If the topic, angle, `content_type`, or source material is unclear, ask before drafting.
3. Choose a lowercase hyphenated slug.
4. Create `content/writing/<slug>/index.md` with `draft: true`.
5. Draft using `references/ben-website-writing-style-profile.md`.
6. Run an anti-AI editing pass before presenting the result.
7. Tell the user how to preview locally.

## Voice Rules

Use the bundled style profile as the source of truth. In short:

- Write like clear written conversation.
- Prefer first person when discussing Ben's own process, judgement, or experiments.
- Use plain, practical words over corporate or literary language.
- Prefer flowing sentences over clipped, choppy prose.
- Be confident where the point is clear, but leave room for judgement.
- Avoid generic AI openings, SaaS brochure language, over-polished symmetry, and forced casualness.

## Common Mistakes

| Mistake | Correct behaviour |
|---|---|
| Creating `src/content/posts/*.md` | Use `content/writing/<slug>/index.md` |
| Creating `content/lab-notes/*.md` | Use `content/writing/<slug>/index.md` with `content_type: lab` |
| Putting images in `static/images/...` | Put media beside `index.md` in the page bundle |
| Publishing because the user said "quickly" | Keep `draft: true` unless explicitly told to publish |
| Reading the vault style note at runtime | Use the bundled style reference in this skill |
| Writing generic AI prose | Revise against the style profile before presenting |

## Publishing

Publishing is a separate explicit action. To publish, the user must ask for it or approve it clearly. The publishing edit is to remove `draft: true` or set `draft: false`, then commit and push according to the repo workflow.

If the user asks to "push it live", "publish", "deploy", or similar, treat that as explicit publishing intent. If the wording is only "draft", "preview", "prepare", "write", or "generate", keep `draft: true` and do not commit or push.
