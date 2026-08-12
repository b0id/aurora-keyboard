"""
Layout-specific decoder refinement (VOCAB_CONTEXT_SPEC.md Milestone 3c).
Python wrapper for FUTO's `magic_macaw` DFSMN refiner, ported from their
reference implementation (gitlab.futo.org/keyboard/swipe-library,
src/decoder.cpp). Optional - the encoder's raw output already feeds beam
search correctly without this; this only refines it.

Takes the encoder's own outputs it already computes and currently discards
(coeffs, lam) concatenated with the compact log-probs beam search expects,
and returns refined log-probs in the exact same shape - a drop-in
replacement in the decode pipeline, no changes needed to beam_search.py
or trie.py.

Validated before writing this: loaded the real magic_macaw model, probed
its actual input/output shapes (confirmed [1,32,92] -> [1,32,27]), and
measured real before/after accuracy on a 31-word mixed set (24/31 -> 25/31
top-1) - a small net positive with real trade-offs (fixed "wonderful" and
"fox", broke "world"), consistent with FUTO's own published +0.55-0.76pt.
Not a strict improvement on every word, so it stays fully optional and
independently toggleable, same as the context LM.
"""

from __future__ import annotations

import re


class DecoderRefiner:
    """Loaded magic_macaw refiner. refine() takes the same compact
    log-probs beam search already consumes, plus the encoder's coeffs/lam
    outputs, and returns refined log-probs of identical shape."""

    def __init__(self, torch_module):
        self._forward = torch_module.load_method("forward")
        self.input_length, self.input_dim, self.num_classes = self._probe_shape()

    def _probe_shape(self) -> tuple[int, int, int]:
        """Neither dimension is published in any metadata.json - discovered
        the same way as context_lm.py's max_context_len: try a plausible
        guess, and if wrong, ExecuTorch's resize error embeds the real
        static shape ("Expected shape (1, 32, 92), but received ...")."""
        import torch

        for t_guess, d_guess in ((32, 92), (64, 92), (16, 92), (32, 64)):
            try:
                x = torch.zeros(1, t_guess, d_guess)
                out = self._forward.execute((x,))
                return t_guess, d_guess, out[0].shape[-1]
            except Exception as err:
                msg = str(err)
                m = re.search(r"Expected shape \(1, (\d+), (\d+)\)", msg)
                if m:
                    t, d = int(m.group(1)), int(m.group(2))
                    x = torch.zeros(1, t, d)
                    out = self._forward.execute((x,))
                    return t, d, out[0].shape[-1]
        raise RuntimeError("Could not determine decoder's expected input shape")

    def refine(self, log_probs, coeffs, lam):
        """log_probs: [T, K+1] compact array (same as beam_search.decode()'s
        input). coeffs: [T, coeff_dim] and lam: [T, 1], both straight from
        the encoder's own execute() call - already computed, just unused
        until now. Returns a refined [T, K+1] array, same shape."""
        import numpy as np
        import torch

        concat = np.concatenate([np.asarray(log_probs), np.asarray(coeffs), np.asarray(lam)], axis=1)
        if concat.shape != (self.input_length, self.input_dim):
            raise ValueError(
                f"decoder input shape mismatch: got {concat.shape}, expected ({self.input_length}, {self.input_dim})"
            )
        x = torch.from_numpy(concat[None].astype(np.float32))
        out = self._forward.execute((x,))
        return out[0][0].numpy()


def load_decoder_refiner(runtime_module_factory) -> DecoderRefiner:
    """runtime_module_factory: a zero-arg callable returning a loaded
    ExecuTorch program for magic_macaw/model_fp32.pte - same convention as
    context_lm.py's load_context_lm()."""
    return DecoderRefiner(runtime_module_factory())
