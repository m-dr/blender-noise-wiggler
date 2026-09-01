import bpy
import bpy_extras.anim_utils
import math
import random
from mathutils import Vector, noise
from bpy.app.handlers import persistent

bl_info = {
    "name": "Noise Wiggler",
    "author": "m-dr",
    "version": (0, 1, 2),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Noise Wiggler",
    "description": "Unified procedural noise animation for objects and armatures with spatial wave offsets, hierarchy curves, and seamless looping",
    "category": "Animation",
}

# Modifier identifiers
WIGGLE_OBJ_ROTATION_MOD = "Wiggle Object Rotation"
WIGGLE_OBJ_LOCATION_MOD = "Wiggle Object Location"
WIGGLE_OBJ_CYCLES_MOD = "Wiggle Object Loop Cycles"
WIGGLE_OBJ_PREFIX = "Wiggle Object"

WIGGLE_BONE_ROTATION_MOD = "Wiggle Bone Rotation"
WIGGLE_BONE_CYCLES_MOD = "Wiggle Bone Loop Cycles"
WIGGLE_BONE_PREFIX = "Wiggle Bone"

WIGGLE_CURVE_NODETREE = ".noise_wiggler_curves"

_is_syncing_props = False
_is_updating_props = False
_last_active_object = None


# ==============================================================================
# Presets Definition (Bone Mode)
# ==============================================================================

BONE_PRESETS = {
    'GENTLE_BREEZE': {
        'label': "Gentle Breeze (Foliage / Hair)",
        'description': "Subtle, smooth motion with tips dampened to avoid whipping",
        'strength': 0.06,
        'speed': 50.0,
        'chain_wave': 45.0,
        'randomness': 0.4,
        'falloff_enable': True,
        'falloff_amount': 0.35,
        'invert_falloff': False,
        'falloff_control_type': 'SLIDER',
        'offset_mode': 'RANDOM',
    },
    'STRONG_WIND': {
        'label': "Strong Wind (Trees / Flags)",
        'description': "Dynamic gusts with tips whipped by wind forces",
        'strength': 0.16,
        'speed': 28.0,
        'chain_wave': 60.0,
        'randomness': 0.7,
        'falloff_enable': True,
        'falloff_amount': 0.20,
        'invert_falloff': True,
        'falloff_control_type': 'SLIDER',
        'offset_mode': 'RANDOM',
    },
    'TAIL_TENTACLE': {
        'label': "Tail / Tentacle Flow",
        'description': "Harmonic wave lag undulating down the bone chain",
        'strength': 0.10,
        'speed': 40.0,
        'chain_wave': 80.0,
        'randomness': 0.15,
        'falloff_enable': False,
        'falloff_amount': 0.0,
        'invert_falloff': False,
        'falloff_control_type': 'SLIDER',
        'offset_mode': 'RANDOM',
    },
    'IDLE_BREATHE': {
        'label': "Subtle Idle / Breathing",
        'description': "Slow, synchronized breathing and resting posture shifts",
        'strength': 0.03,
        'speed': 70.0,
        'chain_wave': 20.0,
        'randomness': 0.15,
        'falloff_enable': True,
        'falloff_amount': 0.50,
        'invert_falloff': False,
        'falloff_control_type': 'SLIDER',
        'offset_mode': 'RANDOM',
    },
    'JIGGLE': {
        'label': "Fast Jiggle / Twitch",
        'description': "Rapid jitter and independent bone shake",
        'strength': 0.04,
        'speed': 14.0,
        'chain_wave': 15.0,
        'randomness': 0.90,
        'falloff_enable': False,
        'falloff_amount': 0.0,
        'invert_falloff': False,
        'falloff_control_type': 'SLIDER',
        'offset_mode': 'RANDOM',
    },
}


# ==============================================================================
# Slotted Actions & Animation Utilities
# ==============================================================================

def get_object_fcurves(ob, create_if_missing=False):
    """
    Retrieves fcurves from an object's action/channelbag.
    Compatible with Blender 5.2+ Slotted Actions and legacy actions.
    """
    if not ob:
        return []

    anim_data = ob.animation_data
    if not anim_data:
        if create_if_missing:
            anim_data = ob.animation_data_create()
        else:
            return []

    if create_if_missing and not anim_data.action:
        act = bpy.data.actions.new(name=f"{ob.name}_WiggleAction")
        anim_data.action = act
        if hasattr(bpy_extras, "anim_utils") and hasattr(bpy_extras.anim_utils, "animdata_ensure_slot"):
            try:
                bpy_extras.anim_utils.animdata_ensure_slot(anim_data)
            except Exception:
                pass

    if hasattr(bpy_extras, "anim_utils"):
        try:
            channelbag = bpy_extras.anim_utils.animdata_get_channelbag_for_assigned_slot(anim_data)
            if channelbag and hasattr(channelbag, "fcurves"):
                return channelbag.fcurves
        except Exception:
            pass

        if anim_data.action and hasattr(anim_data, "action_slot") and anim_data.action_slot:
            try:
                channelbag = bpy_extras.anim_utils.action_get_channelbag_for_slot(anim_data.action, anim_data.action_slot)
                if channelbag and hasattr(channelbag, "fcurves"):
                    return channelbag.fcurves
            except Exception:
                pass

    if anim_data.action and hasattr(anim_data.action, "fcurves"):
        return anim_data.action.fcurves

    return []


def ensure_object_fcurve(ob, data_path, index, frame=1):
    """
    Ensures an fcurve exists on an object for delta transforms with at least 1 keyframe.
    """
    if not ob.animation_data:
        ob.animation_data_create()

    fcurves = get_object_fcurves(ob, create_if_missing=True)
    target_fc = None
    for fc in fcurves:
        if fc.data_path == data_path and fc.array_index == index:
            target_fc = fc
            break

    if target_fc is None or len(target_fc.keyframe_points) == 0:
        try:
            ob.keyframe_insert(data_path=data_path, index=index, frame=frame)
        except Exception:
            pass
        fcurves = get_object_fcurves(ob, create_if_missing=True)
        for fc in fcurves:
            if fc.data_path == data_path and fc.array_index == index:
                target_fc = fc
                break

    return target_fc


def ensure_bone_fcurve(arm_ob, bone, transform_prop="rotation_euler", index=0, frame=1):
    """
    Ensures an fcurve exists for the target pose bone transform with at least 1 keyframe.
    """
    if not arm_ob.animation_data:
        arm_ob.animation_data_create()

    data_path = bone.path_from_id(transform_prop)
    fcurves = get_object_fcurves(arm_ob, create_if_missing=True)

    target_fc = None
    for fc in fcurves:
        if fc.data_path == data_path and fc.array_index == index:
            target_fc = fc
            break

    if target_fc is None or len(target_fc.keyframe_points) == 0:
        try:
            bone.keyframe_insert(data_path=transform_prop, index=index, frame=frame)
        except Exception:
            try:
                arm_ob.keyframe_insert(data_path=data_path, index=index, frame=frame)
            except Exception:
                pass

        fcurves = get_object_fcurves(arm_ob, create_if_missing=True)
        for fc in fcurves:
            if fc.data_path == data_path and fc.array_index == index:
                target_fc = fc
                break

    return target_fc


def find_modifier(fcu, name_prefix):
    if not fcu:
        return None
    for mod in fcu.modifiers:
        if mod.name.startswith(name_prefix):
            return mod
    return None


def has_object_wiggle(ob):
    """Checks if an object has active Object Wiggle modifiers or delta keyframes"""
    fcurves = get_object_fcurves(ob)
    for fc in fcurves:
        if fc.data_path in ("delta_rotation_euler", "delta_location"):
            if find_modifier(fc, WIGGLE_OBJ_PREFIX) or find_modifier(fc, "Wiggle") or len(fc.keyframe_points) > 1:
                return True
    return False


def has_bone_wiggle(arm_ob):
    """Checks if an armature has active Bone Wiggle modifiers on pose bones"""
    if not arm_ob or arm_ob.type != 'ARMATURE':
        return False
    fcurves = get_object_fcurves(arm_ob)
    for fc in fcurves:
        if fc.data_path.startswith("pose.bones["):
            if find_modifier(fc, WIGGLE_BONE_PREFIX) or any(m.name == WIGGLE_BONE_CYCLES_MOD for m in fc.modifiers) or len(fc.keyframe_points) > 1:
                return True
    return False


