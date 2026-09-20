#!/usr/bin/env bash
# Synthesize the short's sound effects with ffmpeg lavfi only (no samples, nothing copyrighted).
# Output: ../audio/<name>.wav, 48 kHz stereo s16, bit-exact and deterministic (fixed noise seeds).
# Usage: tools/make-sfx.sh            (FFMPEG env var overrides the ffmpeg binary)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/../audio"
mkdir -p "$OUT"
FF="${FFMPEG:-$(cat "$HERE/ffmpeg-path.txt" 2>/dev/null || echo ffmpeg)}"

PEAK_DB="${SFX_PEAK_DB:--3.0}"   # every effect is peak-normalised to this; the EDL's gain_db sets the mix
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# enc <filter args...> <out.wav>: render to 32-bit float (no clipping), measure the peak, then write
# a bit-exact 48 kHz stereo s16 WAV peak-normalised to $PEAK_DB. No metadata, deterministic.
enc() {
  local out="${@: -1}"; local args=("${@:1:$#-1}")
  "$FF" -hide_banner -loglevel error -y "${args[@]}" -ac 2 -ar 48000 -c:a pcm_f32le "$TMP/raw.wav"
  local max; max=$("$FF" -hide_banner -i "$TMP/raw.wav" -af volumedetect -f null - 2>&1 \
                   | sed -n 's/.*max_volume: \(-\?[0-9.]*\) dB.*/\1/p')
  local gain; gain=$(awk -v p="$PEAK_DB" -v m="$max" 'BEGIN{printf "%.2f", p-m}')
  "$FF" -hide_banner -loglevel error -y -i "$TMP/raw.wav" -af "volume=${gain}dB" -ac 2 -ar 48000 \
        -c:a pcm_s16le -map_metadata -1 -fflags +bitexact -flags:a +bitexact "$out"
  printf '  %-7s peak %6s dB -> %s dB (gain %s dB)\n' "$(basename "$out" .wav)" "$max" "$PEAK_DB" "$gain"
}

# whoosh (0.40 s): pink noise through a band-pass whose centre sweeps 350 Hz -> 2.4 kHz -> 700 Hz,
# swelling in and decaying out.
enc -filter_complex "
anoisesrc=d=0.40:c=pink:seed=11:a=0.9:r=48000,
asendcmd=c='0.00 bandpass f 350;0.04 bandpass f 520;0.08 bandpass f 800;0.12 bandpass f 1200;0.16 bandpass f 1800;0.20 bandpass f 2400;0.24 bandpass f 1900;0.28 bandpass f 1400;0.32 bandpass f 1000;0.36 bandpass f 700',
bandpass=f=350:width_type=o:w=1.4,bandpass=f=350:width_type=o:w=1.4,lowpass=f=6000,
afade=t=in:d=0.22:curve=qsin,afade=t=out:st=0.22:d=0.18:curve=exp,
volume=4.0" "$OUT/whoosh.wav"

# impact (0.18 s): crisp club-on-ball "tock" = high-passed noise click + two short decaying sines.
enc -filter_complex "
anoisesrc=d=0.03:c=white:seed=3:a=0.8:r=48000,highpass=f=2500,highpass=f=2500,afade=t=out:d=0.025:curve=exp,apad=whole_dur=0.18[n];
aevalsrc='0.55*sin(2*PI*1480*t)*exp(-t*38)+0.22*sin(2*PI*2290*t)*exp(-t*70)+0.18*sin(2*PI*620*t)*exp(-t*55)':d=0.18:s=48000[s];
[n][s]amix=inputs=2:normalize=0,afade=t=out:st=0.14:d=0.04" "$OUT/impact.wav"

# click (0.04 s): dry UI tick.
enc -filter_complex "
aevalsrc='0.5*sin(2*PI*3400*t)*exp(-t*450)+0.25*sin(2*PI*1700*t)*exp(-t*300)':d=0.04:s=48000" "$OUT/click.wav"

# neural (0.90 s): a few soft sine blips (pentatonic-ish) with a gentle shimmer echo.
enc -filter_complex "
aevalsrc='0.16*sin(2*PI*880*t)*exp(-(t-0.00)*14)*gte(t,0.00)+0.14*sin(2*PI*1319*(t-0.11))*exp(-(t-0.11)*14)*gte(t,0.11)+0.13*sin(2*PI*1175*(t-0.23))*exp(-(t-0.23)*14)*gte(t,0.23)+0.12*sin(2*PI*1760*(t-0.34))*exp(-(t-0.34)*16)*gte(t,0.34)+0.11*sin(2*PI*1568*(t-0.47))*exp(-(t-0.47)*16)*gte(t,0.47)+0.09*sin(2*PI*2093*(t-0.58))*exp(-(t-0.58)*18)*gte(t,0.58)':d=0.90:s=48000,
aecho=0.8:0.6:70|130:0.35|0.2,lowpass=f=6000,afade=t=out:st=0.70:d=0.20" "$OUT/neural.wav"

# pop (0.08 s): very subtle upward blip for captions.
enc -filter_complex "
aevalsrc='0.35*sin(2*PI*(420*t+2600*t*t))*exp(-t*55)':d=0.08:s=48000,afade=t=in:d=0.004" "$OUT/pop.wav"

# clink (0.45 s): ball on the cup rim = two quick metallic, inharmonic high pings.
enc -filter_complex "
aevalsrc='(0.22*sin(2*PI*2750*t)+0.14*sin(2*PI*4130*t)+0.08*sin(2*PI*6020*t))*exp(-t*22)+gte(t,0.085)*(0.16*sin(2*PI*2900*(t-0.085))+0.10*sin(2*PI*4390*(t-0.085))+0.06*sin(2*PI*6350*(t-0.085)))*exp(-(t-0.085)*26)':d=0.45:s=48000,
afade=t=in:d=0.002,afade=t=out:st=0.35:d=0.10" "$OUT/clink.wav"

# womp (0.60 s): short comedic descending tone (300 -> ~120 Hz slide with a little wobble), soft.
enc -filter_complex "
aevalsrc='0.30*(sin(2*PI*(300*t-150*t*t)+1.2*sin(2*PI*6*t))+0.35*sin(4*PI*(300*t-150*t*t)))':d=0.60:s=48000,
lowpass=f=1400,afade=t=in:d=0.02,afade=t=out:st=0.30:d=0.30:curve=qsin" "$OUT/womp.wav"

# vineboom (1.60 s): the meme "vine boom" hit, synthesized: a deep sub thud whose pitch drops
# 160 -> ~42 Hz with a slow decay, a second harmonic for punch, a short noise transient on top,
# soft-clipped for grit, then a dark cavernous echo tail.
enc -filter_complex "
aevalsrc='0.9*sin(2*PI*(42*t+118*(1-exp(-t*9))/9))*exp(-t*2.6)+0.35*sin(4*PI*(42*t+118*(1-exp(-t*9))/9))*exp(-t*4.5)':d=1.60:s=48000[b];
anoisesrc=d=0.05:c=brown:seed=5:a=0.9:r=48000,lowpass=f=900,afade=t=out:d=0.05:curve=exp,apad=whole_dur=1.60[n];
[b][n]amix=inputs=2:normalize=0,volume=2.2,asoftclip=type=tanh,lowpass=f=2200,
aecho=0.8:0.55:90|170|260:0.35|0.25|0.15,afade=t=in:d=0.003,afade=t=out:st=1.10:d=0.50:curve=qsin" "$OUT/vineboom.wav"

echo "SFX written to $OUT"
