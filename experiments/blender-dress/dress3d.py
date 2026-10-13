"""Proof of concept: put a flat-lay dress photo on a simple 3D dress, drape it
over stand-in shapes of the seated idol, render it with Blender and
composite it onto the bare idol photo.

    blender -b -P dress3d.py -- dress.jpg idol_bare.jpg out.png     (Blender 4.2 or newer)

Needs nothing but Blender (its own Python and numpy are used).

The flat-lay photo IS the fabric in its flat state: the skirt mesh starts as a
flat ring whose texture coordinates are the photo's pixels, then the cloth
simulation drapes it. Embroidery is never redrawn, only bent with the cloth.
All numbers for the idol and the photos live in setup.json next to this file.
"""
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
DRESS, IDOL, OUT = (argv + ["dress.jpg", "idol_bare.jpg", "out.png"][len(argv):])[:3]
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "setup.json"), encoding="utf-8"))
WORK = os.path.join(HERE, "work")
os.makedirs(WORK, exist_ok=True)

d = dict(CFG["dress_photo"])
side = os.path.splitext(DRESS)[0] + ".json"      # per-dress overrides, e.g. dresses/red.json
if os.path.exists(side):
    d.update(json.load(open(side, encoding="utf-8")))
s = CFG["scene"]


# ------------------------------------------------------------ image helpers
# Only Blender's own Python is needed (numpy ships with Blender), so nothing
# extra has to be installed. Arrays are float RGBA 0-1, row 0 = top of the image.
def load(path):
    img = bpy.data.images.load(os.path.abspath(path))
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[::-1].copy()


def save(arr, path, fmt="PNG"):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("out", w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(arr[::-1], dtype=np.float32).ravel())
    img.filepath_raw = os.path.abspath(path)
    img.file_format = fmt
    img.save()
    bpy.data.images.remove(img)


def box_blur(a, r):
    """Box blur of a 2-D array with radius r (fast, via running sums)."""
    if r < 1:
        return a
    out = a
    for axis in (0, 1):
        p = np.pad(out, [(r + 1, r) if k == axis else (0, 0) for k in range(2)], mode="edge")
        c = np.cumsum(p, axis=axis)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        out = (hi - lo) / (2 * r + 1)
    return out


def grow(mask, r):   # binary dilate (r>0) / erode (r<0)
    b = box_blur(mask.astype(np.float32), abs(r))
    return b > 0.001 if r > 0 else b > 0.999


def polygon_mask(h, w, poly):
    yy, xx = np.mgrid[0:h, 0:w]
    inside = np.zeros((h, w), bool)
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if y1 == y2:
            continue
        cross = ((yy >= min(y1, y2)) & (yy < max(y1, y2)) &
                 (xx < x1 + (yy - y1) * (x2 - x1) / (y2 - y1)))
        inside ^= cross
    return inside


# ------------------------------------------------------------ dress texture
def dress_texture(path):
    """RGBA texture: the dress photo with its plain background made transparent."""
    a = load(path)
    rgb = a[..., :3]
    edge = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                           rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    bg = np.median(edge, axis=0)
    fabric = np.abs(rgb - bg).sum(axis=2) > d.get("bg_threshold", 60) / 255
    fabric = grow(grow(fabric, 2), -2)      # close small holes
    fabric = grow(fabric, -2)               # pull the edge in: no dark rim
    alpha = np.clip(box_blur(fabric.astype(np.float32), 1), 0, 1)
    # under the transparent part, spread the fabric colour outwards (texture
    # filtering mixes in neighbouring pixels; they must be fabric, not background)
    filled = rgb.copy()
    known = fabric.copy()
    for r in (2, 4, 8, 16, 32, 64):
        k = known.astype(np.float32)
        den = box_blur(k, r)
        guess = np.stack([box_blur(filled[..., c] * k, r) for c in range(3)], -1) / np.maximum(den, 1e-6)[..., None]
        new = ~known & (den > 1e-4)
        filled[new] = guess[new]
        known |= new
    out = np.dstack([filled, alpha])
    p = os.path.join(WORK, "dress_rgba.png")
    save(out, p)
    ys, xs = np.nonzero(fabric)
    found = (float(xs.mean()), float(ys.mean()), float(np.sqrt(len(xs) / np.pi)))
    return p, (a.shape[1], a.shape[0]), found


def uv_of(px, py):
    return (px / DW, 1 - py / DH)


