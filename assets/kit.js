// 3D helpers shared by the page and the thumbnail worker.
// three.js comes from the CDN on first use, so images work offline. The "+esm" builds
// need no import map, which is what lets the same code run inside a worker.
const CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/';
const X = p => CDN + 'examples/jsm/' + p + '/+esm';
let T;
export async function three() {
  if (T) return T;
  const [THREE, { GLTFLoader }, { DRACOLoader }, { MeshoptDecoder }, { OBJLoader }, { STLLoader }, { PLYLoader }, { FBXLoader }, { RoomEnvironment }] = await Promise.all([
    import(CDN + '+esm'), import(X('loaders/GLTFLoader.js')), import(X('loaders/DRACOLoader.js')),
    import(X('libs/meshopt_decoder.module.js')), import(X('loaders/OBJLoader.js')), import(X('loaders/STLLoader.js')),
    import(X('loaders/PLYLoader.js')), import(X('loaders/FBXLoader.js')), import(X('environments/RoomEnvironment.js'))]);
  const draco = new DRACOLoader(); draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
  const gltf = new GLTFLoader(); gltf.setDRACOLoader(draco); gltf.setMeshoptDecoder(MeshoptDecoder);
  T = { THREE, RoomEnvironment, L: { gltf, glb: gltf, obj: new OBJLoader(), stl: new STLLoader(), ply: new PLYLoader(), fbx: new FBXLoader() } };
  return T;
}
export async function orbit() { return (await import(X('controls/OrbitControls.js'))).OrbitControls; }

export async function loadModel(url, ext, onProgress) {
  const obj = await readModel(url, ext, onProgress);
  // Tone the room light down so pale, untextured models keep their surface detail instead of clipping to white.
  obj.traverse(o => { for (const m of [].concat(o.material || [])) if ('envMapIntensity' in m) m.envMapIntensity = 0.45; });
  return obj;
}
async function readModel(url, ext, onProgress) {
  const { THREE, L } = await three();
  if (ext === 'glb' || ext === 'gltf') return (await L.gltf.loadAsync(url, onProgress)).scene;
  if (ext === 'obj' || ext === 'fbx') return await L[ext].loadAsync(url, onProgress);
  const geo = await L[ext].loadAsync(url, onProgress), colored = !!geo.attributes.color;
  if (ext === 'ply' && !geo.index) {  // point cloud
    geo.computeBoundingSphere();
    return new THREE.Points(geo, new THREE.PointsMaterial({ size: geo.boundingSphere.radius / 200, vertexColors: colored, color: colored ? 0xffffff : 0xb8c0cc }));
  }
  if (!geo.attributes.normal) geo.computeVertexNormals();
  return new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: colored ? 0xffffff : 0xb8c0cc, vertexColors: colored, roughness: .55, metalness: .1 }));
}
export function stage(renderer) {
  const { THREE, RoomEnvironment } = T, scene = new THREE.Scene(), pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture; pm.dispose();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 0.15));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(3, 5, 4); scene.add(d);
  return scene;
}
export function frame(cam, obj, ctl) {
  const { THREE } = T, box = new THREE.Box3().setFromObject(obj); if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2 || 1;
  const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2));
  cam.position.copy(c).addScaledVector(new THREE.Vector3(1, .7, 1.2).normalize(), dist * 1.02);
  cam.near = dist / 100; cam.far = dist * 100; cam.updateProjectionMatrix(); cam.lookAt(c);
  if (ctl) { ctl.target.copy(c); ctl.update(); }
}
export function dispose(obj) {
  obj.traverse(o => {
    o.geometry?.dispose();
    for (const m of [].concat(o.material || [])) { for (const k in m) if (m[k]?.isTexture) m[k].dispose(); m.dispose(); }
  });
}

// Thumbnails: one renderer reused for every model. `canvas` is a <canvas> or an OffscreenCanvas.
export async function thumbKit(canvas, size) {
  const { THREE } = await three();
  const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  r.setSize(size, size, false);
  return { r, scene: stage(r), cam: new THREE.PerspectiveCamera(35, 1, .01, 1000) };
}
export async function drawThumb(kit, url, ext) {
  const obj = await loadModel(url, ext);
  try { kit.scene.add(obj); frame(kit.cam, obj); kit.r.render(kit.scene, kit.cam); }
  finally { kit.scene.remove(obj); dispose(obj); }
}
