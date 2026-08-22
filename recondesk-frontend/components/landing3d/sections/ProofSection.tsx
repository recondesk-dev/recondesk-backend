'use client';

import { motion } from 'framer-motion';

export default function ProofSection() {
  return (
    <section className="relative w-full py-32 px-6 sm:px-8 lg:px-12 flex items-center justify-center text-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className="max-w-3xl flex flex-col gap-6"
      >
        <p className="font-[var(--font-general-sans)] text-2xl md:text-3xl text-[#F5F5F3]">
          Tens of thousands of CA firms in India do this by hand every month.
        </p>
        <p className="font-[var(--font-general-sans)] text-2xl md:text-3xl text-[#6B6B70]">
          ReconDesk exists to make GST reconciliation something a firm configures once — not re-does by hand every period.
        </p>
      </motion.div>
    </section>
  );
}
