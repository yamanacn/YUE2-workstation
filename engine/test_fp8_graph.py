import unittest
from unittest.mock import Mock,patch
import torch
from yue2 import pipeline,cuda_graph
from yue2.modeling_yue2 import YuE2Config,YuE2ForCausalLM
from yue2.protocol import Sampling
from yue2.quantization import prepare_fp8_ar,restore_ar
from engine.ar_attention import install_ar_policy,ExternalGraphAR,GraphCaptureUnavailable
from engine.performance import settings

class FP8GateTests(unittest.TestCase):
    def test_default_off_and_boolean_validation(self):
        self.assertFalse(settings({})['fp8CudaGraph'])
        with self.assertRaises(ValueError):settings({'performance':{'fp8CudaGraph':'true'}})

    def test_gate_requires_certificate_and_requested_switch(self):
        saved=pipeline.generate_tokens
        try:
            for enabled,passed,expected in [(False,True,False),(True,False,False),(True,True,True)]:
                fake=Mock(return_value=([],{'execution':'eager','attention':'sdpa'},False));pipeline.generate_tokens=fake
                with patch('engine.ar_attention.external_flash_function',return_value=Mock()),patch('engine.fp8_graph.validation_status',return_value={'validated':passed}) as validate:
                    install_ar_policy(fp8_cuda_graph=enabled)
                    pipeline.generate_tokens(Mock(_yue2_fp8_originals={'x':1}),[2],None,73,'abc',use_cuda_graph=True)
                    self.assertEqual(fake.call_args.kwargs['use_cuda_graph'],expected)
                    self.assertEqual(validate.call_count,int(enabled))
        finally:pipeline.generate_tokens=saved

    def test_capture_rejection_retries_fp8_eager_same_seed(self):
        saved=pipeline.generate_tokens
        try:
            fake=Mock(side_effect=[GraphCaptureUnavailable('not supported during capture'),([],{'execution':'eager','attention':'sdpa'},False)])
            pipeline.generate_tokens=fake
            with patch('engine.ar_attention.external_flash_function',return_value=Mock()),patch('engine.fp8_graph.validation_status',return_value={'validated':True}):
                audit=install_ar_policy(fp8_cuda_graph=True)
                pipeline.generate_tokens(Mock(_yue2_fp8_originals={'x':1}),[2],None,73,'abc',use_cuda_graph=True)
            self.assertFalse(fake.call_args.kwargs['use_cuda_graph']);self.assertEqual(fake.call_args.args[3],73)
            self.assertTrue(audit()['phases']['abc']['fallback'])
        finally:pipeline.generate_tokens=saved

@unittest.skipUnless(torch.cuda.is_available(),'CUDA required')
class FP8GraphGPU(unittest.TestCase):
    def test_cfg_scale_capture_and_sampling(self):
        model=YuE2ForCausalLM(YuE2Config(hidden_size=256,intermediate_size=512,num_hidden_layers=2,num_attention_heads=2,num_key_value_heads=1,head_dim=128,vocab_size=184704,max_position_embeddings=512,max_latent_frames=512)).eval().to('cuda',torch.bfloat16)
        saved=pipeline.generate_tokens
        try:
            prepare_fp8_ar(model,'cuda')
            with self.assertRaises(ValueError):ExternalGraphAR(model,[[2,3]],4)
            model._yue2_fp8_graph_validated=True
            with self.assertRaises(ValueError):cuda_graph.GraphAR(model,[[2,3]],4,fuse_projections=True)
            with torch.inference_mode():
                module=model.model.layers[0].self_attn.q_proj
                x=torch.randn(2,1,256,device='cuda',dtype=torch.bfloat16);x[1]*=10
                torch.testing.assert_close(module(x),torch.cat([module(x[:1]),module(x[1:])]),rtol=0,atol=0)
                a=ExternalGraphAR(model,[[2,3,4],[2,5]],10)
                b=ExternalGraphAR(model,[[2,3,4],[2,5]],10,capture=False)
                try:
                    torch.testing.assert_close(a.prefill(),b.prefill(),rtol=0,atol=0)
                    for t in range(6,12):torch.testing.assert_close(a.step(t),b.step(t),rtol=0,atol=0)
                finally:a.close();b.close()
            with patch('engine.fp8_graph.validation_status',return_value={'validated':True}):
                audit=install_ar_policy(fp8_cuda_graph=True)
                pipeline.generate_tokens(model,[2,3,4],Sampling(temperature=0,min_tokens=4,max_tokens=4),73,'abc',negative=[2,5],cfg_scale=1.5,use_cuda_graph=True)
                self.assertEqual(audit()['phases']['abc']['execution'],'cuda_graph')
        finally:restore_ar(model);pipeline.generate_tokens=saved
