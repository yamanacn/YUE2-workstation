import unittest
from .performance import settings, token_budget

class PerformanceTests(unittest.TestCase):
    def test_default(self):
        p=settings({})
        self.assertTrue(p['offloadAr'])
        self.assertEqual(p['quantization'],'none')
        self.assertEqual(p['vaeCoreFrames'],512)

    def test_dynamic_budget(self):
        c={'maxTokens':9000,'performance':{'targetSeconds':180}}
        self.assertEqual(token_budget(c),5078)
        self.assertEqual(token_budget({'maxTokens':9000},60),1778)
        self.assertEqual(token_budget({'maxTokens':9000}),9000)
        self.assertEqual(token_budget({'maxTokens':1000},180),1000)
        self.assertEqual(token_budget({'maxTokens':9000,'performance':{'dynamicTokens':False}},60),9000)

    def test_invalid_settings(self):
        for patch in ({'offloadAr':'true'},{'memoryBudgetGiB':2},{'targetSeconds':float('nan')},{'vaeCoreFrames':0},{'quantization':'int4'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                settings({'performance':patch})