def get_target_bones(arm_ob, filter_mode='ALL'):
    if not arm_ob or arm_ob.type != 'ARMATURE' or not arm_ob.pose:
        return []
    if filter_mode == 'DEFORM':
        return [b for b in arm_ob.pose.bones if b.bone.use_deform]
    else:
        return list(arm_ob.pose.bones)


def get_bone_hierarchy_depth(bone):
    depth = 0
    p = bone.parent
    while p:
        depth += 1
        p = p.parent
    return depth


# ==============================================================================
# Curve Mapping Utilities
# ==============================================================================

def get_or_create_falloff_curve_node(arm_ob):
    if not arm_ob:
        return None
    tree_name = f"{WIGGLE_CURVE_NODETREE}_{arm_ob.name}"
    tree = bpy.data.node_groups.get(tree_name)
    if not tree:
        tree = bpy.data.node_groups.new(tree_name, 'ShaderNodeTree')
        tree.use_fake_user = True

    node = tree.nodes.get("FalloffCurve")
    if not node:
        node = tree.nodes.new("ShaderNodeFloatCurve")
        node.name = "FalloffCurve"
        cm = node.mapping
        if len(cm.curves) > 0 and len(cm.curves[0].points) >= 2:
            cm.curves[0].points[0].location = (0.0, 1.0)
            cm.curves[0].points[1].location = (1.0, 0.25)
            cm.update()
    return node


# ==============================================================================
# Calculation Engines: Spatial Offsets, Decay, and Circular Looping
# ==============================================================================

def calculate_object_spatial_offset(ob, props):
    seed_base = props.seed * 1000.0

    if props.offset_mode == 'RANDOM':
        obj_hash = (abs(hash(ob.name)) % 100000) * 13.37
        return seed_base + (obj_hash if props.use_unique_seed else 0.0)

    world_pos = ob.matrix_world.translation - Vector(ob.delta_location)
    guide = props.guide_object

    if props.offset_mode == 'LINEAR':
        if guide and guide != ob:
            try:
                rel_pos = guide.matrix_world.inverted_safe() @ world_pos
            except Exception:
                rel_pos = world_pos - guide.matrix_world.translation
        else:
            rel_pos = world_pos

        axis = props.offset_axis.lower()
        axis_coord = getattr(rel_pos, axis, 0.0)
        return seed_base + (axis_coord * props.spatial_scale)

    if props.offset_mode == 'RADIAL':
        if guide and guide != ob:
            origin = guide.matrix_world.translation
        else:
            origin = Vector((0.0, 0.0, 0.0))
        dist = (world_pos - origin).length
        return seed_base + (dist * props.spatial_scale)

    return seed_base


def calculate_bone_spatial_offset(arm_ob, bone, props):
    seed_base = props.seed * 1000.0

    if props.offset_mode == 'RANDOM':
        bone_hash = (abs(hash(f"{arm_ob.name}_{bone.name}")) % 100000) * 13.37
        return seed_base + (bone_hash * props.randomness)

    world_pos = arm_ob.matrix_world @ bone.head
    guide = props.guide_object

    if props.offset_mode == 'LINEAR':
        if guide and guide != arm_ob:
            try:
                rel_pos = guide.matrix_world.inverted_safe() @ world_pos
            except Exception:
                rel_pos = world_pos - guide.matrix_world.translation
        else:
            rel_pos = world_pos

        axis = props.offset_axis.lower()
        axis_coord = getattr(rel_pos, axis, 0.0)
        return seed_base + (axis_coord * props.spatial_scale)

    if props.offset_mode == 'RADIAL':
        if guide and guide != arm_ob:
            origin = guide.matrix_world.translation
        else:
            origin = Vector((0.0, 0.0, 0.0))
        dist = (world_pos - origin).length
        return seed_base + (dist * props.spatial_scale)

    return seed_base


def calculate_bone_hierarchy_multiplier(depth, max_depth, props, arm_ob):
    if not props.falloff_enable or max_depth <= 0:
        return 1.0

    if props.falloff_control_type == 'CURVE':
        node = get_or_create_falloff_curve_node(arm_ob)
        if node and len(node.mapping.curves) > 0:
            norm_pos = min(max(depth / max_depth, 0.0), 1.0)
            curve = node.mapping.curves[0]
            val = node.mapping.evaluate(curve, norm_pos)
            return max(float(val), 0.0)

    if depth == 0:
        return 1.0

    rate = props.falloff_amount
    if props.invert_falloff:
        return 1.0 + (rate * depth * 0.8)
    else:
        return 1.0 / (1.0 + (rate * depth * 1.5))


def evaluate_circular_noise(frame, f_start, f_end, speed, strength, seed_z, phase_offset=0.0):
    length = max(f_end - f_start, 1.0)
    angle = 2.0 * math.pi * (frame - f_start) / length + (phase_offset * 0.02)
    freq = max(50.0 / max(speed, 0.001), 0.1)
    nx = math.cos(angle) * freq
    ny = math.sin(angle) * freq
    nz = seed_z * 0.01
    val = noise.turbulence_vector(Vector((nx, ny, nz)), 3, False).x
    return val * strength


# ==============================================================================
# Object Mode: Core Apply & Remove (Delta Transforms)
# ==============================================================================

