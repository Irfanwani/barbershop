import { useEffect, useRef, useState, type ReactNode } from 'react';

interface RevealProps {
  children: ReactNode;
  className?: string;
  /** Stagger, in milliseconds, for siblings revealed together. */
  delay?: number;
  id?: string;
}

/**
 * A small scroll-reveal wrapper.
 *
 * The site has a lot of illustration work that is only worth animating once it
 * is actually on screen. An IntersectionObserver per block is cheap, and the
 * one-way flag means nothing re-hides when a visitor scrolls back up.
 *
 * When IntersectionObserver is unavailable — older browsers, and jsdom — the
 * content starts visible rather than waiting forever for an event that will
 * never fire. Motion is a bonus, not a prerequisite for reading the page.
 */
export function Reveal({ children, className = '', delay = 0, id }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(() => typeof IntersectionObserver === 'undefined');

  useEffect(() => {
    if (shown || !ref.current) return;

    const node = ref.current;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.18, rootMargin: '0px 0px -6% 0px' },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [shown]);

  return (
    <div
      id={id}
      ref={ref}
      className={`reveal${shown ? ' is-visible' : ''}${className ? ` ${className}` : ''}`}
      style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}
