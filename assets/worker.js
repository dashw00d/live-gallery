// Renders 3D thumbnails off the page's main thread, so parsing a big model never freezes the page.
import { thumbKit, drawThumb } from './kit.js';
let kit = null;
self.onmessage = async e => {
  const { url, ext, size } = e.data;
  if (!kit) {
    try { kit = await thumbKit(new OffscreenCanvas(size, size), size); }
    catch (err) { postMessage({ error: String(err?.message || err), fatal: true }); return; }
  }
  try {
    await drawThumb(kit, url, ext);
    postMessage({ blob: await kit.r.domElement.convertToBlob({ type: 'image/webp', quality: 0.9 }) });
  } catch (err) {
    const error = String(err?.message || err);  // `dom`: this loader needs the page (it touched document/Image)
    postMessage({ error, dom: /document|window|Image|createElement/.test(error) });
  }
};