def apply_object_wiggle(ob, props=None):
    if not ob:
        return
    if props is None:
        props = ob.noise_wiggler_obj_props

    spatial_offset = calculate_object_spatial_offset(ob, props)

    if props.enable_loop:
        f_start = int(props.loop_start)
        f_end = int(props.loop_end)
        if f_end <= f_start:
            f_end = f_start + 1
        count = f_end - f_start + 1

        # Rotation Loop
        if props.enable_rotation:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_rotation_euler", idx, frame=f_start)
                if not fc:
                    continue
                for m in list(fc.modifiers):
                    if (m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle")) and m.type == 'NOISE':
                        fc.modifiers.remove(m)

                fc.keyframe_points.clear()
                fc.keyframe_points.add(count)
                seed_z = (props.seed * 1000.0) + spatial_offset + (idx * 1731.5)
                eff_strength = props.rot_strength * props.rot_influence

                for i, f in enumerate(range(f_start, f_end + 1)):
                    v = evaluate_circular_noise(f, f_start, f_end, props.rot_speed, eff_strength, seed_z, props.rot_phase)
                    kp = fc.keyframe_points[i]
                    kp.co = (f, v)
                    kp.handle_left_type = 'AUTO'
                    kp.handle_right_type = 'AUTO'
                fc.update()

                if props.loop_repeat:
                    cyc = next((m for m in fc.modifiers if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD), None)
                    if not cyc:
                        cyc = fc.modifiers.new(type='CYCLES')
                        cyc.name = WIGGLE_OBJ_CYCLES_MOD
                    cyc.mode_before = 'REPEAT'
                    cyc.mode_after = 'REPEAT'
                else:
                    for m in list(fc.modifiers):
                        if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD:
                            fc.modifiers.remove(m)
        else:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_rotation_euler", idx)
                if fc:
                    for m in list(fc.modifiers):
                        if m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle"):
                            fc.modifiers.remove(m)
                    if len(fc.keyframe_points) > 1:
                        fc.keyframe_points.clear()
                        fc.keyframe_points.add(1)
                        fc.keyframe_points[0].co = (1.0, 0.0)

        # Location Loop
        if props.enable_location:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_location", idx, frame=f_start)
                if not fc:
                    continue
                for m in list(fc.modifiers):
                    if (m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle")) and m.type == 'NOISE':
                        fc.modifiers.remove(m)

                fc.keyframe_points.clear()
                fc.keyframe_points.add(count)
                seed_z = (props.seed * 1000.0) + spatial_offset + 50000.0 + (idx * 1731.5)
                eff_strength = props.loc_strength * props.loc_influence

                for i, f in enumerate(range(f_start, f_end + 1)):
                    v = evaluate_circular_noise(f, f_start, f_end, props.loc_speed, eff_strength, seed_z, props.loc_phase)
                    kp = fc.keyframe_points[i]
                    kp.co = (f, v)
                    kp.handle_left_type = 'AUTO'
                    kp.handle_right_type = 'AUTO'
                fc.update()

                if props.loop_repeat:
                    cyc = next((m for m in fc.modifiers if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD), None)
                    if not cyc:
                        cyc = fc.modifiers.new(type='CYCLES')
                        cyc.name = WIGGLE_OBJ_CYCLES_MOD
                    cyc.mode_before = 'REPEAT'
                    cyc.mode_after = 'REPEAT'
                else:
                    for m in list(fc.modifiers):
                        if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD:
                            fc.modifiers.remove(m)
        else:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_location", idx)
                if fc:
                    for m in list(fc.modifiers):
                        if m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle"):
                            fc.modifiers.remove(m)
                    if len(fc.keyframe_points) > 1:
                        fc.keyframe_points.clear()
                        fc.keyframe_points.add(1)
                        fc.keyframe_points[0].co = (1.0, 0.0)
    else:
        # --- Procedural Noise Modifier Mode ---
        if props.enable_rotation:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_rotation_euler", idx)
                if not fc:
                    continue
                for m in list(fc.modifiers):
                    if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD:
                        fc.modifiers.remove(m)
                if len(fc.keyframe_points) > 1:
                    fc.keyframe_points.clear()
                    fc.keyframe_points.add(1)
                    fc.keyframe_points[0].co = (1.0, 0.0)

                mod = find_modifier(fc, WIGGLE_OBJ_ROTATION_MOD) or find_modifier(fc, WIGGLE_OBJ_PREFIX) or find_modifier(fc, "Wiggle Rotation")
                if mod is None:
                    mod = fc.modifiers.new(type='NOISE')
                    mod.name = WIGGLE_OBJ_ROTATION_MOD

                mod.scale = max(props.rot_speed, 0.001)
                mod.strength = props.rot_strength
                mod.phase = props.rot_phase + spatial_offset + (idx * 1731.5)
                mod.use_influence = True
                mod.influence = props.rot_influence
                mod.use_restricted_range = props.use_restricted_range
                if props.use_restricted_range:
                    mod.frame_start = props.frame_start
                    mod.frame_end = props.frame_end
                    mod.blend_in = max(props.blend_in, 0.0)
                    mod.blend_out = max(props.blend_out, 0.0)
        else:
            fcurves = get_object_fcurves(ob)
            for fc in fcurves:
                if fc.data_path == "delta_rotation_euler":
                    for m in list(fc.modifiers):
                        if m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle"):
                            fc.modifiers.remove(m)

        if props.enable_location:
            for idx in range(3):
                fc = ensure_object_fcurve(ob, "delta_location", idx)
                if not fc:
                    continue
                for m in list(fc.modifiers):
                    if m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD:
                        fc.modifiers.remove(m)
                if len(fc.keyframe_points) > 1:
                    fc.keyframe_points.clear()
                    fc.keyframe_points.add(1)
                    fc.keyframe_points[0].co = (1.0, 0.0)

                mod = find_modifier(fc, WIGGLE_OBJ_LOCATION_MOD) or find_modifier(fc, WIGGLE_OBJ_PREFIX) or find_modifier(fc, "Wiggle Location")
                if mod is None:
                    mod = fc.modifiers.new(type='NOISE')
                    mod.name = WIGGLE_OBJ_LOCATION_MOD

                mod.scale = max(props.loc_speed, 0.001)
                mod.strength = props.loc_strength
                mod.phase = props.loc_phase + spatial_offset + 50000.0 + (idx * 1731.5)
                mod.use_influence = True
                mod.influence = props.loc_influence
                mod.use_restricted_range = props.use_restricted_range
                if props.use_restricted_range:
                    mod.frame_start = props.frame_start
                    mod.frame_end = props.frame_end
                    mod.blend_in = max(props.blend_in, 0.0)
                    mod.blend_out = max(props.blend_out, 0.0)
        else:
            fcurves = get_object_fcurves(ob)
            for fc in fcurves:
                if fc.data_path == "delta_location":
                    for m in list(fc.modifiers):
                        if m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle"):
                            fc.modifiers.remove(m)

    ob.update_tag()


def remove_object_wiggle(ob):
    if not ob:
        return
    fcurves = get_object_fcurves(ob)
    if not fcurves:
        ob.delta_rotation_euler = (0.0, 0.0, 0.0)
        ob.delta_location = (0.0, 0.0, 0.0)
        ob.update_tag()
        return

    to_remove_fcurves = []
    for fc in list(fcurves):
        if fc.data_path in ("delta_rotation_euler", "delta_location"):
            wiggle_mods = [m for m in fc.modifiers if m.name.startswith(WIGGLE_OBJ_PREFIX) or m.name.startswith("Wiggle")]
            for m in wiggle_mods:
                fc.modifiers.remove(m)
            if len(fc.modifiers) == 0:
                to_remove_fcurves.append(fc)

    if to_remove_fcurves:
        anim_data = ob.animation_data
        cb = None
        if hasattr(bpy_extras, "anim_utils"):
            cb = bpy_extras.anim_utils.animdata_get_channelbag_for_assigned_slot(anim_data)
        if cb:
            for fc in to_remove_fcurves:
                try:
                    cb.fcurves.remove(fc)
                except Exception:
                    pass
        elif anim_data and anim_data.action:
            for fc in to_remove_fcurves:
                try:
                    anim_data.action.fcurves.remove(fc)
                except Exception:
                    pass

    ob.delta_rotation_euler = (0.0, 0.0, 0.0)
    ob.delta_location = (0.0, 0.0, 0.0)
    ob.update_tag()


# ==============================================================================
# Bone Mode: Core Apply & Remove (Pose Bones)
# ==============================================================================

def apply_bone_wiggle(arm_ob, props=None):
    if not arm_ob or arm_ob.type != 'ARMATURE':
        return
    if props is None:
        props = arm_ob.noise_wiggler_bone_props

    target_bones = get_target_bones(arm_ob, props.bone_filter)
    if not target_bones:
        return

    max_depth = max((get_bone_hierarchy_depth(b) for b in target_bones), default=1) or 1

    if props.enable_loop:
        f_start = int(props.loop_start)
        f_end = int(props.loop_end)
        if f_end <= f_start:
            f_end = f_start + 1
        count = f_end - f_start + 1

        for idx, bone in enumerate(target_bones):
            if bone.rotation_mode not in {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}:
                bone.rotation_mode = 'XYZ'

            depth = get_bone_hierarchy_depth(bone)
            hier_mult = calculate_bone_hierarchy_multiplier(depth, max_depth, props, arm_ob)
            spatial_off = calculate_bone_spatial_offset(arm_ob, bone, props)
            phase_offset = spatial_off + (depth * props.chain_wave) + (idx * props.chain_wave * 0.5)
            eff_strength = props.strength * hier_mult

            for axis_i in range(3):
                fc = ensure_bone_fcurve(arm_ob, bone, "rotation_euler", axis_i, frame=f_start)
                if not fc:
                    continue

                for m in list(fc.modifiers):
                    if m.name.startswith(WIGGLE_BONE_PREFIX) and m.type == 'NOISE':
                        fc.modifiers.remove(m)

                fc.keyframe_points.clear()
                fc.keyframe_points.add(count)
                seed_z = (props.seed * 1000.0) + phase_offset + (axis_i * 1731.5)

                for k_i, f in enumerate(range(f_start, f_end + 1)):
                    v = evaluate_circular_noise(f, f_start, f_end, props.speed, eff_strength, seed_z)
                    kp = fc.keyframe_points[k_i]
                    kp.co = (f, v)
                    kp.handle_left_type = 'AUTO'
                    kp.handle_right_type = 'AUTO'
                fc.update()

                if props.loop_repeat:
                    cyc = next((m for m in fc.modifiers if m.type == 'CYCLES' and m.name == WIGGLE_BONE_CYCLES_MOD), None)
                    if not cyc:
                        cyc = fc.modifiers.new(type='CYCLES')
                        cyc.name = WIGGLE_BONE_CYCLES_MOD
                    cyc.mode_before = 'REPEAT'
                    cyc.mode_after = 'REPEAT'
                else:
                    for m in list(fc.modifiers):
                        if m.type == 'CYCLES' and m.name == WIGGLE_BONE_CYCLES_MOD:
                            fc.modifiers.remove(m)
    else:
        # Procedural Noise Modifiers
        for idx, bone in enumerate(target_bones):
            if bone.rotation_mode not in {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}:
                bone.rotation_mode = 'XYZ'

            depth = get_bone_hierarchy_depth(bone)
            hier_mult = calculate_bone_hierarchy_multiplier(depth, max_depth, props, arm_ob)
            spatial_off = calculate_bone_spatial_offset(arm_ob, bone, props)
            phase_offset = spatial_off + (depth * props.chain_wave) + (idx * props.chain_wave * 0.5)
            eff_strength = props.strength * hier_mult
            eff_scale = max(props.speed, 0.1)

            for axis_i in range(3):
                fc = ensure_bone_fcurve(arm_ob, bone, "rotation_euler", axis_i)
                if not fc:
                    continue

                for m in list(fc.modifiers):
                    if m.type == 'CYCLES' and m.name == WIGGLE_BONE_CYCLES_MOD:
                        fc.modifiers.remove(m)

                if len(fc.keyframe_points) > 1:
                    fc.keyframe_points.clear()
                    fc.keyframe_points.add(1)
                    fc.keyframe_points[0].co = (1.0, 0.0)

                mod = find_modifier(fc, WIGGLE_BONE_ROTATION_MOD) or find_modifier(fc, WIGGLE_BONE_PREFIX)
                if mod is None:
                    mod = fc.modifiers.new(type='NOISE')
                    mod.name = WIGGLE_BONE_ROTATION_MOD

                mod.scale = eff_scale
                mod.strength = eff_strength
                mod.phase = phase_offset + (axis_i * 123.45)
                mod.depth = 0
                mod.use_influence = True
                mod.influence = 1.0

    arm_ob.update_tag()


def remove_bone_wiggle(arm_ob, filter_mode='ALL'):
    if not arm_ob or arm_ob.type != 'ARMATURE':
        return

    fcurves = get_object_fcurves(arm_ob)
    if not fcurves:
        return

    target_bones = get_target_bones(arm_ob, filter_mode)
    target_data_paths = set(b.path_from_id("rotation_euler") for b in target_bones)

    to_remove_fcurves = []
    for fc in list(fcurves):
        if fc.data_path in target_data_paths and fc.data_path.startswith("pose.bones["):
            wiggle_mods = [m for m in fc.modifiers if m.name.startswith(WIGGLE_BONE_PREFIX) or m.name == WIGGLE_BONE_CYCLES_MOD]
            for m in wiggle_mods:
                fc.modifiers.remove(m)
            if len(fc.modifiers) == 0:
                to_remove_fcurves.append(fc)

    if to_remove_fcurves:
        anim_data = arm_ob.animation_data
        cb = None
        if hasattr(bpy_extras, "anim_utils"):
            cb = bpy_extras.anim_utils.animdata_get_channelbag_for_assigned_slot(anim_data)
        if cb:
            for fc in to_remove_fcurves:
                try:
                    cb.fcurves.remove(fc)
                except Exception:
                    pass
        elif anim_data and anim_data.action:
            for fc in to_remove_fcurves:
                try:
                    anim_data.action.fcurves.remove(fc)
                except Exception:
                    pass

    arm_ob.update_tag()


# ==============================================================================
# Property Sync & Update Callbacks
# ==============================================================================

def sync_props_from_modifiers(ob):
    global _is_syncing_props
    if not ob or _is_syncing_props:
        return

    fcurves = get_object_fcurves(ob)
    if not fcurves:
        return

    _is_syncing_props = True
    try:
        # Sync Object Wiggle Props
        obj_props = ob.noise_wiggler_obj_props
        has_obj_cycles = any(m.type == 'CYCLES' and m.name == WIGGLE_OBJ_CYCLES_MOD for fc in fcurves for m in fc.modifiers)
        if has_obj_cycles:
            obj_props.enable_loop = True
            for fc in fcurves:
                if fc.data_path in ("delta_rotation_euler", "delta_location") and len(fc.keyframe_points) > 1:
                    obj_props.loop_start = int(fc.keyframe_points[0].co[0])
                    obj_props.loop_end = int(fc.keyframe_points[-1].co[0])
                    break
        else:
            obj_props.enable_loop = False

        for fc in fcurves:
            if fc.data_path == "delta_rotation_euler":
                mod = find_modifier(fc, WIGGLE_OBJ_PREFIX) or find_modifier(fc, "Wiggle")
                if mod and mod.type == 'NOISE':
                    obj_props.rot_speed = mod.scale
                    obj_props.rot_strength = mod.strength
                    obj_props.rot_influence = mod.influence
                    if mod.use_restricted_range:
                        obj_props.use_restricted_range = True
                        obj_props.frame_start = mod.frame_start
                        obj_props.frame_end = mod.frame_end
                        obj_props.blend_in = mod.blend_in
                        obj_props.blend_out = mod.blend_out
                    break

        for fc in fcurves:
            if fc.data_path == "delta_location":
                mod = find_modifier(fc, WIGGLE_OBJ_PREFIX) or find_modifier(fc, "Wiggle")
                if mod and mod.type == 'NOISE':
                    obj_props.loc_speed = mod.scale
                    obj_props.loc_strength = mod.strength
                    obj_props.loc_influence = mod.influence
                    break

        # Sync Bone Wiggle Props (if Armature)
        if ob.type == 'ARMATURE':
            bone_props = ob.noise_wiggler_bone_props
            has_bone_cycles = any(m.type == 'CYCLES' and m.name == WIGGLE_BONE_CYCLES_MOD for fc in fcurves for m in fc.modifiers)
            if has_bone_cycles:
                bone_props.enable_loop = True
                for fc in fcurves:
                    if fc.data_path.startswith("pose.bones[") and len(fc.keyframe_points) > 1:
                        bone_props.loop_start = int(fc.keyframe_points[0].co[0])
                        bone_props.loop_end = int(fc.keyframe_points[-1].co[0])
                        break
            else:
                bone_props.enable_loop = False

            for fc in fcurves:
                if fc.data_path.startswith("pose.bones[") and "rotation_euler" in fc.data_path:
                    mod = find_modifier(fc, WIGGLE_BONE_PREFIX)
                    if mod and mod.type == 'NOISE':
                        bone_props.speed = mod.scale
                        bone_props.strength = mod.strength
                        break
    finally:
        _is_syncing_props = False


def on_object_prop_update(self, context):
    global _is_syncing_props, _is_updating_props
    if _is_syncing_props or _is_updating_props:
        return

    _is_updating_props = True
    try:
        source_ob = getattr(self, "id_data", None)
        if source_ob and isinstance(source_ob, bpy.types.Object):
            if has_object_wiggle(source_ob):
                apply_object_wiggle(source_ob, self)

        if context:
            active_ob = context.active_object
            sel_obs = context.selected_objects
            if source_ob == active_ob and sel_obs and len(sel_obs) > 1:
                for ob in sel_obs:
                    if ob != active_ob and has_object_wiggle(ob):
                        op = ob.noise_wiggler_obj_props
                        op.enable_rotation = self.enable_rotation
                        op.rot_speed = self.rot_speed
                        op.rot_strength = self.rot_strength
                        op.rot_phase = self.rot_phase
                        op.rot_influence = self.rot_influence

                        op.enable_location = self.enable_location
                        op.loc_speed = self.loc_speed
                        op.loc_strength = self.loc_strength
                        op.loc_phase = self.loc_phase
                        op.loc_influence = self.loc_influence

                        op.offset_mode = self.offset_mode
                        op.offset_axis = self.offset_axis
                        op.spatial_scale = self.spatial_scale
                        op.guide_object = self.guide_object
                        op.seed = self.seed
                        op.use_unique_seed = self.use_unique_seed

                        op.use_restricted_range = self.use_restricted_range
                        op.frame_start = self.frame_start
                        op.frame_end = self.frame_end
                        op.blend_in = self.blend_in
                        op.blend_out = self.blend_out

                        op.enable_loop = self.enable_loop
                        op.loop_start = self.loop_start
                        op.loop_end = self.loop_end
                        op.loop_repeat = self.loop_repeat

                        apply_object_wiggle(ob, op)
    finally:
        _is_updating_props = False


def on_bone_prop_update(self, context):
    global _is_syncing_props, _is_updating_props
    if _is_syncing_props or _is_updating_props:
        return

    _is_updating_props = True
    try:
        source_ob = getattr(self, "id_data", None)
        if source_ob and isinstance(source_ob, bpy.types.Object) and source_ob.type == 'ARMATURE':
            if has_bone_wiggle(source_ob):
                apply_bone_wiggle(source_ob, self)

        if context:
            active_ob = context.active_object
            armatures = [o for o in context.selected_objects if o and o.type == 'ARMATURE']
            if source_ob == active_ob and armatures and len(armatures) > 1:
                for arm in armatures:
                    if arm != active_ob and has_bone_wiggle(arm):
                        bp = arm.noise_wiggler_bone_props
                        bp.strength = self.strength
                        bp.speed = self.speed
                        bp.chain_wave = self.chain_wave
                        bp.randomness = self.randomness
                        bp.seed = self.seed

                        bp.falloff_enable = self.falloff_enable
                        bp.falloff_control_type = self.falloff_control_type
                        bp.falloff_amount = self.falloff_amount
                        bp.invert_falloff = self.invert_falloff

                        bp.offset_mode = self.offset_mode
                        bp.offset_axis = self.offset_axis
                        bp.spatial_scale = self.spatial_scale
                        bp.guide_object = self.guide_object

                        bp.enable_loop = self.enable_loop
                        bp.loop_start = self.loop_start
                        bp.loop_end = self.loop_end
                        bp.loop_repeat = self.loop_repeat

                        apply_bone_wiggle(arm, bp)
    finally:
        _is_updating_props = False


def bone_preset_update_callback(self, context):
    preset_key = self.preset
    if preset_key == 'CUSTOM' or preset_key not in BONE_PRESETS:
        return

    data = BONE_PRESETS[preset_key]
    self['strength'] = data['strength']
    self['speed'] = data['speed']
    self['chain_wave'] = data['chain_wave']
    self['randomness'] = data['randomness']
    self['falloff_enable'] = data['falloff_enable']
    self['falloff_amount'] = data['falloff_amount']
    self['invert_falloff'] = data['invert_falloff']
    self['falloff_control_type'] = data['falloff_control_type']
    self['offset_mode'] = data['offset_mode']

    on_bone_prop_update(self, context)


@persistent
def on_depsgraph_update_post(scene, depsgraph):
    global _last_active_object
    ctx = bpy.context
    active_ob = getattr(ctx, "active_object", None)
    if active_ob and active_ob != _last_active_object:
        _last_active_object = active_ob
        if has_object_wiggle(active_ob) or (active_ob.type == 'ARMATURE' and has_bone_wiggle(active_ob)):
            sync_props_from_modifiers(active_ob)


# ==============================================================================
# Property Groups
# ==============================================================================

class ObjectWiggleProperties(bpy.types.PropertyGroup):
    # Rotation
    enable_rotation: bpy.props.BoolProperty(
        name="Rotation",
        description="Enable procedural rotation noise on delta transform",
        default=True,
        update=on_object_prop_update,
    )
    rot_speed: bpy.props.FloatProperty(
        name="Speed",
        description="Noise speed/scale for rotation (higher = slower, smoother)",
        default=50.0,
        min=0.01,
        soft_max=500.0,
        update=on_object_prop_update,
    )
    rot_strength: bpy.props.FloatProperty(
        name="Strength",
        description="Noise amplitude for rotation",
        default=0.2,
        min=0.0,
        soft_max=10.0,
        update=on_object_prop_update,
    )
    rot_phase: bpy.props.FloatProperty(
        name="Phase Offset",
        description="Phase offset for rotation noise",
        default=0.0,
        update=on_object_prop_update,
    )
    rot_influence: bpy.props.FloatProperty(
        name="Influence",
        description="Influence blend factor",
        subtype="FACTOR",
        default=1.0,
        min=0.0,
        max=1.0,
        update=on_object_prop_update,
    )

    # Location
    enable_location: bpy.props.BoolProperty(
        name="Location",
        description="Enable procedural location noise on delta transform",
        default=True,
        update=on_object_prop_update,
    )
    loc_speed: bpy.props.FloatProperty(
        name="Speed",
        description="Noise speed/scale for location",
        default=50.0,
        min=0.01,
        soft_max=500.0,
        update=on_object_prop_update,
    )
    loc_strength: bpy.props.FloatProperty(
        name="Strength",
        description="Noise amplitude for location",
        default=0.2,
        min=0.0,
        soft_max=10.0,
        update=on_object_prop_update,
    )
    loc_phase: bpy.props.FloatProperty(
        name="Phase Offset",
        description="Phase offset for location noise",
        default=0.0,
        update=on_object_prop_update,
    )
    loc_influence: bpy.props.FloatProperty(
        name="Influence",
        description="Influence blend factor for location",
        subtype="FACTOR",
        default=1.0,
        min=0.0,
        max=1.0,
        update=on_object_prop_update,
    )

    # Restrict Range
    use_restricted_range: bpy.props.BoolProperty(
        name="Restrict Frame Range",
        description="Limit procedural noise to a specific frame range",
        default=False,
        update=on_object_prop_update,
    )
    frame_start: bpy.props.FloatProperty(name="Start", default=1.0, update=on_object_prop_update)
    frame_end: bpy.props.FloatProperty(name="End", default=250.0, update=on_object_prop_update)
    blend_in: bpy.props.FloatProperty(name="Blend In", default=0.0, min=0.0, update=on_object_prop_update)
    blend_out: bpy.props.FloatProperty(name="Blend Out", default=0.0, min=0.0, update=on_object_prop_update)

    # Looping
    enable_loop: bpy.props.BoolProperty(
        name="Seamless Loop",
        description="Evaluate circular noise for seamless looping without NLA",
        default=False,
        update=on_object_prop_update,
    )
    loop_start: bpy.props.IntProperty(name="Loop Start", default=1, update=on_object_prop_update)
    loop_end: bpy.props.IntProperty(name="Loop End", default=100, update=on_object_prop_update)
    loop_repeat: bpy.props.BoolProperty(name="Repeat with Cycles", default=True, update=on_object_prop_update)

    # Spatial Offsets
    offset_mode: bpy.props.EnumProperty(
        name="Offset Mode",
        items=[
            ('RANDOM', "Per-Object (Random)", "Individual random phase offset per object"),
            ('LINEAR', "Directional Wave", "Wave propagating along X, Y, or Z"),
            ('RADIAL', "Radial Ripple", "Concentric wave radiating from origin or guide"),
        ],
        default='RANDOM',
        update=on_object_prop_update,
    )
    offset_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[('X', "X", "X Axis"), ('Y', "Y", "Y Axis"), ('Z', "Z", "Z Axis")],
        default='X',
        update=on_object_prop_update,
    )
    guide_object: bpy.props.PointerProperty(type=bpy.types.Object, name="Guide Object", update=on_object_prop_update)
    spatial_scale: bpy.props.FloatProperty(name="Spatial Scale", default=10.0, min=0.001, update=on_object_prop_update)
    seed: bpy.props.IntProperty(name="Seed", default=0, update=on_object_prop_update)
    use_unique_seed: bpy.props.BoolProperty(name="Per-Object Variation", default=True, update=on_object_prop_update)


class BoneWiggleProperties(bpy.types.PropertyGroup):
    preset: bpy.props.EnumProperty(
        name="Preset",
        items=[
            ('CUSTOM', "Custom", "Custom user settings"),
            ('GENTLE_BREEZE', "Gentle Breeze (Foliage / Hair)", "Subtle, smooth motion with tips dampened"),
            ('STRONG_WIND', "Strong Wind (Trees / Flags)", "Dynamic gusts with whipped tips"),
            ('TAIL_TENTACLE', "Tail / Tentacle Flow", "Harmonic sinusoidal wave lag undulating down chain"),
            ('IDLE_BREATHE', "Subtle Idle / Breathing", "Slow, synchronized breathing shifts"),
            ('JIGGLE', "Fast Jiggle / Twitch", "Rapid jitter and independent bone shake"),
        ],
        default='GENTLE_BREEZE',
        update=bone_preset_update_callback,
    )
    bone_filter: bpy.props.EnumProperty(
        name="Target Bones",
        items=[('ALL', "All Bones", "All bones in armature"), ('DEFORM', "Deform Bones Only", "Deform-enabled bones only")],
        default='ALL',
        update=on_bone_prop_update,
    )
    strength: bpy.props.FloatProperty(name="Strength", default=0.06, min=0.0, soft_max=0.5, step=1, precision=3, update=on_bone_prop_update)
    speed: bpy.props.FloatProperty(name="Speed", default=50.0, min=0.1, soft_max=150.0, step=5, update=on_bone_prop_update)
    chain_wave: bpy.props.FloatProperty(name="Chain Wave", default=45.0, soft_min=-180.0, soft_max=180.0, update=on_bone_prop_update)
    randomness: bpy.props.FloatProperty(name="Randomness", default=0.4, min=0.0, max=1.0, subtype='FACTOR', update=on_bone_prop_update)
    seed: bpy.props.IntProperty(name="Seed", default=1, update=on_bone_prop_update)

    # Hierarchy Falloff
    falloff_enable: bpy.props.BoolProperty(name="Compensate Hierarchy", default=True, update=on_bone_prop_update)
    falloff_control_type: bpy.props.EnumProperty(
        name="Falloff Mode",
        items=[('SLIDER', "Slider Rate", "Simple decay rate slider"), ('CURVE', "Curve UI", "Interactive curve mapping")],
        default='SLIDER',
        update=on_bone_prop_update,
    )
    falloff_amount: bpy.props.FloatProperty(name="Falloff Rate", default=0.35, min=0.0, max=1.0, subtype='FACTOR', update=on_bone_prop_update)
    invert_falloff: bpy.props.BoolProperty(name="Invert (Tips Move More)", default=False, update=on_bone_prop_update)

    # Spatial Offsets
    offset_mode: bpy.props.EnumProperty(
        name="Offset Mode",
        items=[
            ('RANDOM', "Per-Bone (Random)", "Independent pseudo-random phase offset for each bone"),
            ('LINEAR', "Directional Wave", "Wave propagating along a world or guide axis"),
            ('RADIAL', "Radial Ripple", "Concentric wave ripple from origin or guide object"),
        ],
        default='RANDOM',
        update=on_bone_prop_update,
    )
    offset_axis: bpy.props.EnumProperty(
        name="Axis",
        items=[('X', "X", "X Axis"), ('Y', "Y", "Y Axis"), ('Z', "Z", "Z Axis")],
        default='Z',
        update=on_bone_prop_update,
    )
    spatial_scale: bpy.props.FloatProperty(name="Spatial Scale", default=10.0, min=0.001, update=on_bone_prop_update)
    guide_object: bpy.props.PointerProperty(type=bpy.types.Object, name="Guide Object", update=on_bone_prop_update)

    # Looping
    enable_loop: bpy.props.BoolProperty(name="Seamless Loop", default=False, update=on_bone_prop_update)
    loop_start: bpy.props.IntProperty(name="Loop Start", default=1, update=on_bone_prop_update)
    loop_end: bpy.props.IntProperty(name="Loop End", default=100, update=on_bone_prop_update)
    loop_repeat: bpy.props.BoolProperty(name="Repeat with Cycles", default=True, update=on_bone_prop_update)


# ==============================================================================
# Operators
# ==============================================================================

class NOISE_WIGGLER_OT_apply(bpy.types.Operator):
    bl_idname = "noise_wiggler.apply"
    bl_label = "Wiggle it!"
    bl_description = "Apply procedural noise to active/selected targets"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('OBJECT', "Object", "Apply to Object Delta Transforms"), ('BONE', "Bone", "Apply to Pose Bones")],
        default='OBJECT',
    )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None or len(context.selected_objects) > 0

    def execute(self, context):
        active_ob = context.active_object
        sel_obs = [o for o in context.selected_objects if o is not None]
        if not sel_obs and active_ob:
            sel_obs = [active_ob]

        if self.mode == 'OBJECT':
            for ob in sel_obs:
                if active_ob and ob != active_ob:
                    # Sync active props
                    ap = active_ob.noise_wiggler_obj_props
                    op = ob.noise_wiggler_obj_props
                    op.rot_speed, op.rot_strength, op.rot_phase, op.rot_influence, op.enable_rotation = ap.rot_speed, ap.rot_strength, ap.rot_phase, ap.rot_influence, ap.enable_rotation
                    op.loc_speed, op.loc_strength, op.loc_phase, op.loc_influence, op.enable_location = ap.loc_speed, ap.loc_strength, ap.loc_phase, op.loc_influence, ap.enable_location
                    op.offset_mode, op.offset_axis, op.spatial_scale, op.guide_object, op.seed, op.use_unique_seed = ap.offset_mode, ap.offset_axis, ap.spatial_scale, ap.guide_object, ap.seed, ap.use_unique_seed
                    op.use_restricted_range, op.frame_start, op.frame_end, op.blend_in, op.blend_out = ap.use_restricted_range, ap.frame_start, ap.frame_end, ap.blend_in, ap.blend_out
                    op.enable_loop, op.loop_start, op.loop_end, op.loop_repeat = ap.enable_loop, ap.loop_start, ap.loop_end, ap.loop_repeat
                apply_object_wiggle(ob, ob.noise_wiggler_obj_props)
            self.report({'INFO'}, f"Object Wiggle applied to {len(sel_obs)} object(s).")
        else:  # BONE
            armatures = [o for o in sel_obs if o.type == 'ARMATURE']
            if not armatures:
                self.report({'WARNING'}, "No armatures selected for Bone Wiggle.")
                return {'CANCELLED'}
            for arm in armatures:
                if active_ob and active_ob.type == 'ARMATURE' and arm != active_ob:
                    ap = active_ob.noise_wiggler_bone_props
                    bp = arm.noise_wiggler_bone_props
                    bp.strength, bp.speed, bp.chain_wave, bp.randomness, bp.seed = ap.strength, ap.speed, ap.chain_wave, ap.randomness, ap.seed
                    bp.falloff_enable, bp.falloff_control_type, bp.falloff_amount, bp.invert_falloff = ap.falloff_enable, ap.falloff_control_type, ap.falloff_amount, ap.invert_falloff
                    bp.offset_mode, bp.offset_axis, bp.spatial_scale, bp.guide_object = ap.offset_mode, ap.offset_axis, ap.spatial_scale, ap.guide_object
                    bp.enable_loop, bp.loop_start, bp.loop_end, bp.loop_repeat = ap.enable_loop, ap.loop_start, ap.loop_end, ap.loop_repeat
                apply_bone_wiggle(arm, arm.noise_wiggler_bone_props)
            self.report({'INFO'}, f"Bone Wiggle applied to {len(armatures)} armature(s).")

        return {'FINISHED'}