# ------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
idol = load(IDOL)
IH, IW = idol.shape[:2]
TEX, (DW, DH), (fx, fy, fr) = dress_texture(DRESS)
# centre and size of the round skirt: measured from the photo unless set in setup.json
CX, CY = d.get("skirt_centre") or (fx, fy)
RPX = d.get("skirt_radius_px") or fr
print(f"dress photo {DW}x{DH}: skirt centre ({CX:.0f}, {CY:.0f}), radius {RPX:.0f} px")
UNIT = RPX / s["skirt_radius"]          # dress-photo pixels per scene unit
scn = bpy.context.scene
scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = s.get("samples", 48)
scn.cycles.use_denoising = True
scn.render.resolution_x, scn.render.resolution_y = IW, IH
scn.render.film_transparent = True
scn.view_settings.view_transform = "Standard"
scn.frame_start, scn.frame_end = 1, s.get("frames", 70)

world = bpy.data.worlds.new("w")
scn.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1.0, 0.95, 0.88, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = s.get("ambient", 0.55)


def holdout_material():
    m = bpy.data.materials.new("holdout")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    h = nt.nodes.new("ShaderNodeHoldout")
    nt.links.new(h.outputs[0], out.inputs[0])
    return m


HOLD = holdout_material()


def proxy(obj, collide=True, friction=8.0, thickness=0.01):
    """Stand-in for a part of the idol: the cloth lands on it, the camera
    sees the real photo there (holdout)."""
    obj.data.materials.append(HOLD)
    if collide:
        obj.modifiers.new("col", "COLLISION")
        obj.collision.cloth_friction = friction
        obj.collision.thickness_outer = thickness
    return obj


# torso (an elliptic cylinder) and the crossed legs (a flattened ellipsoid)
t = s["torso"]
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=1, depth=t["top"] - t["bottom"],
                                    location=(0, t.get("y", 0), (t["top"] + t["bottom"]) / 2))
torso = bpy.context.object
torso.scale = (t["rx"], t["ry"], 1)
bpy.ops.object.transform_apply(scale=True)
proxy(torso)

for i, lp in enumerate(s["lap"]):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1, location=lp["centre"])
    lap = bpy.context.object
    lap.scale = lp["radii"]
    bpy.ops.object.transform_apply(scale=True)
    proxy(lap)

# floor: collision + shadow catcher
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
floor = bpy.context.object
floor.is_shadow_catcher = True
floor.modifiers.new("col", "COLLISION")
floor.collision.cloth_friction = 10


def dress_material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.blend_method = "HASHED" if hasattr(m, "blend_method") else None
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(TEX)
    tex.interpolation = "Cubic"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Roughness"].default_value = 0.8
    # matte cloth: no white sheen, little gloss, so the photo's colours come through
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.15
    # a little relief from the photo's brightness: embroidery and sequins catch light
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.002
    nt.links.new(tex.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


DRESS_MAT = dress_material("dress")

# ------------------------------------------------------------ skirt
# flat ring at waist height, texture = the dress photo (back of the skirt =
# top of the photo, front of the skirt = bottom of the photo)
sk = s["skirt_radius"]
r_in = s["waist_radius"]
rings, segs = s.get("rings", 34), s.get("segments", 128)
wz = s["waist_height"]
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
grid = []
for i in range(rings + 1):
    r = r_in + (sk * 1.04 - r_in) * i / rings   # a bit past the scallops; transparent there
    row = []
    for j in range(segs):
        a = 2 * math.pi * j / segs
        row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), wz)))
    grid.append(row)
pin_idx = []
for i in range(rings):
    for j in range(segs):
        f = bm.faces.new((grid[i][j], grid[i][(j + 1) % segs], grid[i + 1][(j + 1) % segs], grid[i + 1][j]))
        for loop in f.loops:
            x, y, _ = loop.vert.co
            # +y in the scene = away from the camera = up in the photo
            loop[uvl].uv = uv_of(CX + x * UNIT, CY - y * UNIT)
me = bpy.data.meshes.new("skirt")
bm.to_mesh(me)
bm.free()
skirt = bpy.data.objects.new("skirt", me)
scn.collection.objects.link(skirt)
skirt.data.materials.append(DRESS_MAT)
for p in skirt.data.polygons:
    p.use_smooth = True
vg = skirt.vertex_groups.new(name="pin")
vg.add(list(range(segs)), 1.0, "REPLACE")          # the waist ring stays put
cloth = skirt.modifiers.new("cloth", "CLOTH")
cs = cloth.settings
cs.quality = 8
cs.mass = 0.15
cs.tension_stiffness = cs.compression_stiffness = 15
cs.shear_stiffness = 5
cs.bending_stiffness = s.get("bending", 0.08)
cs.air_damping = 1.5
cs.vertex_group_mass = "pin"
cloth.collision_settings.distance_min = 0.006
cloth.collision_settings.use_self_collision = True
cloth.collision_settings.self_distance_min = 0.004
cloth.point_cache.frame_end = scn.frame_end
skirt.modifiers.new("thick", "SOLIDIFY").thickness = 0.002
skirt.modifiers.new("smooth", "SUBSURF").levels = 1

