"""CPU ovstage hierarchy audit; never imports/creates Renderer or CUDA producer."""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import sys, json, pathlib, hashlib, traceback
sys.path.insert(0, '/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovrtx')
import numpy as np
import ovstage
from pxr import Usd, UsdGeom

root = pathlib.Path('/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009/reach-demo01')
seed = json.loads((root / 'mirror/seed.json').read_text())
source = Usd.Stage.Open(seed['overlay'])
body = seed['paths'][9]
instance = next(p for p in Usd.PrimRange(source.GetPrimAtPath(body)) if p.IsInstance())
mesh = next(p for p in Usd.PrimRange(instance, Usd.TraverseInstanceProxies()) if p.IsA(UsdGeom.Mesh))
paths = [body, str(instance.GetPath()), str(mesh.GetPath())]
receipt = {'probe': 'derived-world-matrix-change-membership', 'script_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
           'ovstage_version': ovstage.__version__, 'no_renderer': True,
           'cuda_visible_devices': os.environ['CUDA_VISIBLE_DEVICES'], 'paths': paths,
           'source_overlay_sha256': hashlib.sha256(pathlib.Path(seed['overlay']).read_bytes()).hexdigest(),
           'cases': []}

def read_one(stage, dictionary, path, name, ordinal):
    with dictionary.create_path_list_from_strings([path]) as plist:
        with stage.query_from_path_list(plist) as query:
            with stage.read_attributes(query, [dictionary.intern_token(name)],
                                       (ordinal if isinstance(ordinal, ovstage.OrdinalRange) else ovstage.OrdinalRange.latest(ordinal))) as read:
                read.wait()
                result = []
                for group in read.groups():
                    with group:
                        result.append(dict(ordinal=int(group.raw.ordinal), dtype=str(group.tensor(0).dtype), values=np.array(group.array(0)).tolist()))
                return result

for domain in [ovstage.PopulationDomain.RENDERING, ovstage.PopulationDomain.ALL]:
    case = {'domains': str(domain), 'domain_value': int(domain)}
    receipt['cases'].append(case)
    try:
        with ovstage.Stage('live30.cpu.hierarchy.audit', config=ovstage.StageConfig(
                runtime_default_hierarchy_computation_model=ovstage.HierarchyComputationModel.CPU_INCREMENTAL)) as stage:
            ovstage.population.open_usd(stage, seed['overlay'], ordinal=1, domains=domain)
            stage.advance_write_floor(1).wait()
            with ovstage.PathDictionary(stage) as dictionary:
                def read_all(n):
                    return {path: {attr: read_one(stage, dictionary, path, attr, n)
                                   for attr in ['omni:xform', 'omni:resetXformStack', 'omni:fabric:worldMatrix']}
                            for path in paths}
                case['populated'] = read_all(1)
                with dictionary.create_path_list_from_strings([body]) as plist:
                    with stage.query_from_path_list(plist) as query:
                        matrix = np.array(UsdGeom.XformCache().GetLocalToWorldTransform(source.GetPrimAtPath(body)))[None]
                        matrix[0, 3, 0] += 0.2
                        stage.write_attribute(query, 'omni:resetXformStack', 2,
                                              np.ones(1, dtype=np.bool_), is_array=False).wait()
                        stage.write_attribute(query, 'omni:xform', 2, matrix, is_array=False,
                                              semantic=ovstage.AttributeSemantic.MATRIX).wait()
                stage.advance_write_floor(2).wait()
                stage.compute_hierarchy(2, 2, ovstage.HierarchyComputationModel.CPU_INCREMENTAL)
                case['after_body_translate_x_0p2'] = read_all(2)
                case['changed_at_2'] = read_all(ovstage.OrdinalRange.between(2, 2))
    except BaseException:
        case['error'] = traceback.format_exc()
    pathlib.Path('/tmp/live30-meaningful-cpu-delta.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(case), flush=True)
