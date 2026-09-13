import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

import torch

from .attention import can_attempt_flash, is_flash_capability_error, install_nar_policy


class AttentionPolicyTests(unittest.TestCase):
    def test_cpu_never_requests_flash(self):
        model = SimpleNamespace(
            vae2llm=torch.nn.Linear(4, 4),
            config=SimpleNamespace(head_dim=128),
        )
        self.assertFalse(can_attempt_flash(model))

    def test_only_kernel_capability_errors_fallback(self):
        self.assertTrue(is_flash_capability_error(RuntimeError("No available kernel")))
        self.assertTrue(is_flash_capability_error(RuntimeError("FlashAttention is not supported")))
        self.assertTrue(is_flash_capability_error(RuntimeError("USE_FLASH_ATTENTION was not enabled for build.")))
        self.assertFalse(is_flash_capability_error(RuntimeError("CUDA out of memory")))

    def test_flash_probe_checks_compiled_support(self):
        model=SimpleNamespace(vae2llm=SimpleNamespace(parameters=lambda:iter([
            SimpleNamespace(device=SimpleNamespace(type='cuda'),dtype=torch.bfloat16)])),config=SimpleNamespace(head_dim=128))
        with patch('torch.backends.cuda.is_flash_attention_available',return_value=False):
            self.assertFalse(can_attempt_flash(model))

    def test_nar_fallback_preserves_offload_and_chunks(self):
        from yue2 import nar
        original=nar.synthesize
        mock=Mock(side_effect=[RuntimeError('No available kernel'), 'latents'])
        try:
            nar.synthesize=mock
            with patch('engine.attention.can_attempt_flash',return_value=True):
                audit=install_nar_policy('auto',64)
                self.assertEqual(nar.synthesize(None,[1],[2],42,offload_ar=True),'latents')
            self.assertEqual(mock.call_args_list[0].kwargs['attention'],'flash')
            self.assertEqual(mock.call_args.kwargs['attention'],'sdpa')
            self.assertEqual(mock.call_args.kwargs['query_chunk_size'],64)
            self.assertTrue(mock.call_args.kwargs['offload_ar'])
            self.assertEqual(audit()['fallback'],'true')
        finally:
            nar.synthesize=original


class ExternalFlashTests(unittest.TestCase):
    def test_external_rejection_restores_and_disables(self):
        from yue2 import nar
        from .attention import external_capability_error
        original, saved = nar.synthesize, nar.attention
        mock = Mock(side_effect=[RuntimeError("no kernel image is available"), "latents", "again"])
        try:
            nar.synthesize = mock
            with patch('engine.attention.external_flash_function', return_value=Mock()) as probe, patch('engine.attention.can_attempt_flash', return_value=False):
                audit = install_nar_policy('auto', 64)
                self.assertEqual(nar.synthesize(None,[1],[2],42,offload_ar=True), 'latents')
                self.assertEqual(audit()['fallback'], 'true')
                self.assertIs(nar.attention, saved)
                self.assertEqual(nar.synthesize(None,[1],[2],42), 'again')
                self.assertEqual(probe.call_count, 1)
            self.assertFalse(external_capability_error(RuntimeError('CUDA illegal memory access')))
            self.assertFalse(external_capability_error(torch.OutOfMemoryError('out of memory')))
        finally:
            nar.synthesize = original
            nar.attention = saved

    def test_external_model_failure_is_not_hidden(self):
        from yue2 import nar
        original, saved = nar.synthesize, nar.attention
        try:
            nar.synthesize = Mock(side_effect=RuntimeError('CUDA illegal memory access'))
            with patch('engine.attention.external_flash_function', return_value=Mock()):
                audit = install_nar_policy()
                with self.assertRaisesRegex(RuntimeError, 'illegal memory'):
                    nar.synthesize(None,[1],[2],42)
                self.assertEqual(audit()['selected'], 'external-flash-attn-2')
                self.assertIs(nar.attention, saved)
        finally:
            nar.synthesize = original
            nar.attention = saved

    @unittest.skipUnless(torch.cuda.is_available(), 'CUDA required')
    def test_actual_gpu_causal_offsets_and_nar_gqa(self):
        from .attention import external_attention
        try:
            from flash_attn import flash_attn_func
        except ImportError:
            self.skipTest('optional flash-attn is absent')
        torch.manual_seed(73)
        for causal, length in ((True, 257), (False, 513)):
            q=torch.randn(257,16,128,device='cuda',dtype=torch.bfloat16)
            k=torch.randn(length,8,128,device='cuda',dtype=torch.bfloat16)
            v=torch.randn_like(k)
            actual=external_attention(flash_attn_func,q,k,v,causal=causal,query_chunk_size=64)
            from torch.nn.attention import sdpa_kernel, SDPBackend
            with sdpa_kernel(SDPBackend.MATH):
                expected=torch.nn.functional.scaled_dot_product_attention(q.transpose(0,1)[None],k.transpose(0,1)[None],v.transpose(0,1)[None],is_causal=causal,enable_gqa=True)[0].transpose(0,1)
            torch.cuda.synchronize()
            self.assertTrue(actual.isfinite().all())
            torch.testing.assert_close(actual,expected,atol=0.008,rtol=0.03)

    @unittest.skipUnless(torch.cuda.is_available(), 'CUDA required')
    def test_real_nar_solver_uses_external_and_restores_function(self):
        from yue2 import nar
        from yue2.modeling_yue2 import YuE2Config, YuE2ForCausalLM
        try:
            import flash_attn
        except ImportError:
            self.skipTest('optional flash-attn is absent')
        config=YuE2Config(hidden_size=256, intermediate_size=512, num_hidden_layers=2,
            num_attention_heads=2, num_key_value_heads=1, head_dim=128,
            vocab_size=184704, max_position_embeddings=512, latent_dim=64,
            vae_latent_dim=64, max_latent_frames=512)
        torch.manual_seed(73)
        model=YuE2ForCausalLM(config).eval().to(device='cuda',dtype=torch.bfloat16)
        original, saved=nar.synthesize, nar.attention
        try:
            audit=install_nar_policy('auto',64)
            result=nar.synthesize(model,[2,3],list(range(65)),73,steps=32,offload_ar=True)
            self.assertEqual(audit()['selected'],'external-flash-attn-2')
            self.assertEqual(audit()['fallback'],'false')
            self.assertEqual(result.shape,(65,64))
            self.assertTrue(torch.as_tensor(result).isfinite().all())
            self.assertIs(nar.attention,saved)
        finally:
            nar.synthesize=original
            nar.attention=saved
            del model


if __name__ == "__main__":
    unittest.main()
