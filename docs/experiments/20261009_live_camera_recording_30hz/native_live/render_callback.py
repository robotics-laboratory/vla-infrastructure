"""Installed Kit110.3 / Replicator1.13.36 ungated callback candidate.

Import AFTER Kit/Replicator startup. No app.update(), render(), or orchestrator calls.

    import sys
    sys.path.insert(0, '/tmp/native-temporal-solution-20261010')
    from callback_candidate import NativeResultConsumer
    consumer = NativeResultConsumer(
        {'left_wrist': left_rp.path, 'right_wrist': right_rp.path,
         'scene': scene_rp.path}, on_frame=consume_owned_frame)
    # Keep the existing native physics/render loop. After its ordinary app.update:
    consumer.raise_if_failed()
    # Stop pumping before cleanup; consumer does not own/destroy render products.
    consumer.close()

on_frame receives one dict per completed role, with owned Warp CUDA RGBA and native
result metadata. It runs INSIDE OmniGraph compute: enqueue bounded work; do not
pump Kit, manipulate the graph, run physics or block on another thread requiring
Kit. Keep the array alive until NVENC and preview finish. The synchronous producer
stream copy is a correctness baseline, not an optimized asynchronous copy.

No source-state/action join is inferred; frame_identifier is render metadata.
This file is syntax-checked and source-audited, NOT Kit/GPU-tested.
"""
from collections import Counter
import time
import uuid


# Native types and fields are directly from installed OGN schemas.
_PIXEL_FIELDS = {
    'dataPtr': 'uint64', 'width': 'uint', 'height': 'uint',
    'bufferSize': 'uint64', 'strides': 'int[2]',
    'cudaDeviceIndex': 'int', 'format': 'uint64',
}
_ID_FIELDS = {
    'type': 'token', 'frameNumber': 'int64',
    'durationNumerator': 'int64', 'durationDenominator': 'uint64',
    'sampleTimeOffsetInSimFrames': 'uint64', 'externalTimeOfSimNs': 'int64',
    'rationalTimeOfSimNumerator': 'int64',
    'rationalTimeOfSimDenominator': 'uint64',
}


