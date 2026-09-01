# Noise Wiggler

A comprehensive, artist-friendly Blender 5.2+ extension that brings procedural noise motion and seamless loops to both **Objects (Delta Transforms)** and **Armatures (Pose Bone Chains)** with multi-object editing, hierarchy falloff curves, spatial wave offsets, restricted frame ranges, motion presets, and full Slotted Action compatibility.

---

## Features

### 1. Two Powerful Modes with Harmonized Controls
- **Bone Wiggle Mode (Armatures)**:
  - Animate entire bone hierarchies or deform-only bones.
  - **Hierarchy Falloff**: Counteracts compounding FK rotations with smooth hyperbolic decay or visual **Curve UI** mapping (`template_curve_mapping`).
  - **Motion Presets**: 1-click presets (*Gentle Breeze*, *Strong Wind*, *Tail / Tentacle Flow*, *Subtle Idle*, *Fast Jiggle*).
  - **Traveling Wave Lag**: Natural sinusoidal phase propagation down bone chains.
  - **Restricted Frame Range**: Clamp bone noise to custom frame boundaries with smooth **Blend In** and **Blend Out** transitions.
- **Object Wiggle Mode (All Objects)**:
  - Procedural noise on Object **Delta Rotation** and **Delta Location**.
  - **Restricted Frame Range**: Smooth blend-in / blend-out transitions.
  - Multi-object editing across meshes, empties, lights, cameras, and armatures.

### 2. Zero Conflict & Dual Wiggle
- An Armature can simultaneously have **Object Wiggle** (swaying root/delta transform) AND **Bone Wiggle** (rustling branches/individual bones) without modifier collision.
- Distinct modifier prefixes (`Wiggle Object ...` and `Wiggle Bone ...`) guarantee independent clearing and editing.

### 3. Shared Spatial Variation Engine
- **Per-Object / Per-Bone Random**: Deterministic seed & hash offsets.
- **Directional Wave (Linear)**: Waves propagating along World or Guide X, Y, or Z axes.
- **Radial Ripple**: Expanding concentric ripple radiating outward from origin or a designated Guide Empty/Object.

### 4. Seamless Looping Engine (No NLA Required)
- Mathematically perfect circular periodic noise evaluated across custom frame ranges.
- Automatic `CYCLES` modifier repetition for infinite seamless loops (ideal for games and looping animations).

### 5. Smart Multi-Object Editing & Mixed Selection
- Select mixed hierarchies (Armatures + Skinned Meshes + Empties):
  - Object Wiggle targets all selected objects.
  - Bone Wiggle cleanly isolates Armatures and ignores non-armatures.
- Adjusting sliders on the active object dynamically updates all selected objects.

---

## Installation

### As an Extension (Blender 4.2 / 5.2+)
1. Download or build `noise_wiggler-0.1.2.zip` from the `dist/` folder.
2. In Blender, go to **Edit > Preferences > Get Extensions**.
3. Click the top-right menu and select **Install from Disk...**.
4. Select the `.zip` file.

---

## Usage

1. Select any object or armature in the 3D Viewport.
2. Press **N** to open the sidebar and navigate to the **Noise Wiggler** tab.
3. If an Armature is selected, choose between **Bone Wiggle** or **Object Wiggle** at the top.
4. Click **Wiggle it!** to apply procedural noise.
5. Tweak **Strength**, **Speed**, **Spatial Offsets**, **Restrict Frame Range**, or **Hierarchy Falloff** in real time.
6. When ready for export, use **Bake Keyframes**.

---

## License

GNU General Public License v3.0 or later.
