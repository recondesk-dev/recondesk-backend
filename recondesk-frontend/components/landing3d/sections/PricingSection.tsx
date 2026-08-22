'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { LANDING } from '@/lib/landing-tokens';

const pricingPlans = [
  {
    name: 'Monthly',
    price: '999',
    period: '/mo',
    capacity: 'Up to 25 GSTINs',
    badge: 'Pay-as-you-go',
    isPopular: false,
    isCustom: false,
    ctaText: 'Start Free',
    ctaLink: '/auth/signup',
  },
  {
    name: 'Starter',
    price: '5,999',
    period: '/yr',
    capacity: 'Up to 50 GSTINs',
    badge: 'Save 50%',
    isPopular: false,
    isCustom: false,
    ctaText: 'Start Free',
    ctaLink: '/auth/signup',
  },
  {
    name: 'Growth',
    price: '9,999',
    period: '/yr',
    capacity: 'Up to 100 GSTINs',
    badge: 'Most Popular',
    isPopular: true,
    isCustom: false,
    ctaText: 'Start Free',
    ctaLink: '/auth/signup',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    capacity: '100+ GSTINs',
    badge: "Let's Talk",
    isPopular: false,
    isCustom: true,
    ctaText: 'Contact Us',
    ctaLink: 'mailto:contact@recondesk.in',
  },
];

const features = [
  'Smart 5-Level Matching',
  'Decision Layer (Claim/Hold/Dispute)',
  'Rule 37 & Section 17(5) Tracking',
  'Vendor Risk Scorecard',
  'GSTR-1 & GSTR-3B Filing',
  'Multi-Period Audit Workpapers',
];

const CheckIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M16.6668 5L7.50016 14.1667L3.3335 10" stroke="#34D399" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export default function PricingSection() {
  return (
    <section id="pricing" className="bg-[#0A0A0B] py-32 md:py-40 relative z-20">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="font-[var(--font-general-sans)] text-3xl md:text-4xl text-[#F5F5F3] font-semibold mb-4">
            Simple, honest pricing
          </h2>
          <p className="text-lg text-[#6B6B70]">
            Full product in every plan. Difference is GSTIN capacity.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {pricingPlans.map((plan, index) => (
            <div
              key={index}
              className={`bg-[#2A2A2E] rounded-2xl p-8 border flex flex-col ${
                plan.isPopular
                  ? 'border-[#34D399] border-2 shadow-[0_0_15px_rgba(52,211,153,0.1)]'
                  : 'border-[#3A3A40]'
              }`}
            >
              <div className="mb-6 flex justify-between items-start">
                <h3 className="text-lg font-semibold text-[#F5F5F3]">{plan.name}</h3>
                <span className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${
                  plan.isPopular ? 'bg-[#34D399]/10 text-[#34D399]' : 'bg-[#3A3A40] text-[#F5F5F3]'
                }`}>
                  {plan.badge}
                </span>
              </div>
              
              <div className="mb-4">
                <span className="text-4xl font-bold text-[#F5F5F3] font-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {plan.isCustom ? '' : '₹'}{plan.price}
                </span>
                <span className="text-sm text-[#6B6B70]">{plan.period}</span>
              </div>
              
              <p className="text-base text-[#F5F5F3] mb-8">{plan.capacity}</p>
              
              <ul className="space-y-4 mb-8 flex-1">
                {features.map((feature, fIndex) => (
                  <li key={fIndex} className="flex items-start gap-3">
                    <div className="mt-0.5"><CheckIcon /></div>
                    <span className="text-sm text-[#F5F5F3]">{feature}</span>
                  </li>
                ))}
              </ul>
              
              <Link
                href={plan.ctaLink}
                className={`block text-center w-full py-3 rounded-full font-semibold transition-colors ${
                  plan.isPopular
                    ? 'bg-[#34D399] text-[#0A0A0B] hover:bg-[#34D399]/90'
                    : plan.isCustom
                    ? 'border border-[#F5F5F3] text-[#F5F5F3] hover:bg-[#F5F5F3]/10'
                    : 'bg-[#F5F5F3] text-[#0A0A0B] hover:bg-[#F5F5F3]/90'
                }`}
              >
                {plan.ctaText}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
