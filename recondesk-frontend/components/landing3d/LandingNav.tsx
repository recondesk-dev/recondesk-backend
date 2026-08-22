'use client';

import { motion, useScroll, useTransform } from 'framer-motion';
import Link from 'next/link';

export default function LandingNav() {
  const { scrollY } = useScroll();
  
  const backgroundColor = useTransform(
    scrollY,
    [0, 50],
    ['rgba(10, 10, 11, 0)', 'rgba(10, 10, 11, 0.8)']
  );
  
  const borderColor = useTransform(
    scrollY,
    [0, 50],
    ['rgba(58, 58, 64, 0)', 'rgba(58, 58, 64, 0.5)']
  );

  return (
    <motion.nav
      style={{ backgroundColor, borderColor }}
      className="fixed top-0 left-0 right-0 z-50 border-b backdrop-blur-md"
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/" className="text-lg font-bold text-[#F5F5F3]">
          ReconDesk
        </Link>
        
        <div className="flex items-center gap-6">
          <div className="hidden md:flex items-center gap-6">
            <Link href="#how-it-works" className="text-sm text-[#F5F5F3] hover:text-[#34D399] transition-colors">
              How it works
            </Link>
            <Link href="#pricing" className="text-sm text-[#F5F5F3] hover:text-[#34D399] transition-colors">
              Pricing
            </Link>
            <Link href="/auth/login" className="text-sm text-[#F5F5F3] hover:text-[#34D399] transition-colors">
              Log in
            </Link>
          </div>
          
          <Link
            href="/auth/signup"
            className="bg-[#F5F5F3] text-[#0A0A0B] px-4 py-2 rounded-full text-sm font-semibold hover:bg-[#F5F5F3]/90 transition-colors"
          >
            Start Free
          </Link>
        </div>
      </div>
    </motion.nav>
  );
}
