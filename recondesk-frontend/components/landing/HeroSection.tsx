import Link from "next/link";
import { ArrowDown, ArrowUpRight, Check, ChevronRight } from "lucide-react";
import { HeroProductPanel } from "./HeroProductPanel";
import { InvoiceMatchVisual } from "./InvoiceMatchVisual";

export function HeroSection() {
  return (
    <section className="studio-hero">
      <div className="studio-hero-top">
        <div className="studio-hero-copy">
          <a href="#modules" className="studio-announcement"><span>What&apos;s New</span><span>GSTR-2B, 1, 3B &amp; IMS Support v2.4</span><ChevronRight size={13} /></a>
          <h1>Still Matching<br />Invoices By <span>Hand</span><br />in 2026?</h1>
          <p className="studio-hero-description">Upload your Tally, Busy, or Excel registers with GST portal files. Get audit-grade 5-level matching, Rule 37 reversal alerts, and decision-ready workpapers in under 60 seconds.</p>
          <div className="studio-hero-actions">
            <Link href="/auth/signup" className="studio-primary">Start 60-Day Free Trial (2 GSTINs)<ArrowUpRight size={17} /></Link>
            <a href="#modules" className="studio-secondary">Explore GSTR Modules<ArrowDown size={15} /></a>
          </div>
          <div className="studio-hero-trust"><span><Check size={13} />No credit card required</span><span><Check size={13} />Works with Tally, Busy &amp; Excel</span><span><Check size={13} />2 GSTINs free for 60 days (2 monthly cycles)</span></div>
        </div>
        <InvoiceMatchVisual />
      </div>
      <div className="studio-product-stage">
        <div className="studio-product-caption"><span><span className="studio-status-dot" /> YOUR RECONCILIATION, IN FOCUS</span><span>THE RECONDESK WORKSPACE <ArrowDown size={12} /></span></div>
        <div className="hero-animate-panel"><HeroProductPanel /></div>
        <div className="studio-product-footer"><span>One desk. Every detail.</span><a href="/depth">Explore ReconDepth <ArrowUpRight size={14} /></a></div>
      </div>
    </section>
  );
}
