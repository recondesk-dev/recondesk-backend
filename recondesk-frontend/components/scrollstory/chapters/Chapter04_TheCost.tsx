"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { StickyScene } from "@/components/scrollstory/shared/StickyScene";
import dynamic from "next/dynamic";

// D3 chart is client-only
const HoursBarChart = dynamic(
  () => import("@/components/scrollstory/chapters/HoursBarChart"),
  { ssr: false, loading: () => <div className="h-48 w-full animate-pulse rounded-lg bg-[#1a1a1a]" /> }
);

interface Props {
  scrollProgress: number;
}

const CLIENT_BUCKETS = [
  { label: "1–5 clients", hoursPerClient: 3.5 },
  { label: "6–15 clients", hoursPerClient: 3.5 },
  { label: "16–30 clients", hoursPerClient: 4 },
  { label: "31–50 clients", hoursPerClient: 4 },
  { label: "51+ clients", hoursPerClient: 4.5 },
];

/**
 * Chapter 04 — The Cost
 * D3 bar chart + interactive client slider with a live red counter.
 */
export function Chapter04_TheCost({ scrollProgress }: Props) {
  const [clients, setClients] = useState(20);
  const hoursPerClient = 3.5;
  const totalHours = Math.round(clients * hoursPerClient);
  const totalDays = (totalHours / 8).toFixed(1);

  const showChart = scrollProgress > 0.1;
  const showSlider = scrollProgress > 0.3;
  const showCounter = scrollProgress > 0.5;

  return (
    <StickyScene background="#0a0a0a">
      <div className="relative h-full w-full flex flex-col justify-center px-6 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl py-10">
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-[#444]">
            Chapter 04 — The Cost
          </p>
          <h2 className="mt-3 text-2xl font-semibold text-[#f0f0f0] sm:text-3xl">
            What this is costing your firm.
          </h2>

          {/* D3 Chart */}
          <motion.div
            className="mt-8"
            animate={{ opacity: showChart ? 1 : 0, y: showChart ? 0 : 20 }}
            transition={{ duration: 0.8 }}
          >
            <HoursBarChart clients={clients} />
          </motion.div>

          {/* Interactive slider */}
          <motion.div
            className="mt-8"
            animate={{ opacity: showSlider ? 1 : 0, y: showSlider ? 0 : 16 }}
            transition={{ duration: 0.8 }}
          >
            <label className="block font-mono text-xs uppercase tracking-widest text-[#555]">
              Your client count: {clients}
            </label>
            <input
              type="range"
              min={1}
              max={100}
              value={clients}
              onChange={(e) => setClients(Number(e.target.value))}
              className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-[#222] accent-red-500"
            />
            <div className="mt-1 flex justify-between font-mono text-xs text-[#555]">
              <span>1</span>
              <span>50</span>
              <span>100</span>
            </div>
          </motion.div>

          {/* Running total */}
          <motion.div
            className="mt-8"
            animate={{ opacity: showCounter ? 1 : 0 }}
            transition={{ duration: 0.8 }}
          >
            <div className="rounded-2xl border border-red-900 bg-red-950/20 p-6">
              <p className="font-mono text-xs uppercase tracking-widest text-red-700">
                Hours lost per month
              </p>
              <motion.p
                key={totalHours}
                className="mt-2 font-mono text-6xl font-bold text-red-500 tabular-nums"
                initial={{ scale: 0.9, opacity: 0.5 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.3 }}
              >
                {totalHours}h
              </motion.p>
              <p className="mt-2 font-mono text-sm text-[#888]">
                That&apos;s{" "}
                <span className="text-red-400 font-semibold">{totalDays} working days</span>{" "}
                lost to spreadsheets every single month.
              </p>
              <div className="mt-4 grid grid-cols-3 gap-4 border-t border-red-900/30 pt-4">
                <div>
                  <p className="font-mono text-xs text-[#555]">Per year</p>
                  <p className="font-mono text-xl font-bold text-red-400">
                    {(totalHours * 12).toLocaleString()}h
                  </p>
                </div>
                <div>
                  <p className="font-mono text-xs text-[#555]">At ₹1,500/hr</p>
                  <p className="font-mono text-xl font-bold text-red-400">
                    ₹{((totalHours * 12 * 1500) / 100000).toFixed(1)}L
                  </p>
                </div>
                <div>
                  <p className="font-mono text-xs text-[#555]">Penalty risk</p>
                  <p className="font-mono text-xl font-bold text-red-400">High</p>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </StickyScene>
  );
}
