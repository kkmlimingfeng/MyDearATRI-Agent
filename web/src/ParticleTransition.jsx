import { useEffect, useRef } from 'react';
import { createParticles } from './particleGeometry';

const JOIN_END = 1050;
const REVEAL_AT = 900;
const HOP_START = 1550;
const HOP_STAGGER = 190;
const HOP_LENGTH = 310;
const SCATTER_START = 2880;
const DURATION = 3930;
const clamp = (value) => Math.min(1, Math.max(0, value));
const smooth = (value) => {
  const position = clamp(value);
  return position * position * (3 - 2 * position);
};
const mix = (start, end, amount) => start + (end - start) * amount;
export default function ParticleTransition({ onReveal, onComplete, intro = false }) {
  const canvasRef = useRef(null);
  const backgroundRef = useRef(null);
  const handlers = useRef({ onReveal, onComplete });
  handlers.current = { onReveal, onComplete };

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    const backgroundCanvas = backgroundRef.current;
    const backgroundContext = backgroundCanvas?.getContext('2d');
    if (!context || !backgroundContext) {
      handlers.current.onReveal();
      handlers.current.onComplete();
      return undefined;
    }
    const colors = getComputedStyle(document.documentElement);
    const accent = colors.getPropertyValue('--theme-accent').trim() || '#39836a';
    const background = colors.getPropertyValue('--canvas').trim() || '#e8efea';
    const sparkle = colors.getPropertyValue('--panel').trim() || '#fff';
    let transparentBackground = '';
    if (!intro) {
      backgroundContext.fillStyle = background;
      backgroundContext.fillRect(0, 0, 1, 1);
      const [red, green, blue] = backgroundContext.getImageData(0, 0, 1, 1).data;
      transparentBackground = `rgba(${red}, ${green}, ${blue}, 0)`;
    }
    let width = 0;
    let height = 0;
    let particles = [];
    let frame = 0;
    let started = null;
    let revealed = false;
    let worker = null;
    let generation = 0;
    let animationStarted = false;
    const acceptParticles = (nextParticles) => {
      particles = nextParticles;
      if (!animationStarted) {
        animationStarted = true;
        frame = requestAnimationFrame(draw);
      }
    };
    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(3_200_000 / (width * height)));
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const backgroundRatio = Math.min(1, 1280 / Math.max(width, height));
      backgroundCanvas.width = Math.round(width * backgroundRatio);
      backgroundCanvas.height = Math.round(height * backgroundRatio);
      backgroundContext.setTransform(backgroundRatio, 0, 0, backgroundRatio, 0, 0);
      const id = ++generation;
      if (worker) worker.postMessage({ id, width, height });
      else acceptParticles(createParticles(width, height, document.createElement('canvas')));
    };

    const drawBackground = (elapsed, scatter) => {
      if (intro) return;
      backgroundContext.clearRect(0, 0, width, height);
      const cover = elapsed < JOIN_END ? smooth(elapsed / JOIN_END) : 1 - scatter;
      if (cover <= 0) return;
      const diagonal = Math.hypot(width, height);
      const radius = diagonal * 1.15 * cover;
      const wash = backgroundContext.createRadialGradient(width / 2, height / 2, radius * 0.52, width / 2, height / 2, radius);
      wash.addColorStop(0, background);
      wash.addColorStop(1, transparentBackground);
      backgroundContext.fillStyle = wash;
      backgroundContext.fillRect(0, 0, width, height);
      backgroundContext.globalAlpha = 1;

      const stripePhase = (elapsed % 16000) / 8000;
      const stripeDrift = 70 * (stripePhase <= 1 ? stripePhase : 2 - stripePhase);
      backgroundContext.save();
      backgroundContext.globalCompositeOperation = 'source-atop';
      backgroundContext.globalAlpha = 0.6;
      backgroundContext.fillStyle = '#fff';
      backgroundContext.translate(width / 2 + stripeDrift, height / 2);
      backgroundContext.rotate(Math.PI / 3);
      for (let offset = -diagonal; offset < diagonal; offset += 64) {
        backgroundContext.fillRect(offset + 28, -diagonal, 10, diagonal * 2);
      }
      backgroundContext.restore();
    };

    const draw = (now) => {
      if (started === null) started = now;
      const elapsed = now - started;
      if (!revealed && elapsed >= REVEAL_AT) {
        revealed = true;
        handlers.current.onReveal();
      }
      context.clearRect(0, 0, width, height);
      const scatter = smooth((elapsed - SCATTER_START) / (DURATION - SCATTER_START));
      drawBackground(elapsed, scatter);
      const gather = smooth(elapsed / JOIN_END);
      const opacity = gather * (1 - scatter);
      if (opacity > 0) {
        const hops = [0, 1, 2, 3].map((letter) => elapsed < SCATTER_START
          ? -Math.sin(Math.PI * clamp((elapsed - HOP_START - letter * HOP_STAGGER) / HOP_LENGTH)) * Math.min(30, height * 0.045)
          : 0);
        context.globalAlpha = opacity;
        for (let pass = 0; pass < 2; pass += 1) {
          context.beginPath();
          for (let index = 0; index < particles.length; index += 1) {
            if ((index % 13 === 0) !== (pass === 1)) continue;
            const particle = particles[index];
            const radius = scatter > 0
              ? mix(particle.targetRadius, particle.endRadius, scatter)
              : mix(particle.startRadius, particle.targetRadius, gather);
            const angle = scatter > 0
              ? particle.targetAngle + particle.scatterAngle * scatter
              : particle.startAngle + particle.joinAngle * gather;
            const x = width / 2 + radius * Math.cos(angle);
            const y = height / 2 + radius * Math.sin(angle) + hops[particle.letter];
            context.rect(x, y, particle.size, particle.size);
          }
          context.fillStyle = pass === 1 ? sparkle : accent;
          context.fill();
        }
        context.globalAlpha = 1;
      }
      if (elapsed < DURATION) frame = requestAnimationFrame(draw);
      else handlers.current.onComplete();
    };

    frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        if (intro && typeof Worker !== 'undefined' && typeof OffscreenCanvas !== 'undefined') {
          try {
            worker = new Worker(new URL('./particleWorker.js', import.meta.url), { type: 'module' });
            worker.onmessage = ({ data }) => {
              if (data.id === generation) acceptParticles(data.particles);
            };
            worker.onerror = () => {
              worker?.terminate();
              worker = null;
              acceptParticles(createParticles(width, height, document.createElement('canvas')));
            };
          } catch {
            worker = null;
          }
        }
        resize();
        window.addEventListener('resize', resize);
      });
    });
    return () => {
      cancelAnimationFrame(frame);
      worker?.terminate();
      window.removeEventListener('resize', resize);
    };
  }, []);

  return <div className="particle-transition" style={intro ? { backgroundColor: 'var(--canvas)' } : undefined} aria-hidden="true">
    <canvas ref={backgroundRef} className="particle-transition-background" />
    {intro && <div className="particle-transition-intro-stripes" />}
    <canvas ref={canvasRef} className="particle-transition-particles" />
  </div>;
}
