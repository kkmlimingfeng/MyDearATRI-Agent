const AVATAR_KEYS = {
  user: 'atri.chat.avatar.user.v1',
  agent: 'atri.chat.avatar.agent.v1',
};

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const AVATAR_SIZE = 512;

async function decodeImageFile(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file);
    } catch { /* Fall back to the image element for browser decoder compatibility. */ }
  }

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('图片读取失败'));
    reader.readAsDataURL(file);
  });

  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight, source: image });
    image.onerror = () => reject(new Error('图片无法解码'));
    image.src = dataUrl;
  });
}

export function readAvatarPreferences() {
  try {
    return Object.fromEntries(Object.entries(AVATAR_KEYS).map(([role, key]) => {
      const value = localStorage.getItem(key);
      return [role, value?.startsWith('data:image/') ? value : ''];
    }));
  } catch {
    return { user: '', agent: '' };
  }
}

export function saveAvatarPreference(role, image) {
  const key = AVATAR_KEYS[role];
  if (!key) throw new Error('未知头像类型');
  localStorage.setItem(key, image);
}

export function removeAvatarPreference(role) {
  const key = AVATAR_KEYS[role];
  if (!key) throw new Error('未知头像类型');
  localStorage.removeItem(key);
}

export async function createAvatarImage(file) {
  if (!file?.type?.startsWith('image/')) throw new Error('请选择图片文件');
  if (file.size > MAX_UPLOAD_BYTES) throw new Error('图片不能超过 10 MB');

  let decodedImage;
  try {
    decodedImage = await decodeImageFile(file);
    if (!decodedImage.width || !decodedImage.height) throw new Error('图片尺寸无效');

    const cropSize = Math.min(decodedImage.width, decodedImage.height);
    const sourceX = (decodedImage.width - cropSize) / 2;
    const sourceY = (decodedImage.height - cropSize) / 2;
    const canvas = document.createElement('canvas');
    canvas.width = AVATAR_SIZE;
    canvas.height = AVATAR_SIZE;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法处理这张图片');
    context.drawImage(decodedImage.source || decodedImage, sourceX, sourceY, cropSize, cropSize, 0, 0, AVATAR_SIZE, AVATAR_SIZE);

    return canvas.toDataURL('image/webp', 0.86);
  } catch (error) {
    if (error instanceof Error && /图片|处理/.test(error.message)) throw error;
    throw new Error('图片读取失败，请换一张图片试试');
  } finally {
    decodedImage?.close?.();
  }
}
