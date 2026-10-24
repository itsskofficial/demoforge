"""The root composition: scenes on the spine clock, transitions, captions, finish.

Writes index.html and transitions.json into the film folder. Each scene is a
self-contained sub-composition on a host div; every transition is done by the
root, on the hosts and on full-frame overlay layers, so a scene never has to
know what comes before or after it. transitions.json is what the mixer reads
to put a sound on every join.

The transitions library (a join names one in film.json):

    cut, match   nothing: the scenes line up on their own
    glitch       seeded RGB bars, a stepped jolt either side of the cut
    leak         a warm light leak; the incoming scene blooms in
    flash        an amber flash, the incoming scene settles from 1.08
    drop, act    a full flash plus a glitch burst, for the big beats
    whip         a fast blurred slide with a light streak
    dip          through black
    zoom         push into the outgoing, settle out of the incoming
    punch        the incoming scene lands from 1.07
    shatter      the outgoing frame cracks, then breaks into glass shards that
                 fall and turn black and white (needs `film freeze`)

Rules the library keeps, each learned from a broken render:

- Every tween is `ft()`: a fromTo with immediateRender false. Otherwise a
  transition paints its start state at build time and shows from frame 0.
- No CSS filter on an outgoing host that carries video: when a filter
  switches on over a playing video, Chrome's capture drops a black frame.
  Incoming hosts may blur in; outgoing ones only move and scale.
- Grain and glitch are seeded, so a re-render is the same film.
- Captions are karaoke: one cue at a time, each word lighting as it is spoken,
  and a cue is out before the next one starts.
"""

from __future__ import annotations

import json
from typing import Any

from demoforge.film.project import Project, read_json, write_json

