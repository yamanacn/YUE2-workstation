import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import torch
from fastapi.testclient import TestClient
from torch import nn

from engine import adapters
from engine.service import create_app


def write_adapter(root, kind, family, files, sidecar):
    folder = Path(root) / kind / family
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).write_bytes(b'LoRA' + name.encode())
    (folder / 'adapter.json').write_text(json.dumps(sidecar, ensure_ascii=False), encoding='utf-8')
    return folder


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'loras'
        self.previous = adapters.LORA_ROOT
        adapters.LORA_ROOT = self.root
        adapters._HASHES.clear()

    def tearDown(self):
        adapters.LORA_ROOT = self.previous
        adapters._HASHES.clear()
        self.temporary.cleanup()

    def test_single_file_family_uses_short_id_and_nar_pairing(self):
        write_adapter(self.root, 'artist', 'guofeng', ['step-800.pt', 'best.pt'],
                      {'displayName': '国风战斗 v1', 'rank': 64, 'defaultFile': 'step-800.pt',
                       'recommendedNarAdapterId': 'nar/realaudio-v4'})
        write_adapter(self.root, 'nar', 'realaudio-v4', ['nar_lora_joint_v4.pt'],
                      {'displayName': 'Real Audio NAR v4', 'rank': 32, 'defaultFile': 'nar_lora_joint_v4.pt'})
        catalog = adapters.public_catalog()
        self.assertEqual([item['id'] for item in catalog['artist']],
                         ['artist/guofeng/step-800', 'artist/guofeng/best'])
        self.assertEqual([item['id'] for item in catalog['nar']], ['nar/realaudio-v4'])
        self.assertEqual(catalog['artist'][0]['bytes'], len(b'LoRAstep-800.pt'))
        self.assertNotIn('path', catalog['artist'][0])
        self.assertTrue(catalog['artist'][0]['default'])
        self.assertEqual(catalog['artist'][0]['recommendedNarAdapterId'], 'nar/realaudio-v4')

    def test_empty_registry_is_not_an_error(self):
        self.assertEqual(adapters.public_catalog(), {'artist': [], 'nar': []})
        self.assertIsNone(adapters.normalize_request(None))
        self.assertIsNone(adapters.normalize_request({'artistId': None, 'artistScale': 1.0, 'narEnabled': False}))

    def test_selection_validation(self):
        write_adapter(self.root, 'artist', 'guofeng', ['step-800.pt'], {'rank': 64})
        write_adapter(self.root, 'nar', 'realaudio-v4', ['nar.pt'], {'rank': 32})
        request = adapters.normalize_request({'artistId': 'artist/guofeng', 'artistScale': 1.25,
                                              'narId': 'nar/realaudio-v4', 'narEnabled': True})
        self.assertEqual(request['artist']['scale'], 1.25)
        self.assertEqual(request['nar']['id'], 'nar/realaudio-v4')
        for value, message in (
            ({'artistId': 'artist/nope/x', 'artistScale': 1.0}, '没有找到 LoRA'),
            ({'artistId': 'artist/guofeng', 'artistScale': 1.6}, 'artistScale'),
            ({'artistId': 'artist/guofeng', 'artistScale': True}, 'artistScale'),
            ({'narEnabled': True}, '必须选择 narId'),
            ({'artistId': 'artist/guofeng', 'oops': 1}, '未知字段'),
            ({'artistId': 'nar/realaudio-v4', 'artistScale': 1.0}, '不是风格 LoRA'),
            ({'narId': 'artist/guofeng', 'narEnabled': True}, '不是音色适配器'),
        ):
            with self.subTest(value=value):
                with self.assertRaises(adapters.AdapterError) as caught:
                    adapters.normalize_request(value)
                self.assertIn(message, str(caught.exception))

    def test_frozen_identity_detects_a_replaced_checkpoint(self):
        folder = write_adapter(self.root, 'artist', 'guofeng', ['step-800.pt'], {'rank': 64})
        request = adapters.normalize_request({'artistId': 'artist/guofeng', 'artistScale': 1.0})
        identity = adapters.adapter_identity(request)
        self.assertEqual(identity['artist']['bytes'], len(b'LoRAstep-800.pt'))
        self.assertIsNone(identity['nar'])
        adapters.verify_identity(identity, request)
        target = folder / 'step-800.pt'
        target.write_bytes(b'LoRAstep-800.pt' + b'x')
        os.utime(target, (0, 0))
        adapters._HASHES.clear()
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.verify_identity(identity, adapters.normalize_request(
                {'artistId': 'artist/guofeng', 'artistScale': 1.0}))
        self.assertEqual(caught.exception.code, 'adapter_changed')


class _Body(nn.Module):
    def __init__(self, size):
        super().__init__()
        self.layers = nn.ModuleList()
        for _ in range(1):
            layer = nn.Module()
            layer.self_attn = nn.Module()
            layer.mlp = nn.Module()
            for name in ('q_proj', 'k_proj', 'v_proj', 'o_proj'):
                setattr(layer.self_attn, name, nn.Linear(size, size, bias=False))
            for name in ('gate_proj', 'up_proj', 'down_proj'):
                setattr(layer.mlp, name, nn.Linear(size, size, bias=False))
            self.layers.append(layer)


