'use client';

import { motion } from 'framer-motion';

export default function TurnSection() {
  return (
    <section className="relative w-full h-[200vh] flex flex-col items-center justify-between py-[40vh] text-center px-6">
      {/* First point of realization */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
      >
        <h2 className="font-[var(--font-general-sans)] text-3xl md:text-5xl text-[#F5F5F3]">
          Or, upload two files.
        </h2>
      </motion.div>

      {/* The product reveal further down */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.6, ease: 'easeOut', delay: 0.2 }}
        className="mt-auto"
      >
        <h1 className="font-[var(--font-general-sans)] text-5xl md:text-7xl font-bold text-[#34D399] tracking-wide">
          ReconDesk
        </h1>
        <p className="mt-6 text-xl text-[#6B6B70] tracking-wide leading-relaxed">
          Reconciled in minutes, not hours.
        </p>
      </motion.div>
    </section>
  );
}