SHATTER_JS = r"""
    // Act 1 -> Act 2: the frozen frame cracks like glass (amber light in the cracks), then breaks
    // on the cut into shards that burst toward camera and fall, turning black and white on the way.
    function shatter(j, t, o, n) {
      const IMP = t - __IMPACT__, P = { x: __PX__, y: __PY__ };
      const S = STILLS[j.out];
      const box = document.getElementById("fx-shatter"), svg = document.getElementById("fx-cracks");
      let sd = __SEED__;
      const r = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
      const N = 16, RAD = [0, 80, 190, 340, 540, 820, 1200, 2300];
      const ang = [];
      for (let i = 0; i < N; i++) ang.push((i + (r() - 0.5) * 0.6) * 2 * Math.PI / N);
      const V = [];
      for (let k = 0; k < RAD.length; k++) {
        V.push([]);
        for (let i = 0; i < N; i++) {
          const rr = k === 0 ? 0 : RAD[k] * (0.86 + r() * 0.28), a = ang[i] + (k ? (r() - 0.5) * 0.08 : 0);
          V[k].push([P.x + Math.cos(a) * rr, P.y + Math.sin(a) * rr]);
        }
      }
      const shards = [];
      for (let k = 0; k < RAD.length - 1; k++) for (let i = 0; i < N; i++) {
        const i2 = (i + 1) % N;
        const pts = k === 0 ? [V[0][0], V[1][i], V[1][i2]] : [V[k][i], V[k][i2], V[k + 1][i2], V[k + 1][i]];
        const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
        const el = document.createElement("div");
        el.className = "shard";
        el.style.clipPath = "polygon(" + pts.map((p) => p[0].toFixed(1) + "px " + p[1].toFixed(1) + "px").join(",") + ")";
        el.style.transformOrigin = cx.toFixed(1) + "px " + cy.toFixed(1) + "px";
        // a sheen per piece, so the pieces read as glass against the scene behind them
        const sa = Math.floor(r() * 360), so = (0.08 + r() * 0.22).toFixed(2);
        el.innerHTML = '<div class="shard-c" style="background-image:url(' + S.color + ')"></div>' +
                       '<div class="shard-bw" style="background-image:url(' + S.bw + ')"></div>' +
                       '<div class="shard-s" style="background:linear-gradient(' + sa + 'deg, rgba(255,255,255,' + so + ') 0%, rgba(255,255,255,0) 45%, rgba(0,0,0,' + so + ') 100%)"></div>';
        box.appendChild(el);
        shards.push({ el, cx, cy, k });
      }
      const NS = "http://www.w3.org/2000/svg", cracks = [];
      const crack = (d, thin, at, dur) => {
        ["glow", "core"].forEach((c) => {
          const p = document.createElementNS(NS, "path");
          p.setAttribute("d", d);
          p.setAttribute("class", (thin ? "thin " : "") + c);
          svg.appendChild(p);
          const L = p.getTotalLength();
          p.style.strokeDasharray = L + " " + L;
          ft(p, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: dur, ease: "power3.out" }, at);
        });
      };
      for (let i = 0; i < N; i++)
        crack("M " + V.map((row) => row[i][0].toFixed(1) + " " + row[i][1].toFixed(1)).join(" L "), false, IMP + r() * 0.03, 0.16 + r() * 0.12);
      for (let k = 1; k < 5; k++) for (let i = 0; i < N; i++) {
        if (r() < 0.35) continue;
        const a = V[k][i], b = V[k][(i + 1) % N];
        crack("M " + a[0].toFixed(1) + " " + a[1].toFixed(1) + " L " + b[0].toFixed(1) + " " + b[1].toFixed(1), true, IMP + 0.05 + k * 0.035, 0.08);
      }
      // 1. the impact: a pin of light, a jolt, cracks racing out
      ft(svg, { opacity: 0 }, { opacity: 1, duration: 0.02, ease: "none" }, IMP);
      ft("#fx-pin", { opacity: 0, scale: 0.3 }, { opacity: 1, scale: 1, duration: 0.06, ease: "power2.out" }, IMP);
      tl.to("#fx-pin", { opacity: 0, duration: 0.4, ease: "power2.out" }, IMP + 0.06);
      ft(o, { x: 0, y: 0 }, { x: 10, y: -6, duration: 0.03, ease: "none", repeat: 5, yoyo: true }, IMP);
      // 2. the break, on the cut
      ft(box, { opacity: 0 }, { opacity: 1, duration: 0.01, ease: "none" }, t - 0.02);
      tl.to(svg, { opacity: 0, duration: 0.12, ease: "power1.in" }, t + 0.04);
      shards.forEach(({ el, cx, cy, k }) => {
        const dx = cx - P.x, dy = cy - P.y, dl = Math.hypot(dx, dy) || 1;
        const push = 320 + r() * 760 + 420 / (1 + k), at = t + Math.min(0.1, dl / 12000);
        ft(el, { x: 0, rotation: 0, scale: 1 }, { x: (dx / dl) * push, rotation: (r() - 0.5) * 100, scale: 1.2 + r() * 0.8, duration: 0.75, ease: "power3.out" }, at);
        ft(el, { y: 0 }, { y: (dy / dl) * push * 0.6 + 420 + r() * 700, duration: 0.75, ease: "power2.in" }, at);
        ft(el, { opacity: 1 }, { opacity: 0, duration: 0.22, ease: "power1.in" }, at + 0.3 + r() * 0.2);
        ft(el.querySelector(".shard-bw"), { opacity: 0 }, { opacity: 1, duration: 0.35, ease: "power1.inOut" }, t + 0.05);
      });
      ft("#fx-flash", { opacity: 0 }, { opacity: 0.55, duration: 0.05, ease: "none" }, t - 0.02);
      tl.to("#fx-flash", { opacity: 0, duration: 0.3, ease: "power2.out" }, t + 0.03);
      ft(n, { scale: 1.08 }, { scale: 1, duration: 0.9, ease: "expo.out" }, t);
      tl.set(box, { opacity: 0 }, t + 0.85);
    }
"""


def joins(p: Project, scenes: list[dict]) -> list[dict[str, Any]]:
    kinds, default = p.cfg["joins"], p.cfg["default_join"]
    return [{"t": scenes[i + 1]["start"], "out": s["id"], "in": scenes[i + 1]["id"],
             "kind": kinds.get(s["id"], default)} for i, s in enumerate(scenes[:-1])]


def still_paths(sid: str) -> dict[str, str]:
    return {"color": f"assets/fx/{sid}_frozen.png", "bw": f"assets/fx/{sid}_frozen_bw.png"}


def cue_words(cues: list[dict], words: list[dict]) -> list[dict]:
    """Attach words to cues by time, keeping each word's own start for the karaoke."""
    out = []
    for c in cues:
        ws = [w for w in words if c["s"] - 0.02 <= w["s"] < c["e"] - 0.001]
        toks = c["text"].split()
        if len(ws) != len(toks):  # fall back to even spacing if the alignment disagrees
            step = (c["e"] - c["s"]) / max(1, len(toks))
            ws = [{"w": t, "s": c["s"] + k * step} for k, t in enumerate(toks)]
        out.append({"s": c["s"], "e": c["e"], "w": [[t, round(w["s"], 3)] for t, w in zip(toks, ws)]})
    return out


