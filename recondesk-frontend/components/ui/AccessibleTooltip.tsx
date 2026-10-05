"use client";

import React, { useState, useRef, useId, useEffect } from "react";

interface AccessibleTooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  side?: "top" | "bottom" | "left" | "right";
  shortcut?: string;
  className?: string;
}

export function AccessibleTooltip({
  content,
  children,
  side = "top",
  shortcut,
  className = "",
}: AccessibleTooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId();
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const showTooltip = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
    }, 120);
  };

  const hideTooltip = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setIsVisible(false);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isVisible) {
        setIsVisible(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [isVisible]);

  const positionClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  // Clone child with accessibility props & event handlers
  const trigger = React.cloneElement(children, {
    "aria-describedby": isVisible ? tooltipId : undefined,
    onPointerEnter: (e: React.PointerEvent) => {
      children.props.onPointerEnter?.(e);
      showTooltip();
    },
    onPointerLeave: (e: React.PointerEvent) => {
      children.props.onPointerLeave?.(e);
      hideTooltip();
    },
    onFocus: (e: React.FocusEvent) => {
      children.props.onFocus?.(e);
      showTooltip();
    },
    onBlur: (e: React.FocusEvent) => {
      children.props.onBlur?.(e);
      hideTooltip();
    },
  });

  return (
    <span className={`relative inline-flex items-center ${className}`}>
      {trigger}
      {isVisible && (
        <span
          id={tooltipId}
          role="tooltip"
          aria-hidden={!isVisible}
          className={`pointer-events-none absolute z-[120] whitespace-nowrap rounded-md bg-[#181322] px-2 py-1 text-[11px] font-medium text-white shadow-md transition-opacity duration-150 motion-reduce:transition-none ${
            positionClasses[side]
          }`}
        >
          <span className="flex items-center gap-1.5">
            <span>{content}</span>
            {shortcut && (
              <kbd className="rounded bg-white/20 px-1 py-0.2 font-mono text-[9px] text-purple-200">
                {shortcut}
              </kbd>
            )}
          </span>
        </span>
      )}
    </span>
  );
}
