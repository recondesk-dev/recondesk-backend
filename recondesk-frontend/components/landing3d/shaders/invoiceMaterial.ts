/**
 * Custom shader material for the invoice planes.
 *
 * Vertex: accepts per-instance transforms + a `uChaos` uniform for jitter.
 * Fragment: translucent white with a subtle grid pattern, color-lerps
 * to red (pain) or green (resolved) based on uniforms.
 */

export const invoiceVertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uChaos;

  varying vec2 vUv;
  varying float vChaosInfluence;

  // Simple pseudo-random for jitter
  float rand(vec2 co) {
    return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
  }

  void main() {
    vUv = uv;

    vec3 pos = position;

    // Add chaos jitter based on instance position
    float instanceSeed = rand(vec2(pos.x * 100.0, pos.z * 100.0));
    vChaosInfluence = instanceSeed;

    // Jitter scales with uChaos
    pos.x += sin(uTime * 2.0 + instanceSeed * 6.28) * uChaos * 0.15;
    pos.y += cos(uTime * 1.7 + instanceSeed * 3.14) * uChaos * 0.1;
    pos.z += sin(uTime * 1.3 + instanceSeed * 9.42) * uChaos * 0.08;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`;

export const invoiceFragmentShader = /* glsl */ `
  uniform float uOpacity;
  uniform vec3 uColor;
  uniform float uGridIntensity;

  varying vec2 vUv;
  varying float vChaosInfluence;

  void main() {
    // Subtle grid/ledger-line pattern
    float lineX = step(0.98, fract(vUv.x * 12.0));
    float lineY = step(0.96, fract(vUv.y * 8.0));
    float grid = max(lineX, lineY) * uGridIntensity;

    // Edge fade for translucency
    float edgeFade = smoothstep(0.0, 0.05, vUv.x)
                   * smoothstep(1.0, 0.95, vUv.x)
                   * smoothstep(0.0, 0.05, vUv.y)
                   * smoothstep(1.0, 0.95, vUv.y);

    vec3 baseColor = uColor;
    vec3 gridColor = baseColor + vec3(grid * 0.15);

    float alpha = uOpacity * edgeFade * (0.6 + grid * 0.2);

    gl_FragColor = vec4(gridColor, alpha);
  }
`;

/**
 * Uniforms factory for the invoice material.
 */
export function createInvoiceUniforms() {
  return {
    uTime: { value: 0 },
    uChaos: { value: 0 },
    uOpacity: { value: 0.6 },
    uColor: { value: [0.96, 0.96, 0.95] }, // paper white
    uGridIntensity: { value: 0.4 },
  };
}