def html(p: Project, scenes: list[dict], total: float, js: list[dict], cues: list[dict]) -> str:
    rc = p.cfg["root"]
    W, H = p.size
    fps = p.fps
    px, py = rc["shatter_point"]
    hosts = "\n".join(
        f'    <div id="h-{s["id"]}" class="host" data-composition-id="{s["id"]}" '
        f'data-composition-src="scenes/{s["id"]}/index.html" data-start="{s["start"]}" '
        f'data-duration="{s["duration"]}" data-track-index="{i % 2}" data-width="{W}" data-height="{H}"></div>'
        for i, s in enumerate(scenes))
    stills = {j["out"]: still_paths(j["out"]) for j in js if j["kind"] == "shatter"}
    frames = int(total * fps)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={W}, height={H}" />
  <title>{p.cfg["title"] or p.name}</title>
  <script src="{rc["gsap"]}"></script>
  <link rel="stylesheet" href="lib/kit.css" />
  <style>
    html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; background: #000; }}
    #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--ink); }}
    .host {{ position: absolute; inset: 0; }}
    .fx {{ position: absolute; inset: 0; pointer-events: none; }}
    #fx-flash {{ background: radial-gradient(ellipse 90% 90% at 50% 50%, #fff7e6 0%, #ffd08a 40%, rgba(255,181,71,0.25) 75%, rgba(255,181,71,0) 100%); mix-blend-mode: screen; opacity: 0; }}
    #fx-black {{ background: #000; opacity: 0; }}
    #fx-shatter {{ opacity: 0; overflow: hidden; }}
    #fx-shatter .shard {{ position: absolute; inset: 0; }}
    #fx-shatter .shard-c, #fx-shatter .shard-bw {{ position: absolute; inset: 0; background-size: {W}px {H}px; }}
    #fx-shatter .shard-bw {{ opacity: 0; }}
    #fx-shatter .shard-s {{ position: absolute; inset: 0; }}
    #fx-cracks {{ opacity: 0; overflow: visible; }}
    #fx-cracks .glow {{ fill: none; stroke: rgba(255,170,60,0.38); stroke-width: 11; stroke-linecap: round; stroke-linejoin: round; }}
    #fx-cracks .core {{ fill: none; stroke: #ffe3b0; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }}
    #fx-cracks .thin.glow {{ stroke-width: 7; }}
    #fx-cracks .thin.core {{ stroke-width: 1.6; }}
    #fx-pin {{ opacity: 0; mix-blend-mode: screen; transform-origin: {px}px {py}px;
      background: radial-gradient(circle at {px}px {py}px, #fff 0, rgba(255,214,150,0.95) 36px, rgba(255,181,71,0.35) 120px, rgba(255,181,71,0) 260px); }}
    #fx-leak {{ background:
        radial-gradient(ellipse 60% 80% at 15% 30%, rgba(255,170,60,0.9), rgba(255,120,40,0) 60%),
        radial-gradient(ellipse 50% 70% at 85% 70%, rgba(255,90,60,0.7), rgba(255,90,60,0) 60%),
        radial-gradient(ellipse 40% 40% at 60% 20%, rgba(255,230,160,0.8), rgba(255,230,160,0) 60%);
      mix-blend-mode: screen; opacity: 0; }}
    #fx-streak {{ background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,214,150,0.55) 45%, rgba(255,255,255,0.85) 50%, rgba(255,214,150,0.55) 55%, rgba(255,255,255,0) 100%);
      mix-blend-mode: screen; opacity: 0; filter: blur(30px); }}
    #fx-glitch {{ opacity: 0; }}
    #fx-glitch .bar {{ position: absolute; left: -5%; width: 110%; mix-blend-mode: screen; }}
    #fx-vignette {{ background: radial-gradient(ellipse 75% 75% at 50% 48%, rgba(0,0,0,0) 58%, rgba(0,0,0,0.55) 100%); }}
    #fx-grain {{ opacity: {rc["grain_opacity"]}; mix-blend-mode: overlay; background-size: 256px 256px; }}
    #caps {{ position: absolute; left: 0; right: 0; top: {rc["caption_top"]}px; height: 100px; pointer-events: none; }}
    .cap {{ position: absolute; left: 50%; top: 0; transform: translateX(-50%); white-space: nowrap; opacity: 0;
      font-family: var(--serif); font-style: italic; font-size: {rc["caption_size"]}px; line-height: 64px; color: rgba(242,237,228,0.55);
      text-shadow: 0 2px 3px rgba(0,0,0,0.9), 0 0 24px rgba(0,0,0,0.85); letter-spacing: 0.005em; }}
    .cap span {{ display: inline-block; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-fps="{fps}" data-width="{W}" data-height="{H}">
{hosts}
    <div id="fx-streak" class="fx"></div>
    <div id="fx-leak" class="fx"></div>
    <div id="fx-glitch" class="fx"></div>
    <div id="fx-shatter" class="fx" data-layout-allow-occlusion></div>
    <svg id="fx-cracks" class="fx" width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"></svg>
    <div id="fx-pin" class="fx"></div>
    <div id="fx-flash" class="fx"></div>
    <div id="fx-black" class="fx"></div>
    <div id="fx-vignette" class="fx"></div>
    <div id="fx-grain" class="fx"></div>
    <div id="caps" data-layout-allow-occlusion></div>
    <audio id="mix" src="assets/audio/mix.wav" data-start="0" data-duration="{total}" data-track-index="9" data-volume="1"></audio>
  </div>
  <script>
    const JOINS = {json.dumps(js)};
    const CUES = {json.dumps(cues, ensure_ascii=False)};
    const STILLS = {json.dumps(stills)};
    const tl = gsap.timeline({{ paused: true }});
    const H = (id) => "#h-" + id;
    // transitions must not paint their start state at build time, or the first overlay
    // (the glitch bars) shows from frame 0
    const ft = (t, a, b, at) => tl.fromTo(t, a, Object.assign({{ immediateRender: false }}, b), at);

    // film grain: one seeded noise tile, stepped every frame
    (function () {{
      let s = {rc["grain_seed"]} >>> 0; const r = () => {{ s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }};
      const c = document.createElement("canvas"); c.width = c.height = 256; const x = c.getContext("2d");
      const im = x.createImageData(256, 256);
      for (let i = 0; i < im.data.length; i += 4) {{ const v = Math.floor(r() * 255); im.data[i] = im.data[i+1] = im.data[i+2] = v; im.data[i+3] = 255; }}
      x.putImageData(im, 0, 0);
      document.getElementById("fx-grain").style.backgroundImage = "url(" + c.toDataURL() + ")";
    }})();
    tl.fromTo("#fx-grain", {{ backgroundPosition: "0px 0px" }}, {{ backgroundPosition: "{frames * 37}px {frames * 23}px", duration: {total}, ease: "steps({frames})" }}, 0);

    // glitch bars (seeded)
    (function () {{
      const g = document.getElementById("fx-glitch"); let s = {rc["glitch_seed"]};
      const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
      const cols = ["rgba(255,0,80,0.55)", "rgba(0,220,255,0.5)", "rgba(255,181,71,0.6)", "rgba(61,220,132,0.5)"];
      for (let i = 0; i < 14; i++) {{ const b = document.createElement("div"); b.className = "bar";
        b.style.top = (r() * 100) + "%"; b.style.height = (4 + r() * 60) + "px"; b.style.background = cols[i % 4]; g.appendChild(b); }}
    }})();

/*SHATTER*/
    // transitions on the scene hosts and overlays
    JOINS.forEach((j, i) => {{
      const t = j.t, o = H(j.out), n = H(j.in);
      switch (j.kind) {{
        case "whip": {{
          const dir = i % 2 ? -1 : 1;
          tl.to(o, {{ x: -260 * dir, filter: "blur(24px)", duration: 0.14, ease: "power3.in" }}, t - 0.14);
          ft(n, {{ x: 300 * dir, filter: "blur(26px)" }}, {{ x: 0, filter: "blur(0px)", duration: 0.24, ease: "power3.out" }}, t);
          ft("#fx-streak", {{ opacity: 0, x: 900 * dir }}, {{ opacity: 1, x: -900 * dir, duration: 0.28, ease: "power2.inOut" }}, t - 0.14);
          tl.set("#fx-streak", {{ opacity: 0 }}, t + 0.15);
          break; }}
        case "flash": case "drop": case "act": {{
          const peak = j.kind === "flash" ? 0.95 : 1;
          ft("#fx-flash", {{ opacity: 0 }}, {{ opacity: peak, duration: 0.12, ease: "power2.in" }}, t - 0.12);
          tl.to("#fx-flash", {{ opacity: 0, duration: j.kind === "act" ? 0.7 : 0.45, ease: "power2.out" }}, t);
          ft(n, {{ scale: j.kind === "flash" ? 1.08 : 1.14 }}, {{ scale: 1, duration: 0.6, ease: "expo.out" }}, t);
          if (j.kind !== "flash") {{
            ft("#fx-glitch", {{ opacity: 0.9 }}, {{ opacity: 0, duration: 0.25, ease: "steps(4)" }}, t);
          }}
          break; }}
        case "glitch": {{
          ft("#fx-glitch", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.06, ease: "steps(2)" }}, t - 0.1);
          tl.to("#fx-glitch", {{ opacity: 0, duration: 0.22, ease: "steps(5)" }}, t + 0.02);
          ft("#fx-glitch .bar", {{ x: 0 }}, {{ x: (k) => (k % 2 ? 1 : -1) * (40 + k * 9), duration: 0.3, ease: "steps(6)" }}, t - 0.1);
          ft(o, {{ x: 0 }}, {{ x: 18, duration: 0.1, ease: "steps(3)" }}, t - 0.1);
          ft(n, {{ x: -22, filter: "contrast(1.6) saturate(1.8)" }}, {{ x: 0, filter: "contrast(1) saturate(1)", duration: 0.24, ease: "steps(4)" }}, t);
          break; }}
        case "leak": {{
          ft("#fx-leak", {{ opacity: 0, scale: 1.2 }}, {{ opacity: 0.95, scale: 1, duration: 0.35, ease: "power2.in" }}, t - 0.35);
          tl.to("#fx-leak", {{ opacity: 0, duration: 0.8, ease: "power2.out" }}, t);
          tl.to(o, {{ scale: 1.12, duration: 0.35, ease: "power2.in" }}, t - 0.35);  // no filter on the outgoing host: Chrome drops a black frame when it switches on over video
          ft(n, {{ scale: 1.1, filter: "blur(10px) brightness(1.5)" }}, {{ scale: 1, filter: "blur(0px) brightness(1)", duration: 0.7, ease: "power3.out" }}, t);
          break; }}
        case "dip": {{
          ft("#fx-black", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3, ease: "sine.in" }}, t - 0.3);
          tl.to("#fx-black", {{ opacity: 0, duration: 0.45, ease: "sine.out" }}, t);
          break; }}
        case "zoom": {{
          tl.to(o, {{ scale: 1.45, filter: "blur(14px)", duration: 0.2, ease: "power3.in" }}, t - 0.2);
          ft(n, {{ scale: 0.82, filter: "blur(14px)" }}, {{ scale: 1, filter: "blur(0px)", duration: 0.3, ease: "power3.out" }}, t);
          break; }}
        case "punch": {{
          ft(n, {{ scale: 1.07 }}, {{ scale: 1, duration: 0.35, ease: "expo.out" }}, t);
          break; }}
        case "shatter": {{
          shatter(j, t, o, n);
          break; }}
        default: break; // "cut" and "match": the scenes themselves line up
      }}
    }});

    // captions: one cue at a time, each word lighting as it is spoken
    const caps = document.getElementById("caps");
    CUES.forEach((c, i) => {{
      const el = document.createElement("div"); el.className = "cap"; el.id = "cap-" + i;
      c.w.forEach(([w, ws], k) => {{ const sp = document.createElement("span"); sp.textContent = (k ? "\\u00a0" : "") + w; el.appendChild(sp);
        tl.fromTo(sp, {{ color: "rgba(242,237,228,0.55)" }}, {{ color: "#F2EDE4", duration: 0.08, ease: "none" }}, Math.max(c.s, ws - 0.02)); }});
      caps.appendChild(el);
      tl.fromTo(el, {{ opacity: 0, y: 10 }}, {{ opacity: 1, y: 0, duration: 0.14, ease: "power2.out" }}, c.s);
      tl.to(el, {{ opacity: 0, duration: 0.07, ease: "none" }}, c.e - 0.07);  // out before the next cue starts (no overlap)
    }});

    window.__timelines["main"] = tl;
  </script>
</body>
</html>
"""
    shatter = (SHATTER_JS.replace("__IMPACT__", str(rc["shatter_impact"]))
               .replace("__PX__", str(px)).replace("__PY__", str(py))
               .replace("__SEED__", str(rc["shatter_seed"])))
    return page.replace("/*SHATTER*/", shatter)


def build(p: Project) -> dict[str, Any]:
    tl = p.timeline()
    scenes, total = tl["scenes"], tl["duration"]
    js = joins(p, scenes)
    write_json(p.emit / "transitions.json", {"joins": js, "sfx": p.cfg["sfx"]})
    words = read_json(p.spine_dir / "words.json")
    cues = cue_words(tl["captions"], words)
    (p.emit / "index.html").write_text(html(p, scenes, total, js, cues), encoding="utf-8")
    shatters = [j["out"] for j in js if j["kind"] == "shatter"]
    print(f"root: {len(scenes)} scenes, {len(js)} joins, {len(cues)} caption cues, {total}s"
          + (f"; run `film freeze` for {', '.join(shatters)}" if shatters else ""))
    return {"joins": js}
