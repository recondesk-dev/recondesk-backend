import React from "react";

interface LogoProps {
  className?: string;
  width?: number | string; // Kept for backward compatibility
  height?: number | string; // Maps to font size
}

export function Logo({ className = "", height }: LogoProps) {
  // Approximate the SVG's visual size based on the height attribute (font size is ~80% of height)
  // If height is a string like "1.2em", it passes through directly.
  let fontSize: string | undefined = undefined;
  if (height) {
    if (typeof height === "number") {
      fontSize = `${Math.round(height * 0.8)}px`;
    } else {
      fontSize = height;
    }
  }

  return (
    <span className={`whitespace-nowrap ${className}`} style={{ fontSize }}>
      <span style={{ fontWeight: 700, fontSize: "inherit" }}>ReconDesk</span>
      <span
        style={{
          display: "inline-block",
          width: "0.35em",
          height: "0.35em",
          borderRadius: "50%",
          backgroundColor: "#7B5CFA",
          marginLeft: "1px",
          marginBottom: "1px",
          verticalAlign: "baseline",
        }}
      />
    </span>
  );
}