class NativeResultConsumer:
    def __init__(self, render_products, on_frame, resolution=(960, 600)):
        import omni.graph.core as og
        # Import registers the installed PostProcessDispatchUngated template.
        import omni.replicator.core  # noqa: F401
        import warp as wp
        from omni.gpu_foundation_factory import TextureFormat
        from omni.syntheticdata import SyntheticData as SD, SyntheticDataStage

        if len(render_products) != 3 or len(set(render_products.values())) != 3:
            raise ValueError('Provide three distinct existing render-product paths')
        if not callable(on_frame):
            raise TypeError('on_frame must be callable')
        self.og, self.wp, self.sd = og, wp, SD.Get()
        self.texture_format = TextureFormat
        if self.sd is None:
            raise RuntimeError('SyntheticData must already be initialized by Kit')
        for name in ('PostProcessDispatchUngated', 'LdrColorPostCopyToBuff'):
            if not SD.is_node_template_registered(name):
                raise RuntimeError(f'Required installed template missing: {name}')
        self.roles = {str(path): str(role) for role, path in render_products.items()}
        self.resolution = tuple(resolution)
        self.on_frame = on_frame
        self.counts, self.warmup_empty = Counter(), Counter()
        self.error, self.closed = None, False
        self._templates, self._attached = [], []
        self._attrs, self._streams = {}, {}
        self._registered = False
        suffix = uuid.uuid4().hex
        self._node_type = f'vla.audit.NativeResultConsumer_{suffix}'
        pointer_name = f'NativeLdrPointer_{suffix}'
        identifier_name = f'NativeIdentifier_{suffix}'
        consumer_name = f'NativeConsumer_{suffix}'
        self._consumer_name = consumer_name
        owner = self

        class CallbackNode:
            @staticmethod
            def get_node_type():
                return owner._node_type

            @staticmethod
            def initialize_type(node_type):
                node_type.add_input('inputs:exec', 'execution', True)
                node_type.add_input('inputs:renderProductPath', 'token', True)
                node_type.add_input('inputs:renderResults', 'uint64', True)
                node_type.add_input('inputs:cudaStream', 'uint64', True)
                for name, data_type in _PIXEL_FIELDS.items():
                    node_type.add_input(f'inputs:{name}', data_type, True)
                for name, data_type in _ID_FIELDS.items():
                    node_type.add_input(f'inputs:id_{name}', data_type, True)

            @staticmethod
            def compute(_context, node):
                if owner.closed or owner.error is not None:
                    return False
                try:
                    owner._receive(node)
                    return True
                except Exception as exc:
                    # OG catches exceptions; latch so the caller cannot miss failure.
                    owner.error = exc
                    return False

        self._callback_type = CallbackNode
        C, T = SD.NodeConnectionTemplate, SD.NodeTemplate
        stage = SyntheticDataStage.ON_DEMAND

        def register(name, node_type, connections, attributes=None):
            SD.register_node_template(
                T(stage, node_type, connections, attributes or {}),
                template_name=name)
            self._templates.append(name)

        try:
            og.register_node_type(CallbackNode, 1)
            self._registered = True
            # The native post-render texture-to-buffer chain creates LdrColorbuff.
            # Its inter-graph exec dependency follows the installed Ptr template.
            register(pointer_name, 'omni.syntheticdata.SdRenderVarPtr', [
                C('PostProcessDispatchUngated', attributes_mapping={
                    'outputs:exec': 'inputs:exec',
                    'outputs:renderResults': 'inputs:renderResults'}),
                C('LdrColorbuff', attributes_mapping={
                    'outputs:exec': 'inputs:exec'}),
            ], {'inputs:renderVar': 'LdrColorbuff'})
            # Strict execution chain: dispatch -> pointer -> identifier -> callback.
            # Metadata and pixels take the IDENTICAL per-product renderResults wire.
            register(identifier_name, 'omni.syntheticdata.SdFrameIdentifier', [
                C('PostProcessDispatchUngated', attributes_mapping={
                    'outputs:renderResults': 'inputs:renderResults'}),
                C(pointer_name, attributes_mapping={'outputs:exec': 'inputs:exec'}),
            ])
            register(consumer_name, self._node_type, [
                C(identifier_name, attributes_mapping={
                    'outputs:exec': 'inputs:exec',
                    **{f'outputs:{k}': f'inputs:id_{k}' for k in _ID_FIELDS}}),
                C(pointer_name, attributes_mapping={
                    f'outputs:{k}': f'inputs:{k}' for k in _PIXEL_FIELDS}),
                C('PostProcessDispatchUngated', attributes_mapping={
                    'outputs:renderResults': 'inputs:renderResults',
                    'outputs:cudaStream': 'inputs:cudaStream',
                    'outputs:renderProductPath': 'inputs:renderProductPath'}),
            ])
            for path in self.roles:
                # Record attempt before activation so partial setup can be unwound.
                self._attached.append(path)
                self.sd.activate_node_template(consumer_name, 0, [path])
        except BaseException:
            self.close()
            raise

    def _receive(self, node):
        og, wp = self.og, self.wp
        key = str(node.get_prim_path())
        attrs = self._attrs.get(key)
        if attrs is None:
            names = list(_PIXEL_FIELDS) + [f'id_{k}' for k in _ID_FIELDS]
            names += ['renderProductPath', 'renderResults', 'cudaStream']
            attrs = {name: node.get_attribute(f'inputs:{name}') for name in names}
            if not all(attr.is_valid() for attr in attrs.values()):
                raise RuntimeError('Consumer schema/connection mismatch')
            self._attrs[key] = attrs
        data = {name: og.AttributeValueHelper(attr).get() for name, attr in attrs.items()}
        path = str(data['renderProductPath'])
        if path not in self.roles:
            raise RuntimeError(f'Unexpected render product {path}')
        role = self.roles[path]
        ptr, width, height = int(data['dataPtr']), int(data['width']), int(data['height'])
        if not ptr or not width or not height:
            if self.counts[role]:
                raise RuntimeError(f'{role}: native CUDA output disappeared after warmup')
            self.warmup_empty[role] += 1
            return
        if (width, height) != self.resolution or int(data['cudaDeviceIndex']) != 0:
            raise RuntimeError(f'{role}: unexpected resolution/device')
        raw_strides = tuple(int(x) for x in data['strides'])
        if len(raw_strides) != 2:
            raise RuntimeError(f'{role}: invalid native strides')
        if any(raw_strides) and not all(raw_strides):
            raise RuntimeError(f'{role}: mixed-zero native strides')
        # Installed Replicator annotator_utils uses (strides[1], strides[0], sizeof(dtype)).
        strides = (raw_strides[1], raw_strides[0], 1) if all(raw_strides) else None
        if strides and (strides[1] != 4 or strides[0] < width * 4):
            raise RuntimeError(f'{role}: expected packed RGBA8 pixels')
        required = (height - 1) * (strides[0] if strides else width * 4) + width * 4
        size = int(data['bufferSize'])
        if size and size < required:
            raise RuntimeError(f'{role}: CUDA buffer is smaller than its image')
        native_format = self.texture_format(int(data['format']))
        if native_format.name not in ('RGBA8_UNORM', 'RGBA8_SRGB', 'RGBA8_UINT'):
            raise RuntimeError(f'{role}: unsupported native pixel format {native_format}')
        device = wp.get_device(f"cuda:{int(data['cudaDeviceIndex'])}")
        stream_ptr = int(data['cudaStream'])
        stream_key = (device.alias, stream_ptr)
        stream = self._streams.get(stream_key)
        if stream is None:
            stream = wp.Stream(device, cuda_stream=stream_ptr)
            self._streams[stream_key] = stream
        start = time.perf_counter_ns()
        with wp.ScopedStream(stream, sync_enter=False, sync_exit=False):
            borrowed = wp.array(ptr=ptr, dtype=wp.uint8, shape=(height, width, 4),
                                strides=strides, device=device, requires_grad=False)
            # clone() preserves strides; allocate explicitly for packed NVENC input.
            owned = wp.empty((height, width, 4), dtype=wp.uint8, device=device)
            wp.copy(owned, borrowed)
            wp.synchronize_stream(stream)
        identity = {k: (str(data[f'id_{k}']) if k == 'type' else int(data[f'id_{k}']))
                    for k in _ID_FIELDS}
        self.counts[role] += 1
        self.on_frame({
            'role': role, 'render_product': path, 'rgba': owned,
            'frame_identifier': identity, 'producer_cuda_stream': stream_ptr,
            'native_format': int(data['format']), 'copy_ns': time.perf_counter_ns() - start,
            # Diagnostic numeric receipt only; NEVER dereference or retain ownership via it.
            'render_result_handle_diagnostic': int(data['renderResults']),
        })

    def raise_if_failed(self):
        if self.error is not None:
            raise RuntimeError('Native result callback failed') from self.error

    def close(self):
        if self.closed:
            return
        self.closed = True
        failures = []
        for path in reversed(self._attached):
            try:
                self.sd.deactivate_node_template(self._consumer_name, 0, [path],
                                                deactivate_render_vars=True)
            except Exception as exc:
                failures.append(exc)
        self._attached.clear()
        for name in reversed(self._templates):
            try:
                self.sd.unregister_node_template(name)
            except Exception as exc:
                failures.append(exc)
        self._templates.clear()
        if self._registered:
            self.og.deregister_node_type(self._node_type)
            self._registered = False
        self._attrs.clear()
        self._streams.clear()
        if failures:
            raise RuntimeError('Callback cleanup incomplete') from failures[0]