# ------------------------------------------------------------ bodice
# the front of the bodice photo wrapped round the front of the torso
b = s["bodice"]
x0, y0, x1, y1 = d["bodice_box"]
bw_units = (x1 - x0) / UNIT
bh_units = (y1 - y0) / UNIT
rb = b["radius"]
arc = bw_units / rb                       # angle the bodice front covers
bm = bmesh.new()
uvl = bm.loops.layers.uv.new("UVMap")
nu, nv = 48, 24
vs = []
for i in range(nv + 1):
    z = b["bottom"] + bh_units * i / nv
    row = []
    for j in range(nu + 1):
        a = -math.pi / 2 - arc / 2 + arc * j / nu   # centred on the front (-y)
        taper = 1 + b.get("flare", 0.08) * (1 - i / nv)
        row.append(bm.verts.new((rb * taper * math.cos(a), b.get("y", 0) + rb * b.get("depth", 0.85) * taper * math.sin(a), z)))
    vs.append(row)
for i in range(nv):
    for j in range(nu):
        f = bm.faces.new((vs[i][j], vs[i][j + 1], vs[i + 1][j + 1], vs[i + 1][j]))
        for loop in f.loops:
            # recover grid position from the vertex
            vi = next(k for k in range(nv + 1) if loop.vert in vs[k])
            vj = vs[vi].index(loop.vert)
            loop[uvl].uv = uv_of(x0 + (x1 - x0) * vj / nu, y1 - (y1 - y0) * vi / nv)
me = bpy.data.meshes.new("bodice")
bm.to_mesh(me)
bm.free()
bodice = bpy.data.objects.new("bodice", me)
scn.collection.objects.link(bodice)
bodice.data.materials.append(DRESS_MAT)
for p in bodice.data.polygons:
    p.use_smooth = True
bodice.modifiers.new("smooth", "SUBSURF").levels = 1

# ------------------------------------------------------------ light + camera
lt = bpy.data.lights.new("key", "AREA")
lt.energy = s.get("light", 900)
lt.size = 4
lt.color = (1.0, 0.93, 0.82)
key = bpy.data.objects.new("key", lt)
key.location = (-2.5, -3.5, 4.5)
key.rotation_euler = (math.radians(45), 0, math.radians(-35))
scn.collection.objects.link(key)

c = s["camera"]
cam_d = bpy.data.cameras.new("cam")
cam_d.type = "ORTHO"
cam_d.ortho_scale = IW / c["px_per_unit"] if IW >= IH else IH / c["px_per_unit"]
cam = bpy.data.objects.new("cam", cam_d)
scn.collection.objects.link(cam)
scn.camera = cam
th = math.radians(c["tilt_deg"])
dvec = np.array([0, math.cos(th), -math.sin(th)])
up = np.array([0, math.sin(th), math.cos(th)])
# put the anchor point (waist centre) at its pixel in the idol photo
ax, ay = c["anchor_px"]
anchor = np.array([0, 0, wz])
centre = anchor + up * ((ay - IH / 2) / c["px_per_unit"]) - np.array([1, 0, 0]) * ((ax - IW / 2) / c["px_per_unit"])
cam.location = tuple(centre - dvec * 20)
cam.rotation_euler = (math.radians(90 - c["tilt_deg"]), 0, 0)
cam_d.clip_end = 100

# ------------------------------------------------------------ simulate + render
for f in range(1, scn.frame_end + 1):
    scn.frame_set(f)
scn.render.filepath = os.path.join(WORK, "dress_render.png")
bpy.ops.render.render(write_still=True)

# ------------------------------------------------------------ composite
ren = load(scn.render.filepath)
a = ren[..., 3:4]
out = idol[..., :3] * (1 - a) + ren[..., :3] * a
# the idol's arms, hands, ball and necklace go back on top
keep = np.zeros((IH, IW), np.float32)
for poly in CFG["keep_on_top"]:
    keep = np.maximum(keep, polygon_mask(IH, IW, poly).astype(np.float32))
keep = box_blur(keep, 1)[..., None]
out = out * (1 - keep) + idol[..., :3] * keep
save(np.dstack([out, np.ones((IH, IW), np.float32)]), OUT)
print("saved", OUT)
