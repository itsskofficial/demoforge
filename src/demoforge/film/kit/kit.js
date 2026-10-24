/* film kit: shared helpers for scene builders. Read-only. Deterministic only. */
(function () {
  if (window.Kit) return;

  // Seeded PRNG (mulberry32). Same seed → same sequence on every render.
  function rng(seed) {
    let s = seed >>> 0;
    return function () {
      s = (s + 0x6d2b79f5) >>> 0;
      let t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // A stable 7-character git-style hash for any string.
  function hash(text) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    const r = rng(h);
    const hex = "0123456789abcdef";
    let out = "";
    for (let i = 0; i < 7; i++) out += hex[Math.floor(r() * 16)];
    return out;
  }

  // Draw an SVG path on: prepares dasharray/offset and returns its length.
  function prepStroke(el) {
    const len = el.getTotalLength();
    el.style.strokeDasharray = len + " " + len;
    el.style.strokeDashoffset = len;
    return len;
  }

  // Type text into an element on a GSAP timeline (seek-safe: derived from tween progress).
  function type(tl, el, text, at, duration, opts) {
    const o = Object.assign({ ease: "none" }, opts || {});
    const p = { n: 0 };
    tl.to(p, {
      n: text.length,
      duration: duration,
      ease: o.ease,
      onUpdate: function () {
        el.textContent = text.slice(0, Math.round(p.n));
      },
    }, at);
    return tl;
  }

  // Count a number up on a timeline. fmt(value) returns the display string.
  function count(tl, el, from, to, at, duration, fmt, ease) {
    const p = { v: from };
    tl.to(p, {
      v: to,
      duration: duration,
      ease: ease || "power2.out",
      onUpdate: function () {
        el.textContent = fmt ? fmt(p.v) : String(Math.round(p.v));
      },
    }, at);
    return tl;
  }

  // Blink something with stepped opacity for a finite window.
  function blink(tl, target, at, until, period) {
    const half = (period || 0.5) / 2;
    const n = Math.max(0, Math.floor((until - at) / half) - 1);
    tl.fromTo(target, { opacity: 1 }, { opacity: 0, duration: half, ease: "steps(1)", repeat: n, yoyo: true }, at);
    return tl;
  }

  window.Kit = { rng: rng, hash: hash, prepStroke: prepStroke, type: type, count: count, blink: blink };
})();
