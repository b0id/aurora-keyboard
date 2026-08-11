"""
Context language model scorer (VOCAB_CONTEXT_SPEC.md sec6.1 alpha term,
Milestone 3b). Python port of FUTO's own reference implementation
(gitlab.futo.org/keyboard/swipe-library, src/context_lm.cpp), validated
empirically against the real hungry_jellyfish model before this was
written: forward()/get_embeddings() I/O shapes and vocab word-ID scheme
were confirmed by loading the actual model, and predict-next-word output
was checked for sanity ("how are" -> "you" ranked first, etc.) rather than
assumed from the header docs alone.

This is the real "context-awareness" component root cause 4 (sec2) needed -
a trained model, not a hand-built bigram table.
"""

from __future__ import annotations

try:
    from .vocab_hash import compute_hash_indices
except ImportError:
    from vocab_hash import compute_hash_indices

NUM_HASHES = 2  # fixed by FUTO's reference implementation (context_lm.cpp)


class ContextLMScorer:
    """Loaded hungry_jellyfish context LM: scores candidate words by how
    well they follow a rolling window of preceding words.

    Word IDs are 1-indexed by line position in the model's own paired
    vocab.txt (id 0 = <OOV> sentinel) - this is NOT the same ID scheme as
    the shared lexicon.py vocabulary (which is deduplicated/lowercased/
    reordered), since the model's embedding table rows are keyed to the
    exact raw vocab.txt line order it was trained against. Deviating from
    that order would silently misalign every score.
    """

    def __init__(self, torch_module, vocab_words: list[str]):
        self._module = torch_module
        self.word2id: dict[str, int] = {}
        self.word2id_lower: dict[str, int] = {}
        self.id2word: list[str] = ["<OOV>"]
        for i, word in enumerate(vocab_words):
            wid = i + 1
            self.word2id[word] = wid
            lowered = word.lower()
            if lowered != word:
                self.word2id_lower[lowered] = wid
            self.id2word.append(word)

        get_emb = torch_module.load_method("get_embeddings")
        exact_embed, exact_bias, hash_embed, hash_bias = get_emb.execute(())
        self.exact_embed = exact_embed
        self.exact_bias = exact_bias
        self.hash_embed = hash_embed
        self.hash_bias = hash_bias
        self.num_exact = exact_embed.shape[0]
        self.embed_dim = exact_embed.shape[1]
        self.num_buckets = hash_embed.shape[0]

        self._forward = torch_module.load_method("forward")
        self.max_context_len = self._probe_max_context_len()

    def _probe_max_context_len(self) -> int:
        """The forward method's expected context length isn't exposed via
        any metadata.json (see VOCAB_CONTEXT_SPEC.md sec2.1's ContextLM
        row) - ExecuTorch reports it in a resize error message when the
        guessed shape is wrong, so it's discovered by trying a small guess
        and reading the real shape back out of that error."""
        import torch

        for guess in (8, 16, 24, 32, 48, 64):
            try:
                ctx_ids = torch.zeros(1, guess, dtype=torch.int64)
                ctx_hashes = torch.zeros(1, guess, NUM_HASHES, dtype=torch.int64)
                self._forward.execute((ctx_ids, ctx_hashes))
                return guess
            except Exception as err:
                msg = str(err)
                # ExecuTorch's resize error embeds the real static shape,
                # e.g. "Expected shape (1, 16), but received (1, 8)."
                import re
                m = re.search(r"Expected shape \(1, (\d+)\)", msg)
                if m:
                    return int(m.group(1))
        raise RuntimeError("Could not determine context LM's max_context_len")

    def _lookup(self, word: str) -> tuple[int, list[int]]:
        wid = self.word2id.get(word)
        if wid is None:
            wid = self.word2id_lower.get(word.lower())
        if wid is not None:
            return wid, [0, 0]
        hashes = compute_hash_indices(word, self.num_buckets, NUM_HASHES)
        return self.num_exact, hashes

    def _run_backbone(self, context_words: list[str]):
        import torch

        L = self.max_context_len
        n_ctx = min(len(context_words), L)
        src_start = len(context_words) - n_ctx

        ctx_ids = torch.zeros(1, L, dtype=torch.int64)
        ctx_hashes = torch.zeros(1, L, NUM_HASHES, dtype=torch.int64)
        for i in range(n_ctx):
            wid, hashes = self._lookup(context_words[src_start + i])
            ctx_ids[0, i] = wid
            for k in range(NUM_HASHES):
                ctx_hashes[0, i, k] = hashes[k]

        out = self._forward.execute((ctx_ids, ctx_hashes))
        pos = max(0, n_ctx - 1)
        return out[0][0, pos]  # [embed_dim]

    def score(self, context_words: list[str], candidate_words: list[str]) -> list[float]:
        """log-likelihood-shaped score for each candidate given context,
        higher is better. Matches context_lm.cpp's score(): h.emb + bias,
        summing hash-bucket embeddings for out-of-vocab candidates."""
        if not candidate_words:
            return []

        h = self._run_backbone(context_words)
        scores = []
        for word in candidate_words:
            wid, hashes = self._lookup(word)
            if wid < self.num_exact:
                dot = float((h * self.exact_embed[wid]).sum())
                bias = float(self.exact_bias[wid])
            else:
                emb_sum = self.hash_embed[hashes[0]] + self.hash_embed[hashes[1]]
                bias = float(self.hash_bias[hashes[0]] + self.hash_bias[hashes[1]])
                dot = float((h * emb_sum).sum())
            scores.append(dot + bias)
        return scores


def load_context_lm(runtime_module_factory, vocab_words: list[str]) -> ContextLMScorer:
    """runtime_module_factory: a zero-arg callable returning a loaded
    ExecuTorch program for hungry_jellyfish/context_lm.pte (the caller
    owns the hf_hub_download/Runtime.get().load_program(...) call, since
    this module has no ExecuTorch/torch dependency at import time -
    keeping it host-importable like the rest of lexicon.py's dependents)."""
    return ContextLMScorer(runtime_module_factory(), vocab_words)
