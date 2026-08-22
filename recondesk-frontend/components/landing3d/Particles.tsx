'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { LANDING, remap, lerp } from '@/lib/landing-tokens';

/**
 * Spreadsheet-cell particles that complement the invoice stack.
 * Count ramps up during pain, coalesces during the turn, then
 * drops to a calm ambient shimmer.
 */
export default function Particles({
  progress,
  count = 200,
}: {
  progress: number;
  count?: number;
}) {
  const pointsRef = useRef<THREE.Points>(null);

  // Generate particle positions
  const { positions, basePositions, gridPositions } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const base = new Float32Array(count * 3);
    const grid = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;

      // Random scattered positions (chaos state)
      const angle = Math.random() * Math.PI * 2;
      const radius = 1 + Math.random() * 4;
      const height = (Math.random() - 0.5) * 5;

      base[i3] = Math.cos(angle) * radius;
      base[i3 + 1] = height;
      base[i3 + 2] = Math.sin(angle) * radius;

      pos[i3] = base[i3];
      pos[i3 + 1] = base[i3 + 1];
      pos[i3 + 2] = base[i3 + 2];

      // Grid positions (resolved state) — arranged in a flat grid
      const cols = Math.ceil(Math.sqrt(count));
      const row = Math.floor(i / cols);
      const col = i % cols;
      grid[i3] = (col - cols / 2) * 0.12;
      grid[i3 + 1] = (row - cols / 2) * 0.08;
      grid[i3 + 2] = 0;
    }

    return { positions: pos, basePositions: base, gridPositions: grid };
  }, [count]);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geo;
  }, [positions]);

  useFrame((state) => {
    if (!pointsRef.current) return;
    const time = state.clock.elapsedTime;
    const posAttr = geometry.attributes.position as THREE.BufferAttribute;
    const { scroll } = LANDING;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;

      if (progress < scroll.turnStart) {
        // Chaos / pain: particles drift with increasing energy
        const painT = remap(progress, scroll.painStart, scroll.painEnd);
        const energy = 0.3 + painT * 0.7;
        const seed = i * 1.618;

        posAttr.array[i3] =
          basePositions[i3] +
          Math.sin(time * energy + seed) * (0.2 + painT * 0.4);
        posAttr.array[i3 + 1] =
          basePositions[i3 + 1] +
          Math.cos(time * energy * 0.7 + seed * 1.3) * (0.15 + painT * 0.3);
        posAttr.array[i3 + 2] =
          basePositions[i3 + 2] +
          Math.sin(time * energy * 0.5 + seed * 0.7) * (0.1 + painT * 0.2);
      } else if (progress < scroll.turnEnd) {
        // Turn: coalesce toward grid
        const turnT = remap(progress, scroll.turnStart, scroll.turnEnd);
        posAttr.array[i3] = lerp(
          basePositions[i3],
          gridPositions[i3],
          turnT,
        );
        posAttr.array[i3 + 1] = lerp(
          basePositions[i3 + 1],
          gridPositions[i3 + 1],
          turnT,
        );
        posAttr.array[i3 + 2] = lerp(
          basePositions[i3 + 2],
          gridPositions[i3 + 2] - progress * 3,
          turnT,
        );
      } else {
        // Ambient: gentle drift around grid positions
        const drift = 0.03;
        posAttr.array[i3] =
          gridPositions[i3] + Math.sin(time * 0.3 + i) * drift;
        posAttr.array[i3 + 1] =
          gridPositions[i3 + 1] + Math.cos(time * 0.25 + i * 0.7) * drift;
        posAttr.array[i3 + 2] =
          gridPositions[i3 + 2] - (progress - scroll.turnEnd) * 3;
      }
    }

    posAttr.needsUpdate = true;

    // Opacity: visible during pain/turn, fading during pricing
    const pricingFade = remap(progress, scroll.pricingStart, scroll.pricingEnd);
    const closeFadeIn = remap(progress, scroll.closeStart, 1.0);
    const mat = pointsRef.current.material as THREE.PointsMaterial;
    mat.opacity = Math.max(0, lerp(0.6, 0, pricingFade) + closeFadeIn * 0.3);

    // Color shift: white during pain, accent after turn
    if (progress > scroll.turnMid) {
      const colorT = remap(progress, scroll.turnMid, scroll.turnEnd);
      const r = lerp(0.96, 0.204, colorT);
      const g = lerp(0.96, 0.827, colorT);
      const b = lerp(0.95, 0.6, colorT);
      mat.color.setRGB(r, g, b);
    } else {
      mat.color.setRGB(0.96, 0.96, 0.95);
    }
  });

  return (
    <points ref={pointsRef} geometry={geometry}>
      <pointsMaterial
        size={0.025}
        transparent
        opacity={0.5}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}
