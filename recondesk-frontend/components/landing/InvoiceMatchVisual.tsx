"use client";

import { useState } from "react";
import { useAutoplay } from "../motion/useAutoplay";
import { ArrowDown, ArrowRight, Check, FileSpreadsheet, FileText, RotateCcw, Sparkles } from "lucide-react";

/** A deliberately small, labelled example; it never uploads or processes client data. */
export function InvoiceMatchVisual() {
  const [paused, setPaused] = useState(false);
  const { ref, step, setStep, running, reduced } = useAutoplay(2, paused, 4400);
  const matched = step === 1;
  return (
    <div ref={ref} data-running={running} className={`studio-match studio-match-auto ${matched ? "is-matched" : ""}`} aria-label="Illustrative invoice matching demo">
      <div className="studio-match-grid" aria-hidden="true" />
      <div className="studio-match-orbit studio-match-orbit-one" aria-hidden="true" />
      <div className="studio-match-orbit studio-match-orbit-two" aria-hidden="true" />
      <div className="studio-match-label"><span /> THE DETAILS, CONNECTED</div>
      <div className="studio-document studio-document-books">
        <div className="studio-document-heading"><span className="studio-file-icon"><FileSpreadsheet size={19} /></span><div><strong>Purchase register</strong><small>YOUR BOOKS</small></div><span className="studio-file-tag">XLSX</span></div>
        <div className="studio-document-rule" />
        <span className="studio-field-label">Invoice number</span>
        <strong className="studio-invoice-number">INV-941</strong>
        <div className="studio-document-total"><span>Invoice value</span><strong>₹1,42,000</strong></div>
      </div>
      <div className="studio-match-bridge" aria-hidden="true"><span /><div><Sparkles size={25} strokeWidth={1.5} /></div><span /></div>
      <div className="studio-document studio-document-portal">
        <div className="studio-document-heading"><span className="studio-file-icon"><FileText size={19} /></span><div><strong>GSTR-2B</strong><small>GST PORTAL</small></div><span className="studio-file-tag">JSON</span></div>
        <div className="studio-document-rule" />
        <span className="studio-field-label">Invoice number</span>
        <strong className="studio-invoice-number">INV-0941</strong>
        <div className="studio-document-total"><span>Invoice value</span><strong>₹1,42,000</strong></div>
      </div>
      <div className="studio-match-result" aria-live={running ? "off" : "polite"} aria-atomic="true">
        <span className="studio-result-icon">{matched ? <Check size={17} /> : <ArrowDown size={17} />}</span>
        <div><strong>{matched ? "L2 normalized match" : "One invoice. Two formats."}</strong><small>{matched ? "Prefix normalised · ₹0 difference" : "See how the details come together."}</small></div>
        {matched && <span className="studio-result-tag">MATCHED</span>}
      </div>
      {!reduced && <button className="studio-autoplay-toggle" type="button" aria-label={paused ? "Play animation" : "Pause animation"} aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? "▶ Play animation" : "Ⅱ Pause animation"}</button>}
      <div className="studio-match-controls"><span>ILLUSTRATIVE EXAMPLE</span><button type="button" onClick={() => { setPaused(true); setStep(matched ? 0 : 1); }}>{matched ? "Reset sample" : "Run sample match"}{matched ? <RotateCcw size={13} /> : <ArrowRight size={14} />}</button></div>
    </div>
  );
}
