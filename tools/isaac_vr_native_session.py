"""Compose main-scene media with the existing human S2 recording lifecycle."""
from __future__ import annotations

import json
from pathlib import Path


class NativeRuntimeSession:
    def __init__(self, env, args, *, media_type=None):
        from isaac_vr_runtime_profiles import load_runtime_profile
        from isaac_vr_native_bootstrap import retain

        self.profile = load_runtime_profile(args.vr_runtime_variant)
        if not self.profile['native']:
            raise ValueError('NativeRuntimeSession requires an explicit native profile')
        if media_type is None:
            from isaac_vr_native_media import NativeKitMedia
            media_type = NativeKitMedia
        options = dict(self.profile['media'])
        options['preview'] = bool(args.xr or args.demo_hud_on_start)
        options['prepared_source_layer'] = getattr(args, 'native_source_layer', None)
        output = Path(args.report).parent / 'native-camera'
        self.media = media_type(None, env, output, **options)
        if self.media.preview is not None:
            self.media.preview.set_visible(bool(args.demo_hud_on_start))
        retain(self.media)
        self.episodes, self.previous, self.stale = [], {}, {}
        self.last_sample = dict(valid=False, strictly_advanced=False, roles={})
        self.active = None
        self.closed = False

    def start_recording(self, record):
        if self.active is not None:
            raise RuntimeError('Previous native media episode is still attached')
        self.media.start_recording(record, Path(record.output_dir) / 'live_rgb')
        self.active = record

    def stop_recording(self):
        if self.active is None:
            return None
        record = self.active
        try:
            receipt = self.media.stop_recording()
        finally:
            self.active = None
        summary = dict(runtime=self.profile['name'], episode_id=record.episode_id,
                       path=str(Path(record.output_dir) / 'live_rgb'), media=receipt,
                       dataset_admissible=False)
        (Path(record.output_dir) / 'live_rgb_manifest.json').write_text(
            json.dumps(summary, indent=2) + '\n')
        self.episodes.append(summary)
        return summary

    def capture_boundary(self):
        self.last_sample = dict(valid=False, strictly_advanced=False, roles={})
        if self.active is None:
            self.media.capture_boundary()
        if not self.media.rows:
            raise RuntimeError('Native camera callback produced no complete triplet')
        row = self.media.rows[-1]
        results = row['native_result_identifiers']
        if set(results) != {'left_wrist', 'right_wrist', 'scene'}:
            raise RuntimeError('Native camera callback roles are incomplete')
        roles, next_stale, next_previous = {}, {}, {}
        for role, identity in results.items():
            frame = int(identity['frameNumber'])
            previous = self.previous.get(role)
            if previous is not None and frame < previous:
                raise RuntimeError('Native callback frame regressed without reset')
            advanced = previous is None or frame > previous
            next_stale[role] = 0 if advanced else self.stale.get(role, 0) + 1
            if next_stale[role] > 2:
                raise RuntimeError(f'Frozen native camera: {role}')
            roles[role] = dict(frame_index=frame, advanced=advanced)
            next_previous[role] = frame
        self.previous, self.stale = next_previous, next_stale
        self.last_sample = dict(valid=True, strictly_advanced=all(r['advanced'] for r in roles.values()),
                                roles=roles, source='main_kit_native_callback')
        return self.last_sample

    def reset(self):
        if self.active is not None:
            raise RuntimeError('Stop recording before resetting native media')
        self.media.reset_source_epoch()
        self.previous.clear()
        self.stale.clear()
        self.last_sample = dict(valid=False, strictly_advanced=False, roles={})

    def close(self):
        if not self.closed:
            try:
                self.stop_recording()
            finally:
                self.receipt = self.media.close()
                self.closed = True
        return self.receipt

    def report(self):
        return dict(profile=self.profile, episodes=self.episodes, last_camera=self.last_sample,
                    effective_physics=getattr(self, 'physics', None),
                    preview_layout=(self.media.preview.layout_report()
                                    if self.media.preview is not None
                                    and hasattr(self.media.preview, 'layout_report') else None),
                    media=getattr(self, 'receipt', None), dataset_admissible=False,
                    actual_quest_qualified=False)
