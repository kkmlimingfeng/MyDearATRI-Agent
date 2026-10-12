const typeColors = {
  any: '#74808b',
  text: '#7874d8',
  prompt: '#a467d6',
  context: '#39a6a5',
  memory: '#58a675',
  skills: '#83a84c',
  tools: '#da8945',
  tool_executor: '#d5794f',
  skill_executor: '#709d65',
  mcp: '#6b90ce',
  tool_schemas: '#c5a244',
  capability_handlers: '#6b90ce',
  llm: '#5a9fd2',
  model_response: '#b66cc1',
  tool_calls: '#d46f67',
  tool_results: '#45ac8a',
  trace: '#8c80ba',
  loop: '#c38a54',
};

export function getPortTypeColor(type) {
  const name = String(type || 'any');
  if (Object.hasOwn(typeColors, name)) return typeColors[name];
  let hash = 0;
  for (const character of name) hash = (hash * 31 + character.codePointAt(0)) >>> 0;
  const hue = hash % 360;
  const chroma = (1 - Math.abs(2 * 0.48 - 1)) * 0.55;
  const secondary = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
  const [red, green, blue] = hue < 60 ? [chroma, secondary, 0]
    : hue < 120 ? [secondary, chroma, 0]
      : hue < 180 ? [0, chroma, secondary]
        : hue < 240 ? [0, secondary, chroma]
          : hue < 300 ? [secondary, 0, chroma] : [chroma, 0, secondary];
  const toHex = (channel) => Math.round((channel + 0.48 - chroma / 2) * 255).toString(16).padStart(2, '0');
  return `#${toHex(red)}${toHex(green)}${toHex(blue)}`;
}

export function portsCompatible(sourceType, targetType) {
  return Boolean(sourceType && targetType)
    && (sourceType === targetType || sourceType === 'any' || targetType === 'any');
}
