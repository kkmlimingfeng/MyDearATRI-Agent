export function normalizeLive2dFolder(files) {
  if (!files.length) return null;
  const paths = files.map(({ path }) => path.replace(/\\/g, '/'));
  const roots = new Set(paths.map((path) => path.split('/')[0]));
  if (roots.size !== 1 || paths.some((path) => !path.includes('/'))) return null;

  const root = [...roots][0];
  const relativePaths = paths.map((path) => path.slice(root.length + 1));
  const modelAtRoot = relativePaths.some((path) => path.toLowerCase().endsWith('.model3.json') && !path.includes('/'));
  const modelInLive2d = relativePaths.some((path) => /^live2d\/[^/]+\.model3\.json$/i.test(path));
  if (modelAtRoot) {
    return files.map((item, index) => ({ ...item, path: `live2d/${relativePaths[index]}` }));
  }
  if (!modelInLive2d) return null;
  return files.flatMap((item, index) => {
    const path = relativePaths[index];
    return path.toLowerCase().startsWith('live2d/')
      ? [{ ...item, path: `live2d/${path.slice('live2d/'.length)}` }]
      : [];
  });
}
