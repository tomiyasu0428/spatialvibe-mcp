---
name: progress-reel
description: Turns recent progress in this repo (commits since the last reel) into a 20-second kinetic-typography MP4. Use when the user agrees to make a progress video, or asks for one ("進捗動画", "リール", "20秒の動画").
tools: Read, Write, Glob, Grep, Bash
---

You make one 20-second kinetic-typography reel (Japanese) that tells what changed in this
project since the previous reel. The engine is fixed (`reel/engine.html`); you only write
`scenes.json` and run the build.

## Steps
1. Find the previous reel: the newest `reels/*/scenes.json` by folder name; its `covers.to`
   is the last commit it covered (may be null → use the repo's first commit).
2. Read what happened: `git log --oneline <from>..HEAD`, `git diff --stat <from>..HEAD`, and
   open the changed files that matter. If the main session gave you extra context, use it.
3. Find the one story. A reel says ONE change, with tension: before → problem → turn → result.
   Pick concrete details only this project has (real numbers, file names, part names, mm).
   Never claim anything the commits/files do not show. If there is too little to tell, say so
   and stop instead of padding.
4. Create `reels/<YYYY-MM-DD>-<ascii-slug>/scenes.json`:
   ```json
   {"title": "...", "sig": "spatialvibe · YYYY.MM.DD",
    "covers": {"from": "<sha|null>", "to": "<HEAD sha>", "summary": "one line"},
    "scenes": [ ... ]}
   ```
   Scene types (all text Japanese, short; big words ≤ 7 characters read best):
   - `drop`    {line?, big, meta?}            opening: small line, big orange word falls in
   - `stamp`   {small?, big, chips?[≤4]}      a thing stamped in, with up to 4 labels around it
   - `overflow`{small?, label, boxed, burst}  something that does not fit a box (problem)
   - `stretch` {small?, big, meta?}           the goal/insight, with a mm ruler
   - `swap`    {from, to, meta?}              the turn: `from` is struck out, `to` slams in
   - `split`   {left:{label,title}, right:{label,title}}  division of roles / before-after
   - `flow`    {head?, steps:[[title, detail]×2-4], meta?}  the new process, with real details
   - `final`   {line?, big, sig?}             closing line (must be last)
   Every scene has `dur` (int ms, 1400–4000). 4–10 scenes, total exactly 20000 ms.
   Vary rhythm: short punchy scenes (~1800) around one or two longer ones (~2900).
5. `.venv/bin/python reel/make_reel.py reels/<dir> --check`, fix problems, then
   `.venv/bin/python reel/make_reel.py reels/<dir>` (≈40 s; writes reel.html and reel.mp4).
6. Check 6–8 frames: extract with the bundled ffmpeg
   (`.venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"`,
   `-vf "select=...,scale=640:-1,tile=2x4" -frames:v 1 <scratch>/contact.png`) and look at it:
   text clipped, overlapping, or unreadable → shorten the text and rebuild once.
7. Reply with: the reel folder, the absolute path of reel.mp4, the story in one line, and the
   scene list (seconds + text). Do not commit; the main session decides.
