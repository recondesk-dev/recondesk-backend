'use client';

import { motion } from 'framer-motion';

const solutions = [
  {
    title: 'Reconciliation, not just matching.',
    description: "Five-level matching — exact through fuzzy — resolves the obvious cases automatically so you only look at what's actually ambiguous."
  },
  {
    title: 'Rule 37 / Section 17(5) reasoning, not a spreadsheet.',
    description: "For every uncertain line, a claim/hold/dispute recommendation with the compliance rule behind it. You see why, not just what."
  },
  {
    title: 'Vendor risk, before it becomes your problem.',
    description: "Suppliers who stop filing get flagged and risk-scored automatically. One-click follow-up built in — not a separate manual chase."
  },
  {
    title: 'Filing, not just reporting.',
    description: "GSTR-1 and GSTR-3B filed directly with the same decision layer behind Offset and EVC. The reconciliation connects all the way to the return."
  }
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.15
    }
  }
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { 
    opacity: 1, 
    y: 0, 
    transition: { duration: 0.6, ease: [0, 0, 0.2, 1] as const } 
  }
};

export default function SolutionSection() {
  return (
    <section className="relative w-full py-32 md:py-48 px-6 sm:px-8 lg:px-12">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className="mb-12"
        >
          <h2 className="text-sm uppercase tracking-[0.2em] text-[#34D399] mb-4">
            What changes
          </h2>
        </motion.div>

        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-2 gap-6"
        >
          {solutions.map((solution, index) => (
            <motion.div
              key={index}
              variants={itemVariants}
              className="bg-[#2A2A2E] rounded-2xl p-8 border border-[#3A3A40] flex flex-col"
            >
              <div className="flex items-start gap-4 mb-4">
                <div className="w-2.5 h-2.5 rounded-full bg-[#34D399] shrink-0 mt-2" aria-hidden="true" />
                <h3 className="font-[var(--font-general-sans)] text-xl font-semibold text-[#F5F5F3]">
                  {solution.title}
                </h3>
              </div>
              <p className="text-base leading-relaxed text-[#6B6B70] pl-6.5">
                {solution.description}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
