import unittest
from unittest.mock import Mock, patch

import torch
from yue2 import cuda_graph, modeling_yue2, pipeline
from yue2.modeling_yue2 import YuE2Config, YuE2ForCausalLM
from yue2.protocol import Sampling
from .ar_attention import (ExternalGraphAR, install_ar_policy, eager_flash_scope,
                           ExternalFlashUnavailable, GraphCaptureUnavailable)


class ARPolicyTests(unittest.TestCase):
    def setUp(self):
        self.original = pipeline.generate_tokens
        self.original_graph = cuda_graph.GraphAR
        self.original_sdpa = modeling_yue2.sdpa

    def tearDown(self):
        pipeline.generate_tokens = self.original
        self.assertIs(cuda_graph.GraphAR, self.original_graph)
        self.assertIs(modeling_yue2.sdpa, self.original_sdpa)

    def test_external_failure_restarts_phase_without_graph_and_is_audited(self):
        model = Mock(_yue2_fp8_originals={})
        fake = Mock(side_effect=[ExternalFlashUnavailable('no kernel image'),
                                ([], {'execution':'eager', 'attention':'sdpa'}, False)])
        pipeline.generate_tokens = fake
        with patch('engine.ar_attention.external_flash_function', return_value=Mock()):
            audit=install_ar_policy()
            pipeline.generate_tokens(model,[2],None,73,'abc',use_cuda_graph=True)
        self.assertEqual(fake.call_count,2)
        self.assertFalse(fake.call_args.kwargs['use_cuda_graph'])
        self.assertEqual(fake.call_args.args[3],73)
        self.assertTrue(audit()['phases']['abc']['fallback'])
        self.assertEqual(audit()['phases']['abc']['attention'],'sdpa')

    def test_capture_failure_keeps_external_eager(self):
        fake=Mock(side_effect=[GraphCaptureUnavailable('not supported during capture'),
                              ([],{'execution':'eager','attention':'sdpa'},False)])
        pipeline.generate_tokens=fake
        with patch('engine.ar_attention.external_flash_function',return_value=Mock()):
            audit=install_ar_policy()
            pipeline.generate_tokens(Mock(_yue2_fp8_originals={}),[2],None,73,'semantic')
        self.assertEqual(audit()['phases']['semantic']['attention'],'external-flash-attn-2')
        self.assertFalse(fake.call_args.kwargs['use_cuda_graph'])

    def test_fatal_cuda_error_not_retried(self):
        fake=Mock(side_effect=RuntimeError('CUDA illegal memory access'))
        pipeline.generate_tokens=fake
        with patch('engine.ar_attention.external_flash_function',return_value=Mock()):
            audit=install_ar_policy()
            with self.assertRaisesRegex(RuntimeError,'illegal memory'):
                pipeline.generate_tokens(Mock(_yue2_fp8_originals={}),[2],None,73,'abc')
        self.assertEqual(fake.call_count,1)
        self.assertEqual(audit()['phases']['abc']['status'],'failed')

    def test_explicit_sdpa_does_not_probe_external_or_enable_graph(self):
        pipeline.generate_tokens=Mock(return_value=([],{'execution':'eager','attention':'sdpa'},False))
        fake=pipeline.generate_tokens
        with patch('engine.ar_attention.external_flash_function') as probe:
            install_ar_policy('sdpa')
            pipeline.generate_tokens(Mock(_yue2_fp8_originals={}),[2],None,73,'abc')
            probe.assert_not_called()
        self.assertFalse(fake.call_args.kwargs['use_cuda_graph'])


@unittest.skipUnless(torch.cuda.is_available(), 'CUDA required')
class ARGPUChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flash_attn import flash_attn_func
        cls.flash=staticmethod(flash_attn_func)
        torch.manual_seed(146)
        cls.model=YuE2ForCausalLM(YuE2Config(hidden_size=256, intermediate_size=512,
            num_hidden_layers=2,num_attention_heads=2,num_key_value_heads=1,head_dim=128,
            vocab_size=184704,max_position_embeddings=512,max_latent_frames=512)).eval().to('cuda',torch.bfloat16)

    def test_graph_capture_parity_cfg_lengths_future_slots_and_replay(self):
        for prefixes in ([[2,3,4]], [[2,3,4,5],[6]]):
            with self.subTest(branches=len(prefixes)),torch.inference_mode():
                reference=cuda_graph.GraphAR(self.model,prefixes,6,capture=False,attention_backend='sdpa')
                candidate=ExternalGraphAR(self.model,prefixes,6,capture=True)
                try:
                    expected=reference.prefill()
                    actual=candidate.prefill()
                    torch.testing.assert_close(actual,expected,atol=.015,rtol=.03)
                    self.assertIsNotNone(candidate.graph)
                    for keys,values in zip(candidate.keys,candidate.values):
                        for branch,prefix in enumerate(prefixes):
                            keys[branch,len(prefix)+1:].fill_(100)
                            values[branch,len(prefix)+1:].fill_(-100)
                    pointers=[x.data_ptr() for x in candidate.keys+candidate.values]
                    for index,token in enumerate([7,8,9,10,11]):
                        actual=candidate.step(token).clone()
                        expected=reference.step(token).clone()
                        torch.cuda.synchronize()
                        torch.testing.assert_close(actual,expected,atol=.02,rtol=.04)
                        self.assertEqual(candidate.positions.tolist(),[len(p)+index+1 for p in prefixes])
                        self.assertEqual([x.data_ptr() for x in candidate.keys+candidate.values],pointers)
                finally:
                    candidate.close();reference.close()

    def test_eager_custom_mask_preserved(self):
        counters=dict(externalPrefillCalls=0,externalEagerDecodeCalls=0,maskedOrUnsupportedSdpaCalls=0)
        q=torch.randn(1,2,5,128,device='cuda',dtype=torch.bfloat16)
        k=torch.randn(1,1,5,128,device='cuda',dtype=torch.bfloat16)
        mask=torch.eye(5,device='cuda',dtype=torch.bool)
        expected=modeling_yue2.sdpa(q,k,k,attn_mask=mask)
        with eager_flash_scope(self.flash,counters):
            actual=modeling_yue2.sdpa(q,k,k,attn_mask=mask)
        torch.testing.assert_close(actual,expected,atol=0,rtol=0)
        self.assertEqual(counters['maskedOrUnsupportedSdpaCalls'],1)

    def test_real_sampling_graph_and_fp8_eager(self):
        from yue2.quantization import prepare_fp8_ar,restore_ar
        original=pipeline.generate_tokens
        try:
            for fp8 in (False,True):
                if fp8:
                    prepare_fp8_ar(self.model,'cuda')
                audit=install_ar_policy('auto')
                result=pipeline.generate_tokens(self.model,[2,3,4],Sampling(temperature=0,min_tokens=3,max_tokens=3),73,'abc',
                                               negative=[2,5],cfg_scale=1.5,use_cuda_graph=True)
                self.assertEqual(len(result[0]),3)
                record=audit()['phases']['abc']
                self.assertEqual(record['execution'],'eager' if fp8 else 'cuda_graph')
                self.assertIn('external-flash-attn-2',record['attention'])
                self.assertGreater(record['externalPrefillCalls'],0)
                if fp8:
                    self.assertGreater(record['externalEagerDecodeCalls'],0)
                pipeline.generate_tokens=original
        finally:
            restore_ar(self.model)
            pipeline.generate_tokens=original
