#!/usr/bin/env bash
# Draft narration from narration.txt with macOS text-to-speech, placed at each cue's start second.
# Output: demo/video/narration.m4a (voice only) and demo/video/demo_narrated.mp4 (demo.mp4 + music ducked + voice).
# Usage (on the Mac):  demo/video/make_narration.sh [voice]      default voice: Kyoko (日本語)
#   Voices: `say -v '?' | grep ja_JP`  — O-Ren / Kyoko / (ダウンロード済みなら) Siri の声も使える。
# Re-record any line with your own voice: put a WAV named cue_NN.wav in demo/video/narration/ and re-run; it is used instead of say.
set -euo pipefail
cd "$(dirname "$0")"
VOICE="${1:-Kyoko}"
FF="${FFMPEG:-$(../../.venv/bin/python -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())')}"
mkdir -p narration
inputs=(); filters=""; mix=""; n=0
while IFS='|' read -r start text; do
  start="$(echo "$start" | xargs)"; text="$(echo "$text" | xargs)"
  [[ -z "$start" || "$start" == \#* ]] && continue
  n=$((n+1)); id=$(printf "%02d" "$n")
  if [[ -f "narration/cue_$id.wav" ]]; then src="narration/cue_$id.wav"
  else src="narration/cue_$id.aiff"; say -v "$VOICE" -r 185 -o "$src" "$text"; fi
  inputs+=(-i "$src")
  filters+="[$((n-1)):a]adelay=$(python3 -c "print(int($start*1000))")|$(python3 -c "print(int($start*1000))")[a$n];"
  mix+="[a$n]"
done < narration.txt
"$FF" -v error -y "${inputs[@]}" -filter_complex "${filters}${mix}amix=inputs=$n:normalize=0,aresample=48000[v]" -map "[v]" -c:a aac -b:a 160k narration.m4a
echo "narration.m4a ($n cues)"
# Mix under demo.mp4: music ducked to 0.35, voice at 1.0
"$FF" -v error -y -i demo.mp4 -i narration.m4a -filter_complex "[0:a]volume=0.35[m];[m][1:a]amix=inputs=2:normalize=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -movflags +faststart demo_narrated.mp4
echo "demo_narrated.mp4"
