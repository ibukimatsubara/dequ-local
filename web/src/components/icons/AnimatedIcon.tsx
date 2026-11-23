import {useEffect, useRef, type ForwardRefExoticComponent, type RefAttributes} from 'react';

type Handle = {startAnimation: () => void; stopAnimation: () => void};
type AnimatedComponent = ForwardRefExoticComponent<{size?: number; className?: string} & RefAttributes<Handle>>;
type Props = {icon: AnimatedComponent; size?: number | string};

/**
 * Plays an animated icon (components/icons/animated) with the control around it.
 * If it is inside a button or link, that control is the target; otherwise a data-animate-icons frame is.
 * It plays when the pointer enters or focus lands. With neither, the icon itself is the target.
 */
export function AnimatedIcon({icon: Component, size = '1em'}: Props) {
  const host = useRef<HTMLSpanElement>(null);
  const handle = useRef<Handle>(null);

  useEffect(() => {
    const element = host.current;
    if (!element || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const target = element.closest('button, a, [role="button"], [role="radio"], label, [data-animate-icons]') ?? element;
    const start = () => { void handle.current?.startAnimation(); };
    const stop = () => { void handle.current?.stopAnimation(); };
    target.addEventListener('pointerenter', start);
    target.addEventListener('pointerleave', stop);
    target.addEventListener('focusin', start);
    target.addEventListener('focusout', stop);
    return () => {
      target.removeEventListener('pointerenter', start);
      target.removeEventListener('pointerleave', stop);
      target.removeEventListener('focusin', start);
      target.removeEventListener('focusout', stop);
    };
  }, []);

  // Imported icons pass size through to width / height, so em is a valid size.
  return (
    <span ref={host} className="animated-icon" aria-hidden="true">
      <Component ref={handle} size={size as number} />
    </span>
  );
}
