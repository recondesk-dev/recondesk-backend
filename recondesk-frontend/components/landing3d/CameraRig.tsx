'use client';

import { useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { LANDING, remap, lerp } from '@/lib/landing-tokens';

/**
 * Scroll-driven camera controller.
 *
 * - Hero:    Wide view of the stack from a comfortable distance
 * - Pain:    Camera moves through the stack, FOV narrows (claustrophobic)
 * - Turn:    Camera pulls back to reveal the resolved grid, FOV widens (relief)
 * - Ambient: Camera settles at a calm viewing distance
 */
export default function CameraRig({ progress }: { progress: number }) {
  const { camera } = useThree();
  const targetPos = useRef(new THREE.Vector3(0, 0, 8));
  const targetLookAt = useRef(new THREE.Vector3(0, 0, 0));

  useFrame(() => {
    const { scroll } = LANDING;
    const cam = camera as THREE.PerspectiveCamera;

    // --- Camera position keyframes ---
    if (progress < scroll.heroEnd) {
      // Hero: wide establishing shot
      targetPos.current.set(0, 0.5, 8);
      targetLookAt.current.set(0, 0, 0);
      cam.fov = 50;
    } else if (progress < scroll.turnStart) {
      // Pain: push through the chaos
      const painT = remap(progress, scroll.painStart, scroll.painEnd);

      // Camera pushes in and drifts through the stack
      const z = lerp(8, 2.5, painT);
      const x = Math.sin(painT * Math.PI * 0.5) * 1.5;
      const y = lerp(0.5, 0, painT) + Math.sin(painT * Math.PI) * 0.3;

      targetPos.current.set(x, y, z);
      targetLookAt.current.set(0, 0, 0);

      // FOV narrows — claustrophobic
      cam.fov = lerp(50, 38, painT);
    } else if (progress < scroll.turnEnd) {
      // Turn: pull back to reveal the resolved grid
      const turnT = remap(progress, scroll.turnStart, scroll.turnEnd);

      const z = lerp(2.5, 7, turnT);
      const x = lerp(1.5, 0, turnT);
      const y = lerp(0, 0.8, turnT);

      targetPos.current.set(x, y, z);
      targetLookAt.current.set(0, 0, 0);

      // FOV widens — relief/openness
      cam.fov = lerp(38, 55, turnT);
    } else {
      // Ambient: settled, slowly receding
      const ambientT = remap(progress, scroll.turnEnd, 1.0);
      const z = lerp(7, 12, ambientT);

      targetPos.current.set(0, 0.5, z);
      targetLookAt.current.set(0, 0, -ambientT * 2);
      cam.fov = 55;
    }

    // Smooth interpolation (damping)
    camera.position.lerp(targetPos.current, 0.08);
    const lookTarget = new THREE.Vector3().copy(targetLookAt.current);
    camera.lookAt(lookTarget);
    cam.updateProjectionMatrix();
  });

  return null;
}
