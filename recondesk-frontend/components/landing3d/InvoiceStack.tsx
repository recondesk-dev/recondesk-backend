'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { LANDING, remap, lerp } from '@/lib/landing-tokens';

/**
 * The signature 3D object. A stack of translucent "invoice" planes that:
 * - Hero (0–12%):    Loose, slowly rotating, calm
 * - Pain (12–52%):   More planes, tilting chaos, some turn red, jitter
 * - Turn (52–72%):   Split into two streams → collide into resolved grid
 * - Ambient (72%+):  Resolved grid, slow rotation, recedes
 */

interface InvoiceData {
  position: THREE.Vector3;
  rotation: THREE.Euler;
  scale: THREE.Vector3;
  color: THREE.Color;
  targetPosition: THREE.Vector3;
  targetRotation: THREE.Euler;
  stream: 'gstr2b' | 'pr';
  matched: boolean;
}

const PAPER_COLOR = new THREE.Color(LANDING.colors.paper);
const DANGER_COLOR = new THREE.Color(LANDING.colors.danger);
const ACCENT_COLOR = new THREE.Color(LANDING.colors.accent);
const SURFACE_COLOR = new THREE.Color(LANDING.colors.surface);

export default function InvoiceStack({
  progress,
  count = 24,
}: {
  progress: number;
  count?: number;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const meshRefs = useRef<THREE.Mesh[]>([]);
  const materialRefs = useRef<THREE.MeshStandardMaterial[]>([]);

  // Generate invoice plane data
  const invoices = useMemo<InvoiceData[]>(() => {
    const items: InvoiceData[] = [];
    const half = Math.floor(count / 2);

    for (let i = 0; i < count; i++) {
      const isGstr2b = i < half;
      const row = Math.floor((i % half) / 4);
      const col = (i % half) % 4;

      // Chaotic initial positions (spread in a rough stack)
      const angle = (i / count) * Math.PI * 2;
      const radius = 1.2 + Math.random() * 1.8;
      const chaosPos = new THREE.Vector3(
        Math.cos(angle) * radius + (Math.random() - 0.5) * 1.5,
        (Math.random() - 0.5) * 3,
        Math.sin(angle) * radius + (Math.random() - 0.5) * 1.5,
      );

      const chaosRot = new THREE.Euler(
        (Math.random() - 0.5) * 1.2,
        (Math.random() - 0.5) * Math.PI,
        (Math.random() - 0.5) * 0.8,
      );

      // Resolved grid positions (two sides merging to center)
      const gridX = (col - 1.5) * 1.1;
      const gridY = (row - 1) * 0.7;
      const gridZ = isGstr2b ? -0.05 : 0.05; // Slight z-offset for depth

      const targetPos = new THREE.Vector3(gridX, gridY, gridZ);
      const targetRot = new THREE.Euler(0, 0, 0);

      items.push({
        position: chaosPos,
        rotation: chaosRot,
        scale: new THREE.Vector3(0.9, 0.55, 1),
        color: PAPER_COLOR.clone(),
        targetPosition: targetPos,
        targetRotation: targetRot,
        stream: isGstr2b ? 'gstr2b' : 'pr',
        matched: i % 5 !== 0, // ~80% match rate
      });
    }
    return items;
  }, [count]);

  useFrame((state) => {
    if (!groupRef.current) return;
    const time = state.clock.elapsedTime;

    const { scroll } = LANDING;

    // Slow ambient rotation of the whole group
    const rotSpeed = progress > scroll.turnEnd ? 0.05 : 0.15;
    groupRef.current.rotation.y = time * rotSpeed;

    // Per-invoice animation
    meshRefs.current.forEach((mesh, i) => {
      if (!mesh) return;
      const inv = invoices[i];
      const mat = materialRefs.current[i];

      // --- HERO PHASE: gentle float ---
      if (progress < scroll.painStart) {
        const heroT = remap(progress, 0, scroll.heroEnd);
        mesh.position.copy(inv.position);
        mesh.rotation.copy(inv.rotation);
        // Gentle float
        mesh.position.y += Math.sin(time * 0.8 + i * 0.5) * 0.08;
        mesh.position.x += Math.cos(time * 0.6 + i * 0.3) * 0.05;
        if (mat) {
          mat.opacity = lerp(0.3, 0.5, heroT);
          mat.color.copy(PAPER_COLOR);
        }
        return;
      }

      // --- PAIN PHASE: escalating chaos ---
      if (progress < scroll.turnStart) {
        const painT = remap(progress, scroll.painStart, scroll.painEnd);

        // Increasing jitter
        const jitterAmp = painT * LANDING.motion.painShakeIntensity * 80;
        const jx = Math.sin(time * 3 + i * 1.7) * jitterAmp;
        const jy = Math.cos(time * 2.5 + i * 2.3) * jitterAmp;
        const jz = Math.sin(time * 1.8 + i * 3.1) * jitterAmp * 0.5;

        mesh.position.set(
          inv.position.x + jx,
          inv.position.y + jy + Math.sin(time * 0.8 + i) * 0.08,
          inv.position.z + jz,
        );

        // Rotation chaos increases
        mesh.rotation.set(
          inv.rotation.x + Math.sin(time * 1.2 + i) * painT * 0.3,
          inv.rotation.y + time * 0.1,
          inv.rotation.z + Math.cos(time * 0.9 + i) * painT * 0.2,
        );

        // Some planes turn red as pain escalates
        if (mat) {
          const turnRed = i % 3 === 0 && painT > 0.3;
          const redT = turnRed ? remap(painT, 0.3, 0.8) : 0;
          mat.color.copy(PAPER_COLOR).lerp(DANGER_COLOR, redT);
          mat.opacity = lerp(0.4, 0.65, painT);
        }
        return;
      }

      // --- TURN PHASE: chaos → two streams → resolved grid ---
      if (progress < scroll.turnEnd) {
        const turnT = remap(progress, scroll.turnStart, scroll.turnEnd);

        if (turnT < 0.4) {
          // Phase 1: Freeze + split into two streams
          const splitT = remap(turnT, 0, 0.4);
          const streamOffset = inv.stream === 'gstr2b' ? -3 : 3;
          const streamX = lerp(inv.position.x, streamOffset, splitT);
          const streamY = lerp(inv.position.y, inv.targetPosition.y, splitT * 0.5);

          mesh.position.set(streamX, streamY, lerp(inv.position.z, 0, splitT));
          mesh.rotation.set(
            lerp(inv.rotation.x, 0, splitT),
            lerp(inv.rotation.y, 0, splitT),
            lerp(inv.rotation.z, 0, splitT),
          );

          if (mat) {
            mat.color.copy(PAPER_COLOR);
            mat.opacity = 0.55;
          }
        } else if (turnT < 0.7) {
          // Phase 2: Streams flow toward center
          const flowT = remap(turnT, 0.4, 0.7);
          const streamOffset = inv.stream === 'gstr2b' ? -3 : 3;
          const startX = streamOffset;
          const endX = inv.targetPosition.x;

          mesh.position.set(
            lerp(startX, endX, flowT),
            lerp(inv.targetPosition.y, inv.targetPosition.y, flowT),
            lerp(0, inv.targetPosition.z, flowT),
          );
          mesh.rotation.set(0, 0, 0);

          if (mat) {
            mat.color.copy(PAPER_COLOR);
            mat.opacity = lerp(0.55, 0.7, flowT);
          }
        } else {
          // Phase 3: Lock into grid, matched pairs turn green
          const lockT = remap(turnT, 0.7, 1.0);

          mesh.position.copy(inv.targetPosition);
          mesh.rotation.set(0, 0, 0);

          if (mat) {
            if (inv.matched) {
              mat.color.copy(PAPER_COLOR).lerp(ACCENT_COLOR, lockT);
              mat.emissive.copy(ACCENT_COLOR);
              mat.emissiveIntensity = lockT * 0.15;
            } else {
              // Unmatched: subtle amber outline effect
              mat.color.copy(SURFACE_COLOR);
              mat.emissive.set(0, 0, 0);
            }
            mat.opacity = lerp(0.7, 0.85, lockT);
          }
        }
        return;
      }

      // --- AMBIENT PHASE: resolved grid, receding ---
      const ambientT = remap(progress, scroll.turnEnd, 1.0);
      mesh.position.copy(inv.targetPosition);
      mesh.rotation.set(0, 0, 0);

      // Slowly recede
      mesh.position.z -= ambientT * 3;

      if (mat) {
        if (inv.matched) {
          mat.color.copy(ACCENT_COLOR);
          mat.emissive.copy(ACCENT_COLOR);
          mat.emissiveIntensity = 0.12;
        } else {
          mat.color.copy(SURFACE_COLOR);
          mat.emissive.set(0, 0, 0);
        }
        // Fade out during pricing section
        const pricingFade = remap(progress, scroll.pricingStart, scroll.pricingEnd);
        const closeFadeIn = remap(progress, scroll.closeStart, 1.0);
        mat.opacity = lerp(0.8, 0, pricingFade) + closeFadeIn * 0.5;
      }
    });
  });

  return (
    <group ref={groupRef}>
      {invoices.map((inv, i) => (
        <mesh
          key={i}
          ref={(el) => {
            if (el) meshRefs.current[i] = el;
          }}
          position={inv.position.toArray()}
          rotation={[inv.rotation.x, inv.rotation.y, inv.rotation.z]}
          scale={inv.scale.toArray()}
        >
          <planeGeometry args={[1, 0.65, 1, 1]} />
          <meshStandardMaterial
            ref={(el) => {
              if (el) materialRefs.current[i] = el;
            }}
            color={inv.color}
            transparent
            opacity={0.4}
            side={THREE.DoubleSide}
            depthWrite={false}
            roughness={0.7}
            metalness={0.0}
          />
        </mesh>
      ))}
    </group>
  );
}