class NOISE_WIGGLER_OT_clear(bpy.types.Operator):
    bl_idname = "noise_wiggler.clear"
    bl_label = "Clear Wiggle"
    bl_description = "Remove procedural noise from active/selected targets"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('OBJECT', "Object", "Clear Object Delta Transforms"), ('BONE', "Bone", "Clear Pose Bones")],
        default='OBJECT',
    )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None or len(context.selected_objects) > 0

    def execute(self, context):
        sel_obs = [o for o in context.selected_objects if o is not None]
        if not sel_obs and context.active_object:
            sel_obs = [context.active_object]

        if self.mode == 'OBJECT':
            for ob in sel_obs:
                remove_object_wiggle(ob)
            self.report({'INFO'}, f"Object Wiggle cleared from {len(sel_obs)} object(s).")
        else:
            armatures = [o for o in sel_obs if o.type == 'ARMATURE']
            for arm in armatures:
                remove_bone_wiggle(arm, arm.noise_wiggler_bone_props.bone_filter)
            self.report({'INFO'}, f"Bone Wiggle cleared from {len(armatures)} armature(s).")

        return {'FINISHED'}


class NOISE_WIGGLER_OT_match_scene_range(bpy.types.Operator):
    bl_idname = "noise_wiggler.match_scene_range"
    bl_label = "Match Scene Range"
    bl_description = "Set loop start and end frames from current scene frame range"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[('OBJECT', "Object", ""), ('BONE', "Bone", "")], default='OBJECT')

    def execute(self, context):
        scene = context.scene
        sel_obs = [o for o in context.selected_objects if o is not None] or [context.active_object]
        if self.mode == 'OBJECT':
            for ob in sel_obs:
                ob.noise_wiggler_obj_props.loop_start = scene.frame_start
                ob.noise_wiggler_obj_props.loop_end = scene.frame_end
                if ob.noise_wiggler_obj_props.enable_loop and has_object_wiggle(ob):
                    apply_object_wiggle(ob, ob.noise_wiggler_obj_props)
        else:
            for arm in [o for o in sel_obs if o.type == 'ARMATURE']:
                arm.noise_wiggler_bone_props.loop_start = scene.frame_start
                arm.noise_wiggler_bone_props.loop_end = scene.frame_end
                if arm.noise_wiggler_bone_props.enable_loop and has_bone_wiggle(arm):
                    apply_bone_wiggle(arm, arm.noise_wiggler_bone_props)
        return {'FINISHED'}


