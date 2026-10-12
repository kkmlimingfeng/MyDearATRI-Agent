const WORD = 'ATRI';
const FULL_TURN = Math.PI * 2;
const SPIRAL_TURNS = 2;

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

export function createParticles(width, height, textCanvas) {
  const random = randomGenerator();
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
