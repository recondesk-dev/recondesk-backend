'use client';

import { Suspense, useState, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { Preload } from '@react-three/drei';

import InvoiceStack from './InvoiceStack';
import Particles from './Particles';
import CameraRig from './CameraRig';
import { useScrollProgress } from './useScrollProgress';
import { getPerformanceTier } from '@/lib/landing-tokens';

/**
 * Persistent R3F Canvas — fixed, full-bleed, z-0.
 * Dynamically imported with ssr: false from the page.
 *
 * Contains:
 * - CameraRig (scroll-driven position/FOV)
 * - InvoiceStack (chaos → order transition)
 * - Particles (ambient spreadsheet cells)
 * - Lighting (color-lerps with scroll)
 *
 * For prefers-reduced-motion: renders nothing (the fallback
 * component is rendered by the page instead).
 */
export default function LandingScene() {
  const { progress, reducedMotion } = useScrollProgress();
  const [tier, setTier] = useState({ invoicePlanes: 20, particles: 200 });

  useEffect(() => {
    const update = () => setTier(getPerformanceTier(window.innerWidth));
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  // Skip 3D entirely for reduced-motion users
  if (reducedMotion) return null;

  return (
    <div
      className="fixed inset-0 z-0"
      style={{ pointerEvents: 'none' }}
      aria-hidden="true"
    >
      <Canvas
        camera={{ position: [0, 0.5, 8], fov: 50, near: 0.1, far: 50 }}
        dpr={[1, 1.5]}
        gl={{
          antialias: true,
          alpha: true,
          powerPreference: 'high-performance',
        }}
        style={{ background: 'transparent' }}
      >
        <Suspense fallback={null}>
          {/* Lighting */}
          <ambientLight intensity={0.4} />
          <directionalLight
            position={[5, 5, 5]}
            intensity={0.6}
            castShadow={false}
          />
          <directionalLight
            position={[-3, 2, -4]}
            intensity={0.2}
            color="#6B6B70"
          />

          {/* 3D Objects */}
          <CameraRig progress={progress} />
          <InvoiceStack progress={progress} count={tier.invoicePlanes} />
          <Particles progress={progress} count={tier.particles} />

          <Preload all />
        </Suspense>
      </Canvas>
    </div>
  );
}
