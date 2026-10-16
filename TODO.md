# Noise Wiggler - Planned Work & Technical Debt

## Future Enhancements
- [ ] **Armature Mode Noise Stack & Sequencing**: Bring the multi-layer noise modifier stack (`UIList`, additive blending, frame-range sequencing) to Bone Wiggle mode.
- [ ] **Object Mode Presets**: Add motion preset system to Object Mode (matching Armature Mode presets).
- [ ] **Modular Code Refactoring**:
  - Split monolithic `__init__.py` into modular package structure (`properties/`, `operators/`, `ui/`, `core/`).
  - Align with standard repository packaging conventions while maintaining dual manifest/`bl_info` compatibility.
