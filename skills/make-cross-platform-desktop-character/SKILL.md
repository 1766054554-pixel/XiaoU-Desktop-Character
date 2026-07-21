---
name: make-cross-platform-desktop-character
description: Build or customize a local Windows and macOS desktop character from one user-owned image. Use when Codex must analyze identity features, generate a consistent transparent pixel character, enforce character and walking approval gates, organize action sprites, integrate them into XiaoU Desktop Character, validate privacy and anatomy, test the application, or package runnable Windows and macOS builds.
---

# Make a Cross-Platform Desktop Character

Turn one user-owned reference image into a tested local desktop character without publishing the source image. Work inside an existing XiaoU Desktop Character checkout and preserve its code structure.

## Start Safely

1. Read `AGENTS.md`, `文件夹说明.md`, and `agent-guide/AGENT_GUIDE.md` completely.
2. Run `scripts/preflight.py --project <repo>` from this skill.
3. Keep source photos, references, candidates, source sheets, and workflow state under the Git-ignored `user_assets/` tree.
4. Never upload private images to GitHub, Issues, Releases, remote APIs, or public video assets.
5. Stop and explain any missing system software instead of installing it without permission.

## Register and Analyze the Character

1. Register the image with the repository workflow tool so the original remains local.
2. Analyze the face shape, eyes, brows, hair, clothing, accessories, body proportions, palette, and overall temperament.
3. Ask the user to choose preserved style, light chibi, or full chibi when not already stated.
4. Use the available image-generation capability to create exactly one transparent standard candidate. Keep distinctive features; do not reuse a generic face.
5. Register the candidate and open the repository confirmation window.
6. Pause until the user personally approves the character. Do not generate action sheets before approval.

## Build the Action Set

Read [references/action-contract.md](references/action-contract.md) before generating images.

1. Use the approved candidate as the only identity reference.
2. Generate transparent 3x2 sheets for expressions, daily actions, props, front-facing poses, and outfits.
3. Keep all limbs visible and anatomically coherent. Reject extra heads, hands, fingers, legs, cropped hair, opaque corners, or inconsistent scale.
4. Generate a 12-frame walk with alternating feet, planted contacts, body compression, lift, and restrained arm swing. Do not simulate walking by shaking or translating a static body.
5. Create the GIF preview and pause for the user's walking approval.
6. Continue only after both the character and walk gates are approved.

## Integrate and Package

1. Run `tools/prepare_custom_pet.py` to normalize frames to the shared 560x500 transparent canvas.
2. Inspect the generated action contact sheet and walk GIF directly.
3. Run the full tests and a real GUI smoke test on the current platform.
4. Read [references/platform-build.md](references/platform-build.md), then build the requested Windows and/or macOS package.
5. Read [references/quality-checklist.md](references/quality-checklist.md) and complete every release check.
6. Tell the user the exact `.exe` or `.app` to open. Do not hand off only source code or commands.

For commissioned customization, optionally copy `examples/interaction-pack-romantic.json` to the local `user_assets/interaction_pack.json` and replace its actions and dialogue with text the customer approved. Keep that pack local unless the customer explicitly authorizes publication.

## Preserve the Two Gates

- Gate 1: confirm that the standard character resembles the reference.
- Gate 2: confirm that the walk has real steps and a natural rhythm.

Never mark either gate approved on the user's behalf and never bypass `workflow.json` checks.
