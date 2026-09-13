# Third-party code notices

The Oobleck VAE and SnakeBeta implementation in `modeling_vae.py` is derived
from stable-audio-tools commit `a6ae0cdf8b2eb1567a4b42ceadddec3712d99d45`.
The module hierarchy, weight normalization and activation equations preserve
the checkpoint's original inference implementation.

- Oobleck / stable-audio-tools: Copyright (c) 2023 Stability AI, MIT.
  Full text: `vendor/yue2/licenses/stable-audio-tools-MIT.txt`.
- SnakeBeta / BigVGAN: Copyright (c) 2022 NVIDIA CORPORATION, MIT.
  Full text: `vendor/yue2/licenses/SnakeBeta-NVIDIA-MIT.txt`.

These notices cover the identified source code and retain its original licenses.
The YuE2 model checkpoint weights are separately licensed under CC BY-NC 4.0;
see `MODEL_LICENSE.md` for the scope and full terms. SheetSage2 and its MERT
parent are downloaded separately and retain the licenses shipped in their
official Hugging Face repositories. Python and JavaScript dependencies retain
their own licenses as recorded in package metadata and `studio/package-lock.json`.
This file does not relicense any third-party code, model, font, or asset.