class _Model(nn.Module):
    def __init__(self, size):
        super().__init__()
        self.model = _Body(size)


def build_tensors(size, rank, fill, count=7):
    tensors = []
    for index in range(count):
        first = torch.full((rank, size), fill) * (1 + index)
        second = torch.full((size, rank), fill * 0.5)
        tensors.extend([first, second])
    return tensors


class MergeTests(unittest.TestCase):
    def test_merge_folds_exactly_w_and_rejects_bad_shapes(self):
        size, rank, scale = 8, 4, 0.75
        model = _Model(size)
        tensors = build_tensors(size, rank, 0.01)
        linears = adapters.target_linears(model, adapters.ARTIST_TARGETS)
        self.assertEqual(len(linears), 7)
        self.assertEqual(adapters.validate_tensors(linears, tensors, 'artist'), 7)
        before = linears[0][1].weight.detach().clone()
        merged = adapters.merge_tensors(linears, tensors, scale, torch.device('cpu'))
        self.assertEqual(merged, 7)
        expected = before + scale * (tensors[1] @ tensors[0])
        self.assertTrue(torch.allclose(linears[0][1].weight, expected, atol=1e-6))
        self.assertFalse(torch.allclose(linears[0][1].weight, before))
        with self.assertRaises(adapters.AdapterError):
            adapters.validate_tensors(linears, tensors[:12], 'artist')
        broken = list(tensors)
        broken[0] = torch.zeros(rank + 1, size)
        with self.assertRaises(adapters.AdapterError):
            adapters.validate_tensors(linears, broken, 'artist')

    def test_checkpoint_without_lora_tensors_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'broken.pt'
            torch.save({'rank': 4}, path)
            with self.assertRaises(adapters.AdapterError):
                adapters.load_checkpoint(path)


class ServiceTests(unittest.TestCase):
    """The accept path: freeze the identity, and keep stock runs byte-identical."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = Path(self.temporary.name) / 'loras'
        write_adapter(self.registry, 'artist', 'guofeng', ['step-800.pt'], {'displayName': '国风战斗 v1', 'rank': 64})
        write_adapter(self.registry, 'nar', 'realaudio-v4', ['nar.pt'], {'displayName': 'Real Audio NAR v4', 'rank': 32})
        self.previous = adapters.LORA_ROOT
        adapters.LORA_ROOT = self.registry
        adapters._HASHES.clear()
        self.data = Path(self.temporary.name) / 'data'
        self.app = create_app(self.data, schedule=False, test_mode=True)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.state.store.db.close()
        adapters.LORA_ROOT = self.previous
        adapters._HASHES.clear()
        self.temporary.cleanup()

    def payload(self, adapters_value):
        draft = {'title': 'ADAPTER TEST', 'lyrics': '[Verse]\n测试', 'style': 'soft piano', 'count': 1,
                 'seedMode': 'fixed', 'seed': '831001',
                 'config': {'cot': 'off', 'temperature': 1, 'topP': .95, 'topK': 100, 'repetitionPenalty': 1.2,
                            'maxTokens': 200, 'odeSteps': 8, 'cfg': 'auto', 'adapters': adapters_value}}
        return {'requestId': str(uuid.uuid4()), 'draft': draft}

    def test_stock_run_keeps_the_old_identity_shape(self):
        response = self.client.post('/api/v1/batches', json=self.payload({'artistId': None, 'artistScale': 1.0,
                                                                          'narId': None, 'narEnabled': False}))
        self.assertEqual(response.status_code, 201, response.text)
        identities = response.json()['runs'][0]['snapshot']['modelIdentities']
        self.assertEqual(sorted(identities), ['mot', 'vae'])

    def test_accept_freezes_the_adapter_identity(self):
        response = self.client.post('/api/v1/batches', json=self.payload({
            'artistId': 'artist/guofeng', 'artistScale': 1.2, 'narId': 'nar/realaudio-v4', 'narEnabled': True}))
        self.assertEqual(response.status_code, 201, response.text)
        snapshot = response.json()['runs'][0]['snapshot']
        frozen = snapshot['modelIdentities']['adapters']
        self.assertEqual(frozen['artist']['id'], 'artist/guofeng')
        self.assertEqual(frozen['artist']['bytes'], len(b'LoRAstep-800.pt'))
        self.assertEqual(frozen['nar']['id'], 'nar/realaudio-v4')
        self.assertEqual(snapshot['draft']['config']['adapters']['artistScale'], 1.2)

    def test_unknown_adapter_is_rejected_before_the_run_exists(self):
        response = self.client.post('/api/v1/batches', json=self.payload({'artistId': 'artist/ghost', 'artistScale': 1.0}))
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('没有找到 LoRA', response.text)
        self.assertEqual(self.client.get('/api/v1/state').json()['runs'], [])

    def test_catalog_endpoint_hides_paths(self):
        response = self.client.get('/api/v1/adapters')
        self.assertEqual(response.status_code, 200, response.text)
        catalog = response.json()
        self.assertEqual([item['id'] for item in catalog['artist']], ['artist/guofeng'])
        self.assertEqual([item['id'] for item in catalog['nar']], ['nar/realaudio-v4'])
        self.assertNotIn('path', json.dumps(catalog))


if __name__ == '__main__':
    unittest.main()
