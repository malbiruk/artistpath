import { useEffect, useState } from "react";

// Whether the user is currently interacting by touch.
//
// We deliberately avoid the usual static capability sniff
// (`"ontouchstart" in window || navigator.maxTouchPoints > 0`): privacy
// hardening such as Firefox's resistFingerprinting makes the touch API *appear
// present* on plain desktops, which wrongly forced the graph into its touch UX
// (a single click only highlighted connections instead of opening the artist
// card, and hover was disabled). A real touch event cannot be synthesized by
// those modes, so we assume mouse/desktop until an actual touch happens, then
// flip — and flip back on a real mouse press, for hybrid laptops.

let touchActive = false;
const subscribers = new Set();

function set(active) {
  if (touchActive === active) return;
  touchActive = active;
  subscribers.forEach((fn) => fn(touchActive));
}

if (typeof window !== "undefined") {
  const opts = { capture: true, passive: true };
  window.addEventListener("touchstart", () => set(true), opts);
  // Explicit types only — an unknown/blanked pointerType (some hardened modes)
  // must not be mistaken for touch; it leaves the current value untouched.
  window.addEventListener(
    "pointerdown",
    (e) => {
      if (e.pointerType === "mouse") set(false);
      else if (e.pointerType === "touch" || e.pointerType === "pen") set(true);
    },
    opts,
  );
}

export function isTouchInput() {
  return touchActive;
}

export function useIsTouchInput() {
  const [active, setActive] = useState(touchActive);
  useEffect(() => {
    setActive(touchActive);
    subscribers.add(setActive);
    return () => subscribers.delete(setActive);
  }, []);
  return active;
}
