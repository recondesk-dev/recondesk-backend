'use client';

import { motion } from 'framer-motion';

const beats = [
  "Every month: 3–6 hours per client spent manually cross-checking GSTR-2B against the Purchase Register line by line.",
  "Every mismatch is a silent risk: claim ineligible ITC and you're exposed under Rule 37 and Section 17(5); miss eligible ITC and the client overpays tax.",
  "Vendors who haven't filed their GSTR-1 don't tell you — you find out during a scramble, or worse, during a notice.",
  "Multiply by every GSTIN, every client, every month, and it doesn't scale. It just gets more hours."
];

export default function PainSection() {
  return (
    <section className="relative w-full bg-transparent">
      <div className="w-full flex flex-col h-[400vh]">
        {beats.map((beat, index) => (
          <div key={index} className="h-screen w-full flex items-center justify-center px-6">
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: false, amount: 0.3 }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
              className="font-[var(--font-general-sans)] text-2xl md:text-4xl font-medium text-[#F5F5F3] max-w-3xl mx-auto text-center"
            >
              {beat}
            </motion.p>
          </div>
        ))}
      </div>
    </section>
  );
}