class NOISE_WIGGLER_OT_reroll_seed(bpy.types.Operator):
    bl_idname = "noise_wiggler.reroll_seed"
    bl_label = "Randomize Seed"
    bl_description = "Assign a new random seed"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[('OBJECT', "Object", ""), ('BONE', "Bone", "")], default='OBJECT')

    def execute(self, context):
        new_seed = random.randint(0, 99999)
        sel_obs = [o for o in context.selected_objects if o is not None] or [context.active_object]
        if self.mode == 'OBJECT':
            for ob in sel_obs:
                ob.noise_wiggler_obj_props.seed = new_seed
                if has_object_wiggle(ob):
                    apply_object_wiggle(ob, ob.noise_wiggler_obj_props)
        else:
            for arm in [o for o in sel_obs if o.type == 'ARMATURE']:
                arm.noise_wiggler_bone_props.seed = new_seed
                if has_bone_wiggle(arm):
                    apply_bone_wiggle(arm, arm.noise_wiggler_bone_props)
        return {'FINISHED'}


class NOISE_WIGGLER_OT_sync(bpy.types.Operator):
    bl_idname = "noise_wiggler.sync"
    bl_label = "Sync from Curves"
    bl_description = "Read current F-Curve modifier values into the panel"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.active_object:
            sync_props_from_modifiers(context.active_object)
        return {'FINISHED'}


