import { useEffect, useRef } from 'react';

const WORD = 'ATRI';
const JOIN_END = 1050;
const HOP_START = 1550;
const HOP_STAGGER = 190;
const HOP_LENGTH = 310;
const SCATTER_START = 2880;
const DURATION = 3930;
const FULL_TURN = Math.PI * 2;
const SPIRAL_TURNS = 2;

const clamp = (value) => Math.min(1, Math.max(0, value));
const smooth = (value) => {
  const position = clamp(value);
  return position * position * (3 - 2 * position);
};
const mix = (start, end, amount) => start + (end - start) * amount;
const polar = (x, y, centerX, centerY) => ({
  radius: Math.hypot(x - centerX, y - centerY),
  angle: Math.atan2(y - centerY, x - centerX),
});
const spiralAngle = (from, to) => SPIRAL_TURNS * FULL_TURN + ((to - from + FULL_TURN) % FULL_TURN);

function randomGenerator() {
  let seed = 0x41545249;
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
}

function createParticles(width, height) {
  const random = randomGenerator();
  const textCanvas = document.createElement('canvas');
  textCanvas.width = Math.ceil(width);
  textCanvas.height = Math.ceil(height);
  const context = textCanvas.getContext('2d', { willReadFrequently: true });
  if (!context) return [];

  let fontSize = Math.min(width * 0.27, height * 0.41);
  const setFont = () => { context.font = `900 ${fontSize}px "Segoe UI", Arial, sans-serif`; };
  setFont();
  const measureWidth = () => [...WORD].reduce((sum, letter) => sum + context.measureText(letter).width, 0) + fontSize * 0.07 * (WORD.length - 1);
  fontSize = Math.min(height * 0.41, fontSize * (width * 0.62 / measureWidth()));
  setFont();
  const letters = [...WORD];
  const widths = letters.map((letter) => context.measureText(letter).width);
  const gap = fontSize * 0.07;
  const wordWidth = widths.reduce((sum, value) => sum + value, 0) + gap * (letters.length - 1);
  const top = Math.max(0, Math.floor(height / 2 - fontSize * 0.65));
  const bottom = Math.min(textCanvas.height, Math.ceil(height / 2 + fontSize * 0.65));
  const left = Math.max(0, Math.floor((width - wordWidth) / 2 - 2));
  const right = Math.min(textCanvas.width, Math.ceil((width + wordWidth) / 2 + 2));
  const positions = [];
  context.fillStyle = '#fff';
  context.textBaseline = 'middle';
  let cursor = (width - wordWidth) / 2;
  letters.forEach((letter, index) => {
    positions.push(cursor);
    context.fillText(letter, cursor, height / 2);
    cursor += widths[index] + gap;
  });

  const pixels = context.getImageData(left, top, right - left, bottom - top);
  const limit = width < 640 ? 850 : 1850;
  const step = Math.max(3, Math.round(Math.sqrt(wordWidth * fontSize * 0.48 / limit)));
  const particles = [];
  const centerX = width / 2;
  const centerY = height / 2;
  for (let y = top; y < bottom; y += step) {
    for (let x = left; x < right; x += step) {
      const alpha = pixels.data[((y - top) * pixels.width + x - left) * 4 + 3];
      if (alpha < 120) continue;
      const letter = positions.findIndex((position, index) => x < position + widths[index] + gap / 2);
      const start = polar(random() * width, random() * height, centerX, centerY);
      const target = polar(x, y, centerX, centerY);
      const end = polar(centerX + (random() - 0.5) * width * 1.55, centerY + (random() - 0.5) * height * 1.55, centerX, centerY);
      particles.push({
        startRadius: start.radius,
        startAngle: start.angle,
        targetRadius: target.radius,
        targetAngle: target.angle,
        endRadius: end.radius,
        joinAngle: spiralAngle(start.angle, target.angle),
        scatterAngle: spiralAngle(target.angle, end.angle),
        letter: Math.max(0, letter),
        size: Math.max(1.7, Math.min(3.2, step * 0.34)),
      });
    }
  }
  for (let index = particles.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1));
    [particles[index], particles[other]] = [particles[other], particles[index]];
  }
  return particles.slice(0, limit);
}

export default function ParticleTransition({ onReveal, onComplete }) {
  const canvasRef = useRef(null);
  const backgroundRef = useRef(null);
  const stripeRef = useRef(null);
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
    backgroundContext.fillStyle = background;
    backgroundContext.fillRect(0, 0, 1, 1);
    const [red, green, blue] = backgroundContext.getImageData(0, 0, 1, 1).data;
    const transparentBackground = `rgba(${red}, ${green}, ${blue}, 0)`;
    let width = 0;
    let height = 0;
    let particles = [];
    let frame = 0;
    let started = null;
    let revealed = false;

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      backgroundCanvas.width = canvas.width;
      backgroundCanvas.height = canvas.height;
      backgroundContext.setTransform(ratio, 0, 0, ratio, 0, 0);
      particles = createParticles(width, height);
    };

    const draw = (now) => {
      if (started === null) started = now;
      const elapsed = now - started;
      if (!revealed && elapsed >= JOIN_END) {
        revealed = true;
        handlers.current.onReveal();
      }
      context.clearRect(0, 0, width, height);
      backgroundContext.clearRect(0, 0, width, height);
      const scatter = smooth((elapsed - SCATTER_START) / (DURATION - SCATTER_START));
      const cover = elapsed < JOIN_END ? smooth(elapsed / JOIN_END) : 1 - scatter;
      const radius = Math.hypot(width, height) * 1.15 * cover;
      stripeRef.current?.style.setProperty('--wash-radius', `${radius}px`);
      if (cover > 0) {
        const wash = backgroundContext.createRadialGradient(width / 2, height / 2, radius * 0.52, width / 2, height / 2, radius);
        wash.addColorStop(0, background);
        wash.addColorStop(1, transparentBackground);
        backgroundContext.fillStyle = wash;
        backgroundContext.fillRect(0, 0, width, height);
      }

      const gather = smooth(elapsed / JOIN_END);
      const opacity = gather * (1 - scatter);
      context.globalAlpha = opacity;
      for (const [index, particle] of particles.entries()) {
        const hopPhase = clamp((elapsed - HOP_START - particle.letter * HOP_STAGGER) / HOP_LENGTH);
        const hop = elapsed < SCATTER_START ? -Math.sin(Math.PI * hopPhase) * Math.min(30, height * 0.045) : 0;
        const radius = scatter > 0
          ? mix(particle.targetRadius, particle.endRadius, scatter)
          : mix(particle.startRadius, particle.targetRadius, gather);
        const angle = scatter > 0
          ? particle.targetAngle + particle.scatterAngle * scatter
          : particle.startAngle + particle.joinAngle * gather;
        const x = width / 2 + radius * Math.cos(angle);
        const y = height / 2 + radius * Math.sin(angle) + hop;
        context.fillStyle = index % 13 === 0 ? sparkle : accent;
        context.fillRect(x, y, particle.size, particle.size);
      }
      context.globalAlpha = 1;
      if (elapsed < DURATION) frame = requestAnimationFrame(draw);
      else handlers.current.onComplete();
    };

    resize();
    window.addEventListener('resize', resize);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return <div className="particle-transition" aria-hidden="true">
    <canvas ref={backgroundRef} className="particle-transition-background" />
    <div ref={stripeRef} className="particle-transition-stripes" />
    <canvas ref={canvasRef} className="particle-transition-particles" />
  </div>;
}
