"""Transparent CPU observer behavior; no CUDA or simulator imports."""

import json
from types import SimpleNamespace

import pytest

from tools.isaac_vr_native_profile import NativeProfile


class Sampler:
    def __init__(self, frame):
        self.frame, self.calls = frame, 0

    def capture_frame(self):
        self.calls += 1
        return self.frame


def objects(tmp_path, *, cprofile=False):
    frame, image, token = object(), object(), object()
    sampler = Sampler(frame)
    record = SimpleNamespace(sampler=sampler)
    calls = []
    cuda = SimpleNamespace(synchronize=lambda *a, **kw: calls.append(("sync", a, kw)))
    torch = SimpleNamespace(cuda=cuda, uint8="uint8", from_dlpack=lambda value: value)
    encoder = SimpleNamespace(submit=lambda value, tag: calls.append(("encode", value, tag)) or tag)
    preview = SimpleNamespace(publish=lambda tag, images: calls.append(("preview", tag, images)))
    fences = SimpleNamespace(stream=lambda stream: calls.append(("fence", stream)))
    media = SimpleNamespace(previous=lambda: (token, sampler.capture_frame()),
                            _pump=lambda: calls.append(("pump",)), encoders=[encoder],
                            preview=preview, fences=fences, torch=torch)
    env, perf = SimpleNamespace(), object()
    profile = NativeProfile(env=env, performance_logger=perf, record=record, media=media,
                            output=tmp_path / "profile.json", cprofile=cprofile)
    return profile, env, perf, sampler, media, torch, calls, frame, image, token


def test_observer_preserves_results_arguments_and_exact_call_count(tmp_path):
    profile, env, perf, sampler, media, torch, calls, frame, image, token = objects(tmp_path)
    images = {"scene": image}
    with profile:
        assert env.performance_logger is perf
        actual_token, actual_frame = media.previous()
        assert actual_token is token and actual_frame is frame
        assert media.encoders[0].submit(image, 17) == 17
        assert media.preview.publish(17, images) is None
        media.torch.cuda.synchronize(0)
        media.fences.stream("existing-stream")
        media._pump()
    assert sampler.calls == 1
    assert calls == [("encode", image, 17), ("preview", 17, images),
                     ("sync", (0,), {}), ("fence", "existing-stream"), ("pump",)]
    report = json.loads(profile.output.read_text())
    assert report["extra_gpu_work"] is False and not report["restore_errors"]
    assert report["stages"]["canonical_observation"]["count"] == 1
    assert report["stages"]["snapshot_recordables"]["count"] == 1


def test_torch_proxy_is_object_local_and_delegates_all_other_attributes(tmp_path):
    profile, env, perf, sampler, media, torch, calls, frame, image, token = objects(tmp_path)
    original_cuda, synchronize = torch.cuda, torch.cuda.synchronize
    with profile:
        assert media.torch is not torch
        assert media.torch.uint8 == torch.uint8
        assert media.torch.from_dlpack(image) is image
        assert torch.cuda is original_cuda and torch.cuda.synchronize is synchronize
    assert media.torch is torch


def test_restores_inherited_methods_and_prior_logger(tmp_path):
    profile, env, perf, sampler, media, torch, calls, frame, image, token = objects(tmp_path)
    original_logger = env.performance_logger = object()
    previous = media.previous
    assert "capture_frame" not in vars(sampler)
    profile.__enter__()
    profile.close()
    profile.close()
    assert "capture_frame" not in vars(sampler)
    assert env.performance_logger is original_logger
    assert media.previous is previous
    with pytest.raises(RuntimeError, match="one owner-thread scope"):
        profile.__enter__()


def test_failure_propagates_original_exception_and_restores(tmp_path):
    profile, env, perf, sampler, media, torch, calls, frame, image, token = objects(tmp_path)
    error = KeyboardInterrupt("source failure")

    def fail():
        raise error

    media.previous = fail
    with pytest.raises(KeyboardInterrupt) as caught:
        with profile:
            media.previous()
    assert caught.value is error
    assert media.previous is fail and media.torch is torch
    assert "performance_logger" not in vars(env)
    report = json.loads(profile.output.read_text())
    assert report["rows"][0]["succeeded"] is False


def test_cleanup_does_not_clobber_new_owner(tmp_path):
    profile, env, perf, sampler, media, torch, calls, frame, image, token = objects(tmp_path)
    profile.__enter__()
    new_owner = env.performance_logger = object()
    with pytest.raises(RuntimeError, match="ownership changed"):
        profile.close()
    assert env.performance_logger is new_owner
    assert media.torch is torch and "capture_frame" not in vars(sampler)


def test_no_media_and_optional_cprofile_artifact(tmp_path):
    env, sampler = SimpleNamespace(), Sampler(object())
    with NativeProfile(env=env, performance_logger=object(), record=SimpleNamespace(sampler=sampler),
                       media=None, output=tmp_path / "profile.json", cprofile=True) as profile:
        sampler.capture_frame()
    report = json.loads(profile.output.read_text())
    assert profile.output.with_suffix(".prof").is_file()
    assert report["cprofile"] == str(profile.output.with_suffix(".prof"))
    assert sampler.calls == 1 and "performance_logger" not in vars(env)
