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


_SEMANTIC_FIELDS = {
    'sdIMNumSemantics': 'uint', 'sdIMNumSemanticTokens': 'uint',
    'sdIMMinSemanticIndex': 'uint', 'sdIMSemanticTokenMap': 'token[]',
    'sdIMSemanticWorldTransform': 'float[]',
    'sdIMLastUpdateTimeNumerator': 'int64',
    'sdIMLastUpdateTimeDenominator': 'uint64',
}
_PATH_FIELDS = {
    'primPaths': 'token[]', 'pathNumSemantics': 'uint',
    'pathMinSemanticIndex': 'uint', 'pathUpdateNumerator': 'int64',
    'pathUpdateDenominator': 'uint64',
}
_CAMERA_FIELDS = {
    'cameraViewTransform': 'matrixd[4]', 'cameraProjection': 'matrixd[4]',
    'renderProductResolution': 'int[2]',
}
_ATTRIBUTE_FIELDS = {'attributeData': 'uchar[]', 'attributeDataType': 'token',
                     'attributeBufferSize': 'uint', 'attributeWidth': 'uint', 'attributeHeight': 'uint'}


def decode_attribute_publication(data):
    """Native FabricReader CPU byte array, not a pointer or a current-stage query."""
    import numpy as np
    dtype = np.dtype(str(data['attributeDataType']))
    raw = np.array(data['attributeData'], dtype=np.uint8, copy=True).reshape(-1)
    shape = (int(data['attributeWidth']), int(data['attributeHeight']))
    if (dtype != np.dtype(np.int32) or int(data['attributeBufferSize']) != 4
            or raw.nbytes != 4 or shape != (1, 1)):
        raise ValueError(f'Unexpected native publication attribute layout: {dtype}, {raw.nbytes}, {shape}')
    value = int(raw.view(dtype)[0])
    if value < 1:
        raise ValueError('Native publication attribute is not initialized')
    return value