class NOISE_WIGGLER_OT_bake(bpy.types.Operator):
    bl_idname = "noise_wiggler.bake"
    bl_label = "Bake Keyframes"
    bl_description = "Bake procedural noise animation into raw keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[('OBJECT', "Object", ""), ('BONE', "Bone", "")], default='OBJECT')
    frame_start: bpy.props.IntProperty(name="Start Frame", default=1)
    frame_end: bpy.props.IntProperty(name="End Frame", default=250)
    frame_step: bpy.props.IntProperty(name="Frame Step", default=1, min=1)

    def invoke(self, context, event):
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        sel_obs = [o for o in context.selected_objects if o is not None] or [context.active_object]
        if self.mode == 'OBJECT':
            for ob in sel_obs:
                context.view_layer.objects.active = ob
                bpy.ops.nla.bake(
                    frame_start=self.frame_start,
                    frame_end=self.frame_end,
                    step=self.frame_step,
                    only_selected=False,
                    visual_keying=True,
                    use_current_action=True,
                    clean_curves=False,
                    bake_types={'OBJECT'}
                )
                remove_object_wiggle(ob)
            self.report({'INFO'}, f"Baked Object Wiggle to keyframes ({self.frame_start}-{self.frame_end}).")
        else:
            armatures = [o for o in sel_obs if o.type == 'ARMATURE']
            for arm in armatures:
                context.view_layer.objects.active = arm
                bpy.ops.object.mode_set(mode='POSE')
                bpy.ops.pose.select_all(action='SELECT')
                bpy.ops.nla.bake(
                    frame_start=self.frame_start,
                    frame_end=self.frame_end,
                    step=self.frame_step,
                    only_selected=False,
                    visual_keying=True,
                    use_current_action=True,
                    clean_curves=False,
                    bake_types={'POSE'}
                )
                remove_bone_wiggle(arm, 'ALL')
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'INFO'}, f"Baked Bone Wiggle to keyframes ({self.frame_start}-{self.frame_end}).")

        return {'FINISHED'}


