'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { LANDING } from '@/lib/landing-tokens';

export default function CloseSection() {
  return (
    <section className="min-h-[60vh] flex items-center justify-center relative z-10 py-20 px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className="max-w-3xl mx-auto text-center"
      >
        <h2 className="font-[var(--font-general-sans)] text-3xl md:text-4xl text-[#F5F5F3] font-semibold mb-10">
          Your next reconciliation, resolved in minutes.
        </h2>
        
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-6">
          <Link
            href="/auth/signup"
            className="w-full sm:w-auto bg-[#34D399] text-[#0A0A0B] px-8 py-4 rounded-full font-semibold text-lg hover:bg-[#34D399]/90 transition-colors"
          >
            Start Your First Run
          </Link>
          <Link
            href="mailto:contact@recondesk.in"
            className="w-full sm:w-auto border border-[#F5F5F3] text-[#F5F5F3] px-8 py-4 rounded-full font-semibold text-lg hover:bg-[#F5F5F3]/10 transition-colors"
          >
            Book a Walkthrough
          </Link>
        </div>
        
        <p className="text-sm text-[#6B6B70]">
          First 2 reconciliations free. No credit card required.
        </p>
      </motion.div>
    </section>
  );
}