class NativeResultConsumer:
    def __init__(self, render_products, on_frame, resolution=(960, 600), *, geometry=False,
                 attribute_probe=False, attribute_probe_output=None, attribute_only=False, identity_only=False, cache_helpers=False):
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
        self.identity_only = bool(identity_only)
        self.attribute_only = bool(attribute_only or identity_only)
        self.geometry = bool(geometry) and not self.attribute_only
        self.camera_geometry = (self.geometry or self.attribute_only) and not self.identity_only
        self.attribute_probe = bool(attribute_probe or self.attribute_only)
        self.attribute_probe_diagnostics = []
        self._attribute_probe_stream = None
        if self.attribute_probe and not self.camera_geometry and not self.identity_only:
            raise ValueError('Attribute probe requires independent semantic stamp/camera comparison')
        if self.sd is None:
            raise RuntimeError('SyntheticData must already be initialized by Kit')
        required_templates = ['PostProcessDispatchUngated', 'LdrColorPostCopyToBuff']
        if self.attribute_probe:
            required_templates.append('GpuInteropEntry')
            if 'omni.replicator.nv.FabricReader' not in og.get_registered_nodes():
                raise RuntimeError('Installed native FabricReader node is not registered')
        if self.geometry:
            required_templates += ['InstanceMappingPre', 'InstanceMappingTransforms',
                                   'InstanceMappingPost', 'DefaultSemanticFilter',
                                   'DefaultSemanticFilterPost']
            for node_type in ('omni.syntheticdata.SdInstanceMappingPtr',
                              'omni.replicator.core.OgnPrimPaths'):
                if node_type not in og.get_registered_nodes():
                    raise RuntimeError(f'Required installed node type missing: {node_type}')
        if self.camera_geometry:
            required_templates.append('PostRenderProductCamera')
        for name in required_templates:
            if not SD.is_node_template_registered(name):
                raise RuntimeError(f'Required installed template missing: {name}')
        self.roles = {str(path): str(role) for role, path in render_products.items()}
        self.resolution = tuple(resolution)
        self.on_frame = on_frame
        self.counts, self.warmup_empty = Counter(), Counter()
        self.error, self.closed = None, False
        self._templates, self._attached = [], []
        self._attrs, self._streams = {}, {}
        self.cache_helpers, self._value_helpers = bool(cache_helpers), {}
        self._registered = False
        suffix = uuid.uuid4().hex
        self._node_type = f'vla.audit.NativeResultConsumer_{suffix}'
        pointer_name = f'NativeLdrPointer_{suffix}'
        mapping_name = f'NativeMapping_{suffix}'
        mapping_ptr_name = f'NativeMappingPtr_{suffix}'
        paths_name = f'NativePrimPaths_{suffix}'
        camera_name = f'NativeCamera_{suffix}'
        identifier_name = f'NativeIdentifier_{suffix}'
        consumer_name = f'NativeConsumer_{suffix}'
        attribute_pre, attribute_post = f'NativeAttribute_{suffix}PR', f'NativeAttribute_{suffix}'
        self._attribute_templates = (attribute_pre, attribute_post)
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
                if owner.geometry:
                    for name, data_type in {**_SEMANTIC_FIELDS, **_PATH_FIELDS}.items():
                        node_type.add_input(f'inputs:{name}', data_type, True)
                if owner.camera_geometry:
                    for name, data_type in _CAMERA_FIELDS.items():
                        node_type.add_input(f'inputs:{name}', data_type, True)
                if owner.attribute_probe:
                    for name, data_type in _ATTRIBUTE_FIELDS.items():
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

        def register(name, node_type, connections, attributes=None, pipeline_stage=None):
            SD.register_node_template(
                T(stage if pipeline_stage is None else pipeline_stage, node_type, connections, attributes or {}),
                template_name=name)
            self._templates.append(name)

        try:
            if self.attribute_probe and attribute_probe_output is not None:
                from pathlib import Path
                destination = Path(attribute_probe_output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._attribute_probe_stream = destination.open('x', buffering=1)
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
            if self.geometry:
                # Stock InstanceMappingWithTransforms dependencies, with ungated payload.
                # Cross-stage edges declare dependencies; scalars come from renderResults.
                register(mapping_name, 'omni.syntheticdata.SdInstanceMapping', [
                    C('PostProcessDispatchUngated', attributes_mapping={
                        'outputs:renderResults': 'inputs:renderResults'}),
                    C(pointer_name, attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    C('InstanceMappingTransforms', render_product_idxs=(),
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    # The stock post exporter creates an RP-prefixed SIM filter.
                    # Also declare the global filter beside the global controller
                    # used by InstanceMappingTransforms/InstanceMappingPost.
                    C('DefaultSemanticFilter', render_product_idxs=(),
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    # Export the named filter's label/path AOV for this result.
                    # The SIMULATION filter alone only declares the filter.
                    C('DefaultSemanticFilterPost',
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    C('InstanceMappingPost',
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                ])
                # Installed primPaths annotator composition, bound explicitly to
                # this callback's native result. Native C++ converts opaque path
                # tokens; Python never dereferences or guesses their ABI.
                register(mapping_ptr_name, 'omni.syntheticdata.SdInstanceMappingPtr', [
                    C('PostProcessDispatchUngated', attributes_mapping={
                        'outputs:renderResults': 'inputs:renderResults'}),
                    C(mapping_name, attributes_mapping={'outputs:exec': 'inputs:exec'}),
                ], {'inputs:cudaPtr': False})
                register(paths_name, 'omni.replicator.core.OgnPrimPaths', [
                    C(mapping_ptr_name, attributes_mapping={
                        'outputs:exec': 'inputs:exec',
                        'outputs:numSemantics': 'inputs:numSemantics',
                        'outputs:semanticPrimPathPtr': 'inputs:semanticPrimPathPtr'}),
                ])
            if self.camera_geometry:
                register(camera_name, 'omni.syntheticdata.SdRenderProductCamera', [
                    C('PostProcessDispatchUngated', attributes_mapping={
                        'outputs:renderResults': 'inputs:renderResults'}),
                    C(paths_name if self.geometry else pointer_name,
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    C('PostRenderProductCamera',
                      attributes_mapping={'outputs:exec': 'inputs:exec'}),
                ])
            if self.attribute_probe:
                attribute_settings = {'inputs:prims': ['/World/NativeSourceProofStamp'],
                                      'inputs:attribute': 'vla:publicationId'}
                # Installed stock AttributePR/Attribute native two-phase composition.
                register(attribute_pre, 'omni.replicator.nv.FabricReader', [C('GpuInteropEntry')],
                         attribute_settings, pipeline_stage=SyntheticDataStage.AUTO)
            # dispatch -> pointer -> mapping -> camera -> identifier -> callback.
            # Metadata and pixels take the IDENTICAL per-product renderResults wire.
            register(identifier_name, 'omni.syntheticdata.SdFrameIdentifier', [
                C('PostProcessDispatchUngated', attributes_mapping={
                    'outputs:renderResults': 'inputs:renderResults'}),
                C(camera_name if self.camera_geometry else pointer_name,
                  attributes_mapping={'outputs:exec': 'inputs:exec'}),
            ])
            if self.attribute_probe:
                register(attribute_post, 'omni.replicator.nv.FabricReader', [
                    C('PostProcessDispatchUngated', attributes_mapping={'outputs:renderResults': 'inputs:rp'}),
                    C(attribute_pre, attributes_mapping={'outputs:exec': 'inputs:exec'}),
                    # PR edge is an inter-graph dependency, not an ON_DEMAND
                    # execution pulse. Run PP after this frame's identifier.
                    C(identifier_name, attributes_mapping={'outputs:exec': 'inputs:exec'}),
                ], attribute_settings, pipeline_stage=SyntheticDataStage.AUTO)
            geometry_connections = [
                C(paths_name, attributes_mapping={'outputs:primPaths': 'inputs:primPaths'}),
                C(mapping_ptr_name, attributes_mapping={
                    'outputs:numSemantics': 'inputs:pathNumSemantics',
                    'outputs:minSemanticIndex': 'inputs:pathMinSemanticIndex',
                    'outputs:lastUpdateTimeNumerator': 'inputs:pathUpdateNumerator',
                    'outputs:lastUpdateTimeDenominator': 'inputs:pathUpdateDenominator'}),
                C(mapping_name, attributes_mapping={
                    f'outputs:{k}': f'inputs:{k}' for k in _SEMANTIC_FIELDS}),
            ] if self.geometry else []
            if self.camera_geometry:
                geometry_connections.append(C(camera_name, attributes_mapping={
                    f'outputs:{k}': f'inputs:{k}' for k in _CAMERA_FIELDS}))
            attribute_connections = [C(attribute_post, attributes_mapping={
                'outputs:exec': 'inputs:exec', 'outputs:data': 'inputs:attributeData',
                'outputs:dataType': 'inputs:attributeDataType', 'outputs:bufferSize': 'inputs:attributeBufferSize',
                'outputs:width': 'inputs:attributeWidth', 'outputs:height': 'inputs:attributeHeight',
            })] if self.attribute_probe else []
            register(consumer_name, self._node_type, geometry_connections + attribute_connections + [
                C(identifier_name, attributes_mapping={
                    **({} if self.attribute_probe else {'outputs:exec': 'inputs:exec'}),
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
                if self.attribute_probe:
                    ports = ['inputs:prims', 'inputs:attribute', 'inputs:rp', 'inputs:gpu',
                             'outputs:data', 'outputs:dataType', 'outputs:bufferSize',
                             'outputs:width', 'outputs:height']
                    for name in (attribute_pre, attribute_post):
                        values = self.sd.get_node_attributes(name, ports, path)
                        if values is None or set(values) != set(ports):
                            raise RuntimeError(f'Native FabricReader schema mismatch: {name}')
        except BaseException:
            self.close()
            raise

    def _receive(self, node):
        og, wp = self.og, self.wp
        key = str(node.get_prim_path())
        attrs = self._attrs.get(key)
        if attrs is None:
            names = list(_PIXEL_FIELDS) + [f'id_{k}' for k in _ID_FIELDS]
            if self.geometry:
                names += list(_SEMANTIC_FIELDS) + list(_PATH_FIELDS)
            if self.camera_geometry:
                names += list(_CAMERA_FIELDS)
            if self.attribute_probe:
                names += list(_ATTRIBUTE_FIELDS)
            names += ['renderProductPath', 'renderResults', 'cudaStream']
            attrs = {name: node.get_attribute(f'inputs:{name}') for name in names}
            if not all(attr.is_valid() for attr in attrs.values()):
                raise RuntimeError('Consumer schema/connection mismatch')
            self._attrs[key] = attrs
        data = self._read_values(key, attrs)
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
        if self.geometry:
            # Copy native CPU arrays while this render-result callback owns their scope.
            import numpy as np
            semantic_count = int(data['sdIMNumSemantics'])
            tokens = tuple(str(x) for x in data['sdIMSemanticTokenMap'])
            world = np.array(data['sdIMSemanticWorldTransform'], dtype=np.float32, copy=True)
            if world.size != semantic_count * 16:
                raise RuntimeError('Semantic transform array does not match native count')
            world = world.reshape(semantic_count, 4, 4)
            if bool(semantic_count) != bool(tokens):
                raise RuntimeError('Semantic token presence disagrees with native count')
            if semantic_count and len(tokens) % semantic_count:
                raise RuntimeError('Semantic token array does not divide into native rows')
            token_rows = (tuple(tokens[i:i + len(tokens) // semantic_count])
                          for i in range(0, len(tokens), len(tokens) // semantic_count)) if tokens else ()
            # Both native readers expose the same semantic-indexed table from
            # the exact same renderResults. Reject inconsistent extents/version.
            if (int(data['pathNumSemantics']) != semantic_count
                    or int(data['pathMinSemanticIndex']) != int(data['sdIMMinSemanticIndex'])
                    or int(data['pathUpdateNumerator']) != int(data['sdIMLastUpdateTimeNumerator'])
                    or int(data['pathUpdateDenominator']) != int(data['sdIMLastUpdateTimeDenominator'])):
                raise RuntimeError('Native semantic path/matrix table identity disagrees')
            prim_paths = tuple(str(x) for x in data['primPaths'])
            if len(prim_paths) != semantic_count:
                raise RuntimeError('Native semantic path count disagrees with matrix table')
            geometry = {
                'semantic_token_rows': tuple((path,) for path in prim_paths),
                'legacy_semantic_token_rows': tuple(token_rows),
                'semantic_path_authority': 'same_result_SdInstanceMappingPtr_OgnPrimPaths',
                'semantic_world_matrices': world,
                'semantic_min_index': int(data['sdIMMinSemanticIndex']),
                'semantic_num_tokens': int(data['sdIMNumSemanticTokens']),
                'semantic_update_time': (int(data['sdIMLastUpdateTimeNumerator']),
                                         int(data['sdIMLastUpdateTimeDenominator'])),
            }
            if not self.counts[role]:
                token_attr = attrs['sdIMSemanticTokenMap']
                upstream = token_attr.get_upstream_connections()
                geometry['token_transport_diagnostic'] = {
                    'consumer_controller_tokens': [str(x) for x in og.Controller(attribute=token_attr).get()],
                    'upstream': [{
                        'path': attr.get_path(),
                        'controller_tokens': [str(x) for x in og.Controller(attribute=attr).get()],
                        'helper_tokens': [str(x) for x in og.AttributeValueHelper(attr).get()],
                        'same_render_result': int(og.Controller(attribute=attr.get_node().get_attribute(
                            'inputs:renderResults')).get()) == int(data['renderResults']),
                    } for attr in upstream],
                    'default_filter': self.sd.get_node_attributes('DefaultSemanticFilter', [
                        'inputs:name', 'inputs:predicate', 'inputs:hierarchicalLabels',
                        'inputs:matchingLabels', 'outputs:name', 'outputs:predicate']),
                    'per_product_filter': self.sd.get_node_attributes('DefaultSemanticFilter', [
                        'inputs:name', 'inputs:predicate', 'inputs:hierarchicalLabels',
                        'inputs:matchingLabels', 'outputs:name', 'outputs:predicate'], path),
                    'global_controller': self.sd.get_node_attributes('InstanceMappingPre', [
                        'inputs:needTransform', 'inputs:semanticFilterPredicate']),
                    'per_product_controller': self.sd.get_node_attributes('InstanceMappingPre', [
                        'inputs:needTransform', 'inputs:semanticFilterPredicate'], path),
                    'post_mapping_filter': self.sd.get_node_attributes('InstanceMappingPost', [
                        'inputs:semanticFilterName'], path),
                    'post_filter': self.sd.get_node_attributes('DefaultSemanticFilterPost', [
                        'inputs:semanticFilterName', 'outputs:semanticFilterName',
                        'outputs:numSemantics', 'outputs:minSemanticIndex'], path),
                }
        if self.camera_geometry:
            import numpy as np
            if not self.geometry:
                geometry = {}
            geometry.update(
                camera_view=np.array(data['cameraViewTransform'], dtype=np.float64, copy=True).reshape(4, 4),
                camera_projection=np.array(data['cameraProjection'], dtype=np.float64, copy=True).reshape(4, 4),
                camera_resolution=tuple(int(x) for x in data['renderProductResolution']))
        attribute_id = None
        if self.attribute_probe:
            self._record_attribute_diagnostic(data, role, identity, attrs)
            attribute_id = decode_attribute_publication(data)
        self.counts[role] += 1
        self.on_frame({
            'role': role, 'render_product': path, 'rgba': owned,
            **({'result_geometry': geometry} if self.camera_geometry else {}),
            **({'attribute_publication_id': attribute_id} if self.attribute_probe else {}),
            'frame_identifier': identity, 'producer_cuda_stream': stream_ptr,
            'native_format': int(data['format']), 'copy_ns': time.perf_counter_ns() - start,
            # Diagnostic numeric receipt only; NEVER dereference or retain ownership via it.
            'render_result_handle_diagnostic': int(data['renderResults']),
        })

    def _read_values(self, key, attrs):
        """Cache public accessors only; fetch every value afresh inside this compute."""
        if self.closed:
            raise RuntimeError('Cannot read detached callback attributes')
        if not self.cache_helpers:
            return {name: self.og.AttributeValueHelper(attr).get() for name, attr in attrs.items()}
        helpers = self._value_helpers.get(key)
        if helpers is None:
            helpers = {name: self.og.AttributeValueHelper(attr) for name, attr in attrs.items()}
            self._value_helpers[key] = helpers
        return {name: helper.get() for name, helper in helpers.items()}

    def _record_attribute_diagnostic(self, data, role, identity, attrs):
        """Bounded raw public API evidence, including the first failed layout."""
        if len(self.attribute_probe_diagnostics) >= 16:
            return
        import json
        row = {'role': role, 'frame_identifier': identity,
               'consumer': {key: data[key] for key in _ATTRIBUTE_FIELDS},
               'render_result_handle_diagnostic': int(data['renderResults'])}
        try:
            ports = ['inputs:prims', 'inputs:attribute', 'inputs:rp', 'inputs:gpu',
                     'outputs:data', 'outputs:dataType', 'outputs:bufferSize', 'outputs:width', 'outputs:height']
            row['native_nodes'] = {name: self.sd.get_node_attributes(name, ports, str(data['renderProductPath']))
                                   for name in self._attribute_templates}
            upstream = attrs['attributeData'].get_upstream_connections()
            row['post_upstream'] = [{key: [a.get_path() for a in attr.get_node().get_attribute(key)
                                            .get_upstream_connections()]
                                     for key in ('inputs:exec', 'inputs:rp')} for attr in upstream]
            import omni.usd
            from usdrt import Usd as RtUsd
            context = omni.usd.get_context()
            stamp = '/World/NativeSourceProofStamp'
            usd_prim = context.get_stage().GetPrimAtPath(stamp)
            rt_prim = RtUsd.Stage.Attach(context.get_stage_id()).GetPrimAtPath(stamp)
            row['usd_attribute'] = usd_prim.GetAttribute('vla:publicationId').Get()
            row['fabric_attribute'] = rt_prim.GetAttribute('vla:publicationId').Get()
            row['fabric_export_tag'] = rt_prim.GetAttribute('fc_exportToRingbuffer').IsValid()
            row['fabric_property_names'] = [str(name) for name in rt_prim.GetPropertyNames()]
        except Exception as exc:
            row['diagnostic_error'] = repr(exc)
        encoded = json.dumps(row, default=lambda value: value.tolist() if hasattr(value, 'tolist') else str(value))
        self.attribute_probe_diagnostics.append(json.loads(encoded))
        if self._attribute_probe_stream is not None:
            self._attribute_probe_stream.write(encoded + '\n')

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
        self._value_helpers.clear()
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
        if self._attribute_probe_stream is not None:
            self._attribute_probe_stream.close()
        if failures:
            raise RuntimeError('Callback cleanup incomplete') from failures[0]