# ==============================================================================
# UI Panel
# ==============================================================================

class NOISE_WIGGLER_PT_main_panel(bpy.types.Panel):
    bl_label = "Noise Wiggler"
    bl_idname = "NOISE_WIGGLER_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Noise Wiggler"

    def draw(self, context):
        layout = self.layout
        active_ob = context.active_object
        sel_obs = context.selected_objects
        sel_count = len(sel_obs)

        if not active_ob and sel_count == 0:
            box = layout.box()
            box.label(text="Select an object to add noise wiggle", icon='INFO')
            return

        target_ob = active_ob if active_ob else sel_obs[0]
        is_armature = (target_ob.type == 'ARMATURE')
        has_armatures_selected = any(o.type == 'ARMATURE' for o in sel_obs)

        # Mode Selector if Armatures present
        if is_armature or has_armatures_selected:
            row_mode = layout.row(align=True)
            row_mode.prop(target_ob, "noise_wiggler_ui_mode", expand=True)
            active_mode = target_ob.noise_wiggler_ui_mode
        else:
            active_mode = 'OBJECT'

        # Draw Mode-Specific Interface
        if active_mode == 'OBJECT':
            props = target_ob.noise_wiggler_obj_props
            is_active = has_object_wiggle(target_ob)

            # Top Buttons
            main_col = layout.column(align=True)
            row = main_col.row(align=True)
            row.scale_y = 1.3
            btn_label = f"Wiggle ({sel_count} Objects)" if sel_count > 1 else "Wiggle it!"
            op = row.operator("noise_wiggler.apply", text=btn_label, icon='PLAY')
            op.mode = 'OBJECT'

            rem_label = f"Remove ({sel_count} Objects)" if sel_count > 1 else "Remove Wiggle"
            op_rem = row.operator("noise_wiggler.clear", text=rem_label, icon='X')
            op_rem.mode = 'OBJECT'

            # Status row
            status_row = layout.row(align=True)
            status_row.label(text="Status: Object Wiggle Active" if is_active else "Status: No Object Wiggle", icon='CHECKMARK' if is_active else 'DOT')

            # Rotation Box
            rot_box = layout.box()
            rot_header = rot_box.row(align=True)
            rot_header.prop(props, "enable_rotation", text="Rotation Wiggle", icon='ORIENTATION_GIMBAL')
            if props.enable_rotation:
                col = rot_box.column(align=True)
                col.prop(props, "rot_speed")
                col.prop(props, "rot_strength")
                col.prop(props, "rot_phase")
                col.prop(props, "rot_influence")

            # Location Box
            loc_box = layout.box()
            loc_header = loc_box.row(align=True)
            loc_header.prop(props, "enable_location", text="Location Wiggle", icon='ORIENTATION_GLOBAL')
            if props.enable_location:
                col = loc_box.column(align=True)
                col.prop(props, "loc_speed")
                col.prop(props, "loc_strength")
                col.prop(props, "loc_phase")
                col.prop(props, "loc_influence")

            # Seamless Looping Box
            loop_box = layout.box()
            loop_header = loop_box.row(align=True)
            loop_header.prop(props, "enable_loop", text="Seamless Looping (No NLA)", icon='FILE_REFRESH')
            if props.enable_loop:
                col = loop_box.column(align=True)
                row = col.row(align=True)
                row.prop(props, "loop_start")
                row.prop(props, "loop_end")
                row2 = col.row(align=True)
                row2.prop(props, "loop_repeat")
                op_match = row2.operator("noise_wiggler.match_scene_range", text="Match Scene", icon='TIME')
                op_match.mode = 'OBJECT'

            # Frame Restriction
            if not props.enable_loop:
                range_box = layout.box()
                range_header = range_box.row(align=True)
                range_header.prop(props, "use_restricted_range", text="Restrict Frame Range", icon='PREVIEW_RANGE')
                if props.use_restricted_range:
                    col = range_box.column(align=True)
                    row = col.row(align=True)
                    row.prop(props, "frame_start")
                    row.prop(props, "frame_end")
                    row2 = col.row(align=True)
                    row2.prop(props, "blend_in")
                    row2.prop(props, "blend_out")

            # Spatial Offsets & Seed
            var_box = layout.box()
            var_box.label(text="Variation & Spatial Offsets", icon='SPHERE')
            col = var_box.column(align=True)
            col.prop(props, "offset_mode", text="Mode")
            if props.offset_mode == 'RANDOM':
                col.prop(props, "use_unique_seed")
            elif props.offset_mode == 'LINEAR':
                col.prop(props, "offset_axis", text="Axis")
                col.prop(props, "spatial_scale", text="Spatial Scale")
                col.prop(props, "guide_object", text="Guide Object")
            elif props.offset_mode == 'RADIAL':
                col.prop(props, "spatial_scale", text="Spatial Scale")
                col.prop(props, "guide_object", text="Guide Object")

            row_seed = col.row(align=True)
            row_seed.prop(props, "seed", text="Seed")
            op_seed = row_seed.operator("noise_wiggler.reroll_seed", text="", icon='FILE_REFRESH')
            op_seed.mode = 'OBJECT'

            # Footer
            layout.separator()
            col_footer = layout.column(align=True)
            op_bake = col_footer.operator("noise_wiggler.bake", text="Bake Keyframes", icon='ACTION')
            op_bake.mode = 'OBJECT'

        else:  # BONE MODE
            props = target_ob.noise_wiggler_bone_props
            is_active = has_bone_wiggle(target_ob)
            arm_count = len([o for o in sel_obs if o.type == 'ARMATURE'])

            # Top Buttons
            main_col = layout.column(align=True)
            row = main_col.row(align=True)
            row.scale_y = 1.3
            btn_label = f"Wiggle ({arm_count} Armatures)" if arm_count > 1 else "Wiggle it!"
            op = row.operator("noise_wiggler.apply", text=btn_label, icon='PLAY')
            op.mode = 'BONE'

            rem_label = f"Remove ({arm_count} Armatures)" if arm_count > 1 else "Clear Wiggle"
            op_rem = row.operator("noise_wiggler.clear", text=rem_label, icon='X')
            op_rem.mode = 'BONE'

            # Status row
            status_row = layout.row(align=True)
            status_row.label(text="Status: Bone Wiggle Active" if is_active else "Status: No Bone Wiggle", icon='CHECKMARK' if is_active else 'DOT')

            # Presets Header
            box_preset = layout.box()
            box_preset.label(text="Motion Preset", icon='PRESET')
            box_preset.prop(props, "preset", text="")

            # Target Bones
            row_scope = layout.row(align=True)
            row_scope.label(text="Bones:", icon='GROUP_BONE')
            row_scope.prop(props, "bone_filter", text="")

            # Motion Controls Box
            box_motion = layout.box()
            box_motion.label(text="Motion Controls", icon='RNDCURVE')
            col = box_motion.column(align=True)
            col.prop(props, "strength", text="Strength")
            col.prop(props, "speed", text="Speed")
            col.prop(props, "chain_wave", text="Chain Wave")
            col.prop(props, "randomness", text="Randomness")

            row_seed = col.row(align=True)
            row_seed.prop(props, "seed", text="Seed")
            op_seed = row_seed.operator("noise_wiggler.reroll_seed", text="", icon='FILE_REFRESH')
            op_seed.mode = 'BONE'

            # Hierarchy Falloff Box
            box_falloff = layout.box()
            header = box_falloff.row(align=True)
            header.prop(props, "falloff_enable", icon='FORCE_VORTEX', text="Hierarchy Falloff")
            if props.falloff_enable:
                box_falloff.prop(props, "falloff_control_type", expand=True)
                if props.falloff_control_type == 'SLIDER':
                    col_falloff = box_falloff.column(align=True)
                    col_falloff.prop(props, "falloff_amount", text="Falloff Rate")
                    col_falloff.prop(props, "invert_falloff", text="Invert (Tips Move More)")
                else:
                    node = get_or_create_falloff_curve_node(target_ob)
                    if node:
                        box_falloff.label(text="Root (0.0) → Tip (1.0):")
                        box_falloff.template_curve_mapping(node, "mapping", type='NONE')

            # Variation & Spatial Offsets
            box_var = layout.box()
            box_var.label(text="Variation & Spatial Offsets", icon='SPHERE')
            col_var = box_var.column(align=True)
            col_var.prop(props, "offset_mode", text="Mode")
            if props.offset_mode == 'LINEAR':
                col_var.prop(props, "offset_axis", text="Axis")
                col_var.prop(props, "spatial_scale", text="Spatial Scale")
                col_var.prop(props, "guide_object", text="Guide Object")
            elif props.offset_mode == 'RADIAL':
                col_var.prop(props, "spatial_scale", text="Spatial Scale")
                col_var.prop(props, "guide_object", text="Guide Object")

            # Seamless Looping Box
            box_loop = layout.box()
            header_loop = box_loop.row(align=True)
            header_loop.prop(props, "enable_loop", icon='TIME', text="Seamless Looping")
            if props.enable_loop:
                col_loop = box_loop.column(align=True)
                row_frames = col_loop.row(align=True)
                row_frames.prop(props, "loop_start", text="Start")
                row_frames.prop(props, "loop_end", text="End")
                row_loop_tools = col_loop.row(align=True)
                row_loop_tools.prop(props, "loop_repeat", text="Repeat Cycles")
                op_match = row_loop_tools.operator("noise_wiggler.match_scene_range", text="Match Scene", icon='TIME')
                op_match.mode = 'BONE'

            # Footer
            layout.separator()
            col_footer = layout.column(align=True)
            op_bake = col_footer.operator("noise_wiggler.bake", text="Bake Keyframes", icon='ACTION')
            op_bake.mode = 'BONE'


