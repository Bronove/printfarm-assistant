import { useEffect, useRef } from "react";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export default function useSmoothWheel<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let target = element.scrollTop;
    let frame = 0;

    const step = () => {
      const distance = target - element.scrollTop;
      if (Math.abs(distance) < 0.5) {
        element.scrollTop = target;
        frame = 0;
        return;
      }
      element.scrollTop += distance * 0.26;
      frame = window.requestAnimationFrame(step);
    };

    const onWheel = (event: WheelEvent) => {
      if (element.scrollHeight <= element.clientHeight + 1) return;

      const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE
        ? 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
          ? element.clientHeight
          : 1;
      const delta = event.deltaY * unit;
      const max = element.scrollHeight - element.clientHeight;
      if ((element.scrollTop <= 0 && delta < 0)
          || (element.scrollTop >= max - 1 && delta > 0)) {
        return;
      }

      event.preventDefault();
      if (reducedMotion.matches) {
        element.scrollTop = clamp(target + delta, 0, max);
        return;
      }

      if (!frame) target = element.scrollTop;
      target = clamp(target + delta, 0, max);
      if (!frame) frame = window.requestAnimationFrame(step);
    };

    element.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      element.removeEventListener("wheel", onWheel);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return ref;
}
