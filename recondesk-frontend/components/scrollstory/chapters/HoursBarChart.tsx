"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";

interface Props {
  clients: number;
}

/**
 * HoursBarChart — D3 horizontal bar chart showing hours lost per month
 * by client bucket, with the current client count highlighted.
 */
export default function HoursBarChart({ clients }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth || 600;
    const height = 160;
    const margin = { top: 16, right: 80, bottom: 24, left: 100 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    svg.selectAll("*").remove();
    svg.attr("width", width).attr("height", height);

    const data = [
      { label: "5 clients", hours: 18 },
      { label: "10 clients", hours: 35 },
      { label: "20 clients", hours: 70 },
      { label: "40 clients", hours: 140 },
      { label: "100 clients", hours: 350 },
    ];

    const highlight = Math.min(Math.max(0, Math.round((clients / 100) * (data.length - 1))), data.length - 1);

    const x = d3.scaleLinear().domain([0, 350]).range([0, innerWidth]);
    const y = d3.scaleBand().domain(data.map((d) => d.label)).range([0, innerHeight]).padding(0.3);

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    // Bars
    g.selectAll("rect")
      .data(data)
      .join("rect")
      .attr("y", (d) => y(d.label)!)
      .attr("height", y.bandwidth())
      .attr("x", 0)
      .attr("width", 0)
      .attr("rx", 4)
      .attr("fill", (_, i) => (i === highlight ? "#ef4444" : "#1f1f1f"))
      .transition()
      .duration(800)
      .ease(d3.easeCubicOut)
      .attr("width", (d) => x(d.hours));

    // Labels
    g.selectAll(".bar-label")
      .data(data)
      .join("text")
      .attr("class", "bar-label")
      .attr("y", (d) => y(d.label)! + y.bandwidth() / 2 + 4)
      .attr("x", (d) => x(d.hours) + 8)
      .attr("fill", (_, i) => (i === highlight ? "#ef4444" : "#555"))
      .attr("font-family", "var(--font-jetbrains-mono, monospace)")
      .attr("font-size", 11)
      .text((d) => `${d.hours}h`);

    // Y axis
    g.append("g")
      .call(d3.axisLeft(y).tickSize(0))
      .call((ax) => ax.select(".domain").remove())
      .selectAll("text")
      .attr("fill", "#555")
      .attr("font-family", "var(--font-jetbrains-mono, monospace)")
      .attr("font-size", 11);

    // X gridlines
    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(
        d3
          .axisBottom(x)
          .ticks(5)
          .tickFormat((d) => `${d}h`)
          .tickSize(-innerHeight)
      )
      .call((ax) => ax.select(".domain").remove())
      .selectAll("line")
      .attr("stroke", "#1a1a1a");

    g.select(".tick:first-child line").remove();
  }, [clients]);

  return (
    <div className="w-full">
      <p className="mb-2 font-mono text-xs uppercase tracking-widest text-[#444]">
        Hours lost / month by firm size
      </p>
      <svg ref={svgRef} className="w-full" style={{ height: 160 }} />
    </div>
  );
}