# ==============================================================================
# Registration
# ==============================================================================

classes = [
    ObjectWiggleProperties,
    BoneWiggleProperties,
    NOISE_WIGGLER_OT_apply,
    NOISE_WIGGLER_OT_clear,
    NOISE_WIGGLER_OT_match_scene_range,
    NOISE_WIGGLER_OT_reroll_seed,
    NOISE_WIGGLER_OT_sync,
    NOISE_WIGGLER_OT_bake,
    NOISE_WIGGLER_PT_main_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.noise_wiggler_ui_mode = bpy.props.EnumProperty(
        name="Mode",
        items=[('BONE', "Bone Wiggle", "Animate pose bone chains"), ('OBJECT', "Object Wiggle", "Animate object delta transforms")],
        default='BONE',
    )
    bpy.types.Object.noise_wiggler_obj_props = bpy.props.PointerProperty(type=ObjectWiggleProperties)
    bpy.types.Object.noise_wiggler_bone_props = bpy.props.PointerProperty(type=BoneWiggleProperties)

    # Legacy alias compatibility for smooth transitions
    bpy.types.Object.wiggle_props = bpy.props.PointerProperty(type=ObjectWiggleProperties)
    bpy.types.Object.armature_wiggle_props = bpy.props.PointerProperty(type=BoneWiggleProperties)

    if on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update_post)


def unregister():
    if on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update_post)

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for prop_name in ("noise_wiggler_ui_mode", "noise_wiggler_obj_props", "noise_wiggler_bone_props", "wiggle_props", "armature_wiggle_props"):
        if hasattr(bpy.types.Object, prop_name):
            try:
                delattr(bpy.types.Object, prop_name)
            except Exception:
                pass


if __name__ == "__main__":
    register()
