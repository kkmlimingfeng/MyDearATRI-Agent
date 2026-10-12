import { createParticles } from './particleGeometry';

self.onmessage = ({ data: { id, width, height } }) => {
  const canvas = new OffscreenCanvas(Math.ceil(width), Math.ceil(height));
  self.postMessage({ id, particles: createParticles(width, height, canvas) });
};
